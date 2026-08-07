from pathlib import Path

from fastapi.testclient import TestClient

from manual_capture.ai import AIUnavailable, ExtractionResult, SemanticResult
from manual_capture.app import create_app


def test_missing_ai_config_keeps_manual_capture_available(tmp_path, monkeypatch):
    import manual_capture.ai as ai_module
    monkeypatch.setattr(ai_module, "ROOT", tmp_path)
    for key in ("AI_API_KEY", "AI_BASE_URL", "AI_MODEL"):
        monkeypatch.delenv(key, raising=False)
    client = TestClient(create_app(tmp_path / "ai.db"))
    assert client.get("/").status_code == 200
    assert "AI 尚未配置" in client.post("/ai/extract", data={"jd_text": "岗位"}).text


def test_extraction_requires_consent_and_never_creates_job(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "test-key"); monkeypatch.setenv("AI_BASE_URL", "http://local"); monkeypatch.setenv("AI_MODEL", "test")
    app = create_app(tmp_path / "ai.db"); client = TestClient(app)
    app.state.store.save_ai_settings(True)
    response = client.post("/ai/extract", data={"jd_text": "公司 A 招聘产品经理，地点北京"})
    assert "不会发送简历全文" in response.text and app.state.store.list() == []

    class Fake:
        def extract(self, text):
            return ExtractionResult.model_validate({"company":{"value":"公司 A","evidence":"公司 A"},"title":{"value":"产品经理","evidence":"招聘产品经理"},"city":{"value":"北京","evidence":"地点北京"},"deadline":{"value":"08-10","evidence":"截至 8 月 10 日"}})
    app.state.ai_client = Fake()
    response = client.post("/ai/extract", data={"jd_text":"x", "confirm_consent":"true"})
    assert "公司 A" in response.text and 'value=""' in response.text and app.state.store.list() == []


def test_schema_rejects_invalid_semantic_score():
    try:
        SemanticResult.model_validate({"ai_score": 101, "reasons": [], "risks": []})
    except Exception:
        return
    raise AssertionError("score outside 0-100 must be rejected")
