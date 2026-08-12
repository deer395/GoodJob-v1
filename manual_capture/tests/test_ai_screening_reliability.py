import json
import socket
from urllib.error import HTTPError

import pytest

from manual_capture.ai import AIConfig, AIUnavailable, OpenAIClient, ScreeningResult


def valid():
    return {"role_family": "产品", "relation_to_target_track": "same_track", "confidence": 80}


def response(content, finish_reason="stop"):
    class Reply:
        def read(self):
            return json.dumps({"choices": [{"finish_reason": finish_reason, "message": {"content": content}}]}).encode()
        def __enter__(self): return self
        def __exit__(self, *_): return False
    return Reply()


def test_normal_structured_response_is_consumed():
    result = ScreeningResult.model_validate(OpenAIClient._normalize_screening(valid()))
    assert result.relation_to_target_track == "same_track" and result.confidence == 80


def test_deepseek_strict_tool_schema_uses_non_thinking_transport(monkeypatch):
    captured = {}
    class Reply:
        def read(self):
            payload = {"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [{"function": {"name": "submit_career_track", "arguments": json.dumps(valid())}}]}}]}
            return json.dumps(payload).encode()
        def __enter__(self): return self
        def __exit__(self, *_): return False
    monkeypatch.setattr("manual_capture.ai.config", lambda: AIConfig("key", "https://api.deepseek.com", "deepseek-v4-flash"))
    def fake(request, **_kwargs):
        captured.update(json.loads(request.data.decode()))
        return Reply()
    monkeypatch.setattr("manual_capture.ai.urlopen", fake)
    assert OpenAIClient()._strict_screen_call("json", "payload") == valid()
    assert captured["thinking"] == {"type": "disabled"}
    assert captured["tools"][0]["function"]["strict"] is True


def test_code_fenced_json_is_safely_normalized():
    raw = "```json\n" + json.dumps(valid()) + "\n```"
    assert OpenAIClient._parse_json_content(raw) == valid()


@pytest.mark.parametrize(("raw", "category"), [
    ({"confidence": 70}, "missing_required_field"),
    ({"role_family": "x", "relation_to_target_track": "skill_related", "confidence": 70}, "invalid_enum"),
    ({"role_family": "x", "relation_to_target_track": "same_track", "confidence": 101}, "invalid_confidence"),
])
def test_schema_errors_are_classified(raw, category):
    with pytest.raises(AIUnavailable, match=category):
        OpenAIClient._normalize_screening(raw)


def test_extra_fields_are_ignored_without_changing_meaning():
    raw = {**valid(), "explanation": "unused", "score": 99}
    assert OpenAIClient._normalize_screening(raw) == valid()


@pytest.mark.parametrize("content,finish_reason,category", [
    ('{"role_family":', "stop", "json_parse_failure"),
    (json.dumps(valid()), "length", "truncated"),
])
def test_malformed_or_truncated_content_is_classified(monkeypatch, content, finish_reason, category):
    monkeypatch.setattr("manual_capture.ai.config", lambda: AIConfig("key", "https://example.test", "model"))
    monkeypatch.setattr("manual_capture.ai.urlopen", lambda *_args, **_kwargs: response(content, finish_reason))
    with pytest.raises(AIUnavailable, match=category):
        OpenAIClient()._call("json", "payload")


def test_timeout_retries_once_then_succeeds(monkeypatch):
    calls = {"value": 0}
    monkeypatch.setattr("manual_capture.ai.config", lambda: AIConfig("key", "https://example.test", "model"))
    monkeypatch.setattr("manual_capture.ai.time.sleep", lambda _: None)
    def fake(*_args, **_kwargs):
        calls["value"] += 1
        if calls["value"] == 1: raise socket.timeout()
        return response(json.dumps(valid()))
    monkeypatch.setattr("manual_capture.ai.urlopen", fake)
    assert OpenAIClient()._call("json", "payload") == valid()
    assert calls["value"] == 2


def test_timeout_retries_once_then_falls_back_to_error(monkeypatch):
    monkeypatch.setattr("manual_capture.ai.config", lambda: AIConfig("key", "https://example.test", "model"))
    monkeypatch.setattr("manual_capture.ai.time.sleep", lambda _: None)
    monkeypatch.setattr("manual_capture.ai.urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(socket.timeout()))
    with pytest.raises(AIUnavailable, match="timeout"):
        OpenAIClient()._call("json", "payload")


def test_provider_error_is_classified(monkeypatch):
    monkeypatch.setattr("manual_capture.ai.config", lambda: AIConfig("key", "https://example.test", "model"))
    monkeypatch.setattr("manual_capture.ai.urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(HTTPError("https://example.test", 500, "bad", {}, None)))
    with pytest.raises(AIUnavailable, match="provider_error"):
        OpenAIClient()._call("json", "payload")


def test_screen_retries_only_a_repairable_schema_failure(monkeypatch):
    client = OpenAIClient(); calls = {"value": 0}
    monkeypatch.setattr("manual_capture.ai.config", lambda: AIConfig("key", "https://api.deepseek.com", "deepseek-v4-flash"))
    monkeypatch.setattr("manual_capture.ai.time.sleep", lambda _: None)
    def strict(*_args):
        calls["value"] += 1
        return {"confidence": 80} if calls["value"] == 1 else valid()
    monkeypatch.setattr(client, "_strict_screen_call", strict)
    assert client.screen({"job": {}, "candidate": {}}).model_dump() == valid()
    assert calls["value"] == 2
