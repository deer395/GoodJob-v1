from pathlib import Path

from fastapi.testclient import TestClient

from manual_capture.ai import AIUnavailable, ExtractionResult, OpenAIClient, SemanticResult
from manual_capture.app import create_app, should_auto_apply_email
from manual_capture.email_processing import PARSER_VERSION


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


def test_email_parser_uses_ascii_wire_category(monkeypatch):
    client = OpenAIClient()
    monkeypatch.setattr(client, "_call", lambda *_: {"category": "exam", "company": "示例公司", "title": None, "scheduled_date": None, "summary": "请在指定时间内完成在线测评并注意浏览器兼容性", "confidence": 88.4})
    parsed = client.parse_email({"subject": "测评邀请", "sender_domain": "example.com", "snippet": "请完成测评"})
    assert parsed.category == "笔试" and parsed.confidence == 88 and parsed.scheduled_date == "" and len(parsed.summary) <= 30


def test_email_sync_button_runs_one_local_agent_once(tmp_path, monkeypatch):
    import subprocess
    import manual_capture.app as app_module
    monkeypatch.setattr(app_module.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "candidate emails: 2; dry-run=False\n", ""))
    client = TestClient(create_app(tmp_path / "sync.db"))
    response = client.post("/api/email-sync", follow_redirects=True)
    assert response.status_code == 200
    assert "检查到 2 封候选邮件" in response.text


def test_email_can_be_manually_recorded_and_explicitly_linked(tmp_path):
    app = create_app(tmp_path / "manual-link.db")
    store = app.state.store
    assert store.insert_email_event({"dedup_key": "test:manual-link", "subject": "示例公司在线测评邀请", "snippet": "请完成测评", "received_at": "2026-08-09T10:00:00", "category": "笔试", "summary": "测评通知", "confidence": 45})
    client = TestClient(app)
    response = client.post("/applications/manual", data={"company": "示例公司", "title": "产品经理", "city": "上海", "source": "其他", "email_event_id": 1}, follow_redirects=True)
    assert "已手动记录投递并关联邮件" in response.text
    assert store.application_by_id(1)["status"] == "测评/笔试"
    assert store.email_event(1)["status"] == "confirmed"


def test_empty_email_association_returns_guidance_instead_of_server_error(tmp_path):
    app = create_app(tmp_path / "empty-link.db")
    app.state.store.insert_email_event({"dedup_key": "test:empty-link", "subject": "示例测评", "snippet": "测评", "received_at": "2026-08-09T10:00:00", "category": "笔试", "summary": "测评通知", "confidence": 45})
    response = TestClient(app).post("/api/pending-events/1/confirm", data={}, follow_redirects=True)
    assert response.status_code == 200
    assert "请先选择一份已投递申请" in response.text


def test_auto_email_link_requires_high_confidence_and_exact_unique_job(tmp_path):
    store = create_app(tmp_path / "auto-link.db").state.store
    job_id = store.create({"company": "星河科技", "title": "数据产品经理", "city": "上海", "source": "其他", "application_url": "", "salary_range": "", "department": "", "description_text": "", "deadline": "", "note": ""})
    app_id = store.create_application(job_id)
    assert store.confirm_application(app_id)
    payload = {"category": "笔试", "confidence": 95, "company": "星河科技", "title": "数据产品经理"}
    assert should_auto_apply_email(payload, store) == app_id
    assert should_auto_apply_email({**payload, "confidence": 89}, store) is None
    assert should_auto_apply_email({**payload, "title": "产品经理"}, store) is None
    assert should_auto_apply_email({**payload, "category": "其他"}, store) is None


def test_email_event_stores_parser_version_and_progress_renders_email_view(tmp_path):
    app = create_app(tmp_path / "email-view.db")
    store = app.state.store
    store.insert_email_event({"dedup_key": "test:parser-version", "subject": "示例笔试", "snippet": "笔试通知", "received_at": "2026-08-09T10:00:00", "category": "笔试", "summary": "笔试通知", "confidence": 45})
    assert store.email_event(1)["parser_version"] == PARSER_VERSION
    page = TestClient(app).get("/progress?view=email")
    assert page.status_code == 200
    assert "同步邮箱" in page.text and "email-pending-queue" not in page.text


def test_primary_pages_expose_ai_settings_navigation(tmp_path):
    client = TestClient(create_app(tmp_path / "nav.db"))
    for path in ("/", "/jobs", "/applications", "/progress", "/profile", "/import", "/progress?view=calendar"):
        assert "AI 设置" in client.get(path).text
