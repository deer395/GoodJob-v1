from pathlib import Path

from fastapi.testclient import TestClient

from manual_capture.ai import AIUnavailable, ExtractionResult, OpenAIClient, SemanticResult
from manual_capture.app import create_app, should_auto_apply_email
from manual_capture.email_processing import EmailProposal, EmailUnderstanding, PARSER_VERSION


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
    monkeypatch.setattr(client, "_call", lambda *_: {"category": "exam", "company": "示例公司", "title": None, "scheduled_date": None, "action_deadline": "2026-08-12T20:00", "summary": "请在指定时间内完成在线测评并注意浏览器兼容性", "confidence": 88.4})
    parsed = client.parse_email({"subject": "测评邀请", "sender_domain": "example.com", "snippet": "请完成测评"})
    assert parsed.category == "笔试" and parsed.confidence == 88 and parsed.scheduled_date == "" and parsed.action_deadline == "2026-08-12T20:00" and len(parsed.summary) <= 30


def test_email_understanding_returns_cited_multiple_proposals(monkeypatch):
    client = OpenAIClient()
    monkeypatch.setattr(client, "_call", lambda *_: {"company": "星河科技", "title": "数据产品经理", "city": "上海", "proposals": [
        {"kind": "阶段推进", "category": "笔试", "summary": "通过筛选进入测评", "suggested_action": "完成在线测评", "scheduled_date": "", "action_deadline": "", "confidence": 90, "evidence_ids": [1]},
        {"kind": "行动截止", "category": "笔试", "summary": "测评截止", "suggested_action": "在截止前完成测评", "scheduled_date": "", "action_deadline": "2026-08-18T20:00", "confidence": 95, "evidence_ids": [2]},
    ]})
    parsed = client.understand_email({"subject": "测评邀请", "sender_domain": "example.com", "evidence": [{"id": 1, "text": "通过筛选"}, {"id": 2, "text": "2026-08-18 20:00 前完成"}]})
    assert len(parsed.proposals) == 2 and parsed.proposals[1].action_deadline == "2026-08-18T20:00"


def test_email_understanding_backfills_exam_stage_without_changing_relative_deadline(monkeypatch):
    client = OpenAIClient()
    monkeypatch.setattr(client, "_call", lambda *_: {"company": "", "title": "", "city": "", "proposals": [
        {"kind": "行动截止", "category": "笔试", "summary": "完成测评", "suggested_action": "完成", "location": "", "scheduled_date": "", "action_deadline": "2026-08-24T18:00", "confidence": 85, "evidence_ids": [1]},
    ]})
    parsed = client.understand_email({"subject": "测评", "sender_domain": "example.com", "evidence": [{"id": 1, "text": "收到本邮件后48小时内完成在线测评"}]})
    assert [(item.kind, item.category) for item in parsed.proposals] == [("阶段推进", "笔试"), ("行动截止", "笔试")]
    assert all(not item.action_deadline for item in parsed.proposals)


def test_relative_exam_stage_stays_confirmable_while_action_becomes_manual_reminder(tmp_path):
    app = create_app(tmp_path / "relative-exam-stage.db")
    store = app.state.store
    store.insert_email_event({"dedup_key": "relative-exam-stage", "subject": "测评", "snippet": "收到本邮件后48小时内完成测评", "received_at": "2026-08-20T10:00:00"})
    understanding = EmailUnderstanding(proposals=[
        EmailProposal(kind="阶段推进", category="笔试", summary="进入测评/笔试阶段", confidence=85, evidence_ids=[1]),
        EmailProposal(kind="行动截止", category="笔试", summary="48小时内完成测评", confidence=85, evidence_ids=[1]),
    ])
    store.update_email_understanding(1, understanding, ["收到本邮件后48小时内完成测评"])
    proposals = store.email_proposals(1)
    assert [(item["kind"], item["category"], item["action_deadline_at"]) for item in proposals] == [
        ("阶段推进", "笔试", None), ("提醒", "笔试", None),
    ]


def test_email_proposal_normalizes_space_separated_datetime_to_canonical_iso():
    proposal = EmailProposal(kind="阶段推进", category="面试", summary="一面", confidence=90, evidence_ids=[1], scheduled_date="2026-08-18 10:30")
    assert proposal.scheduled_date == "2026-08-18T10:30"


def test_email_understanding_without_explicit_deadline_becomes_manual_reminder(tmp_path):
    app = create_app(tmp_path / "email-reminder.db")
    store = app.state.store
    store.insert_email_event({"dedup_key": "reminder:1", "subject": "二面通知", "snippet": "暂无具体时间", "received_at": "2026-08-12T10:00:00"})
    store.update_email_understanding(1, EmailUnderstanding(proposals=[EmailProposal(kind="行动截止", category="面试", summary="确认面试", suggested_action="确认参加", confidence=60, evidence_ids=[1])]), ["暂无具体时间"])
    assert store.email_proposals(1)[0]["kind"] == "提醒"


def test_interview_primary_proposal_keeps_explicit_location_and_reply_deadline_visible(tmp_path):
    app = create_app(tmp_path / "email-location.db")
    store = app.state.store
    store.insert_email_event({"dedup_key": "location:1", "subject": "综合面试", "snippet": "面试通知", "received_at": "2026-08-12T10:00:00"})
    store.update_email_understanding(1, EmailUnderstanding(proposals=[
        EmailProposal(kind="阶段推进", category="面试", summary="综合面试", suggested_action="准备面试", location="北京市海淀区示例路1号", confidence=90, evidence_ids=[1]),
        EmailProposal(kind="行动截止", category="面试", summary="回复确认", action_deadline="2026-08-19T17:00", confidence=90, evidence_ids=[1]),
    ]), ["综合面试通知"])
    primary = store.email_proposals(1)[0]
    assert primary["location"] == "北京市海淀区示例路1号"
    assert "地点：北京市海淀区示例路1号" in primary["suggested_action"]
    assert "回复截止：2026-08-19T17:00" in primary["suggested_action"]


def test_email_proposals_are_independently_confirmable_and_manual_kinds_do_not_change_status(tmp_path):
    app = create_app(tmp_path / "proposal-flow.db")
    store = app.state.store
    job_id = store.create({"company": "星河科技", "title": "数据产品经理", "city": "上海", "source": "其他", "application_url": "", "salary_range": "", "department": "", "description_text": "", "deadline": "", "note": ""})
    app_id = store.create_application(job_id)
    assert store.confirm_application(app_id)
    store.insert_email_event({"dedup_key": "proposal:1", "subject": "测评", "snippet": "通过筛选", "received_at": "2026-08-12T10:00:00"})
    understanding = EmailUnderstanding(company="星河科技", title="数据产品经理", proposals=[
        EmailProposal(kind="阶段推进", category="笔试", summary="通过筛选", confidence=90, evidence_ids=[1]),
        EmailProposal(kind="行动截止", category="笔试", summary="测评截止", action_deadline="2026-08-18T20:00", confidence=95, evidence_ids=[1]),
        EmailProposal(kind="改期取消", category="面试", summary="原面试取消", confidence=95, evidence_ids=[1]),
    ])
    store.update_email_understanding(1, understanding, ["通过筛选并请在截止前完成测评"])
    proposals = store.email_proposals(1)
    store.resolve_email_proposal(proposals[0]["id"], app_id, "完成测评")
    assert store.application_by_id(app_id)["status"] == "测评/笔试"
    store.resolve_email_proposal(proposals[1]["id"], app_id)
    assert len(store.application_events(app_id)) == 3
    try:
        store.resolve_email_proposal(proposals[2]["id"], app_id)
    except ValueError:
        pass
    else:
        raise AssertionError("cancellation must remain manual")


def test_email_page_renders_cited_proposals_and_manual_cancellation_boundary(tmp_path):
    app = create_app(tmp_path / "proposal-page.db")
    store = app.state.store
    store.insert_email_event({"dedup_key": "proposal:page", "subject": "面试调整", "snippet": "原定面试取消", "received_at": "2026-08-12T10:00:00"})
    store.update_email_understanding(1, EmailUnderstanding(proposals=[EmailProposal(kind="改期取消", category="面试", summary="原定面试取消", suggested_action="人工核对后更新安排", confidence=95, evidence_ids=[1])]), ["原定于 2026-08-20 的面试取消"])
    page = TestClient(app).get("/progress?view=email")
    assert "原定面试取消" in page.text and "人工核对后更新安排" in page.text
    assert "不会自动改写既有事件或阶段" in page.text


def test_email_sync_button_runs_one_local_agent_once(tmp_path, monkeypatch):
    import subprocess
    import manual_capture.app as app_module
    monkeypatch.setattr(app_module.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, 'candidate emails: 2; dry-run=False\nsync-diagnostics: {"candidate_count": 2, "created_count": 1, "deduplicated_count": 1}\n', ""))
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


def test_manual_email_application_prefills_fields_confirms_time_and_returns_to_email(tmp_path):
    app = create_app(tmp_path / "manual-prefill.db")
    store = app.state.store
    store.insert_email_event({"dedup_key": "test:manual-prefill", "subject": "星河科技测评", "snippet": "岗位：数据产品经理，工作地：上海", "received_at": "2026-08-09T10:00:00", "category": "笔试", "summary": "测评通知", "confidence": 45, "company": "星河科技", "title": "数据产品经理", "city": "上海", "proposed_action_deadline_at": "2026-08-12T20:00"})
    client = TestClient(app)
    form = client.get("/applications?manual_event=1")
    assert 'value="星河科技"' in form.text and 'value="数据产品经理"' in form.text and 'value="上海"' in form.text
    response = client.post("/applications/manual", data={"company": "星河科技", "title": "数据产品经理", "city": "上海", "source": "其他", "email_event_id": 1, "confirm_action_deadline": "true", "return_to": "email"}, follow_redirects=False)
    assert response.headers["location"].startswith("/progress?view=email")
    linked = next(event for event in store.application_events(1) if event["event_type"] == "笔试通知")
    assert linked["action_deadline_at"] == "2026-08-12T20:00"


def test_email_page_opens_editable_manual_dialog_without_workspace_navigation(tmp_path):
    app = create_app(tmp_path / "email-dialog.db")
    store = app.state.store
    store.insert_email_event({"dedup_key": "test:email-dialog", "subject": "星河科技测评", "snippet": "岗位：数据产品经理，工作地：上海", "received_at": "2026-08-09T10:00:00", "category": "笔试", "summary": "测评通知", "confidence": 45, "company": "星河科技", "title": "数据产品经理", "city": "上海", "proposed_action_deadline_at": "2026-08-12T20:00"})
    page = TestClient(app).get("/progress?view=email")
    assert 'id="manual-email-1"' in page.text
    assert 'name="event_category"' in page.text and 'name="action_deadline_at"' in page.text
    assert 'value="星河科技"' in page.text and 'value="数据产品经理"' in page.text and 'value="上海"' in page.text


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


def test_email_link_never_reopens_ended_application_or_duplicates_one_email_event(tmp_path):
    app = create_app(tmp_path / "email-state-safety.db")
    store = app.state.store
    job_id = store.create({"company": "状态公司", "title": "产品经理", "city": "北京", "source": "其他", "application_url": "", "salary_range": "", "department": "", "description_text": "", "deadline": "", "note": ""})
    app_id = store.create_application(job_id)
    assert store.confirm_application(app_id)
    store.advance_application(app_id, "已结束", "拒信", "2026-08-09")
    payload = {"category": "笔试", "confidence": 95, "company": "状态公司", "title": "产品经理"}
    assert should_auto_apply_email(payload, store) is None
    store.insert_email_event({"dedup_key": "test:ended", "subject": "笔试", "snippet": "通知", "received_at": "2026-08-09T10:00:00", **payload})
    try:
        store.resolve_email_event(1, "confirmed", app_id)
    except ValueError:
        pass
    else:
        raise AssertionError("ended application must not be advanced")
    assert store.application_by_id(app_id)["status"] == "已结束"
    assert store.email_event(1)["status"] == "pending"

    active_job = store.create({"company": "幂等公司", "title": "算法工程师", "city": "上海", "source": "其他", "application_url": "", "salary_range": "", "department": "", "description_text": "", "deadline": "", "note": ""})
    active_id = store.create_application(active_job)
    assert store.confirm_application(active_id)
    store.insert_email_event({"dedup_key": "test:idempotent", "subject": "笔试", "snippet": "通知", "received_at": "2026-08-09T10:00:00", "category": "笔试", "confidence": 95, "company": "幂等公司", "title": "算法工程师"})
    store.resolve_email_event(2, "confirmed", active_id)
    try:
        store.resolve_email_event(2, "confirmed", active_id)
    except ValueError:
        pass
    else:
        raise AssertionError("one EmailEvent must create at most one application event")
    assert len(store.application_events(active_id)) == 2


def test_email_event_stores_parser_version_and_progress_renders_email_view(tmp_path):
    app = create_app(tmp_path / "email-view.db")
    store = app.state.store
    store.insert_email_event({"dedup_key": "test:parser-version", "subject": "示例笔试", "snippet": "笔试通知", "received_at": "2026-08-09T10:00:00", "category": "笔试", "summary": "笔试通知", "confidence": 45})
    assert store.email_event(1)["parser_version"] == PARSER_VERSION
    page = TestClient(app).get("/progress?view=email")
    assert page.status_code == 200
    assert "同步邮箱" in page.text and "email-pending-queue" not in page.text


def test_pending_email_can_be_reparsed_to_fill_key_time(tmp_path):
    app = create_app(tmp_path / "reparse-pending.db")
    app.state.store.save_ai_settings(False, email_enabled=True)
    app.state.store.insert_email_event({"dedup_key": "test:reparse-pending", "subject": "在线测评", "snippet": "请完成", "received_at": "2026-08-09T10:00:00", "category": "笔试", "summary": "测评", "confidence": 45})

    class Fake:
        def parse_email(self, _):
            from manual_capture.email_processing import EmailParse
            return EmailParse(category="笔试", summary="测评截止", confidence=80, action_deadline="2026-08-12T20:00")

    app.state.ai_client = Fake()
    response = TestClient(app).post("/api/pending-events/1/reparse", follow_redirects=True)
    assert response.status_code == 200
    assert app.state.store.email_event(1)["proposed_action_deadline_at"] == "2026-08-12T20:00"


def test_unanchored_relative_deadline_stays_manual_and_cannot_confirm(tmp_path):
    from manual_capture.email_processing import EmailProposal, EmailUnderstanding

    app = create_app(tmp_path / "relative-deadline.db")
    store = app.state.store
    store.insert_email_event({"dedup_key": "test:relative-deadline", "subject": "在线测评", "snippet": "收到本邮件后48小时内完成测评", "received_at": "2026-08-20T10:00:00"})
    understanding = EmailUnderstanding(proposals=[EmailProposal(
        kind="行动截止", category="笔试", summary="收到邮件后48小时内完成", confidence=80, evidence_ids=[1],
    )])
    store.update_email_understanding(1, understanding, ["收到本邮件后48小时内完成测评"])
    proposal = store.email_proposals(1)[0]
    assert proposal["kind"] == "提醒"
    assert proposal["action_deadline_at"] is None
    try:
        store.resolve_email_proposal(proposal["id"], 1)
    except ValueError as error:
        assert "人工核对" in str(error)
    else:
        raise AssertionError("relative deadline must not become confirmable")


def test_primary_pages_expose_ai_settings_navigation(tmp_path):
    client = TestClient(create_app(tmp_path / "nav.db"))
    for path in ("/", "/jobs", "/applications", "/progress", "/profile", "/import", "/progress?view=calendar"):
        assert "AI 设置" in client.get(path).text
