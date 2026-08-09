from datetime import date, timedelta
import subprocess

from fastapi.testclient import TestClient

from manual_capture.app import create_app


def job(company: str, *, deadline: str = "", title: str = "产品经理", city: str = "北京") -> dict[str, str]:
    return {"company": company, "title": title, "city": city, "source": "其他", "deadline": deadline}


def test_radar_shortcuts_are_exclusive_and_search_is_combined(tmp_path):
    client = TestClient(create_app(tmp_path / "radar.db"))
    today = date.today().isoformat()
    near = (date.today() + timedelta(days=2)).isoformat()
    client.post("/jobs", data=job("今日临期岗位", deadline=near))
    client.post("/jobs", data=job("普通岗位", deadline=(date.today() + timedelta(days=15)).isoformat()))

    page = client.get("/jobs?state=near&q=今日&sort=priority")
    assert "当前筛选" in page.text and "今日临期岗位" in page.text
    assert "普通岗位" not in page.text
    assert "一键清除筛选" in page.text
    assert "高匹配筛选在画像未配置时不可用" in client.get("/jobs?state=high").text
    assert today in client.get("/jobs?state=today").text or "今日新增" in client.get("/jobs?state=today").text


def test_email_sync_records_safe_aggregate_diagnostics_and_releases_lock(tmp_path, monkeypatch):
    import manual_capture.app as app_module

    app = create_app(tmp_path / "sync.db")
    client = TestClient(app)
    monkeypatch.setattr(
        app_module.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, 'candidate emails: 3\nsync-diagnostics: {"candidate_count": 3, "created_count": 1, "deduplicated_count": 2}\n', ""),
    )
    response = client.post("/api/email-sync", follow_redirects=True)
    assert response.status_code == 200
    diagnostic = app.state.store.latest_email_sync_diagnostic()
    assert dict(diagnostic)["candidate_count"] == 3
    assert dict(diagnostic)["created_count"] == 1
    assert dict(diagnostic)["deduplicated_count"] == 2
    assert dict(diagnostic)["scan_mailbox"] == "INBOX" and dict(diagnostic)["scan_days"] == 7 and dict(diagnostic)["scan_limit"] == 50
    assert "message_id" not in dict(diagnostic) and "@" not in repr(dict(diagnostic))
    assert not app.state.email_sync_lock.locked()


def test_email_sync_failure_is_safe_and_help_page_never_echoes_values(tmp_path, monkeypatch):
    import manual_capture.app as app_module

    monkeypatch.setenv("IMAP_SERVER", "private-host.example")
    monkeypatch.setenv("IMAP_EMAIL", "private@example.com")
    app = create_app(tmp_path / "sync-fail.db")
    monkeypatch.setattr(app_module.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 2, "", "secret-token private@example.com"))
    page = TestClient(app).post("/api/email-sync", follow_redirects=True)
    assert "检查本地配置" in page.text
    assert "private@example.com" not in page.text and "secret-token" not in page.text
    help_page = TestClient(app).get("/email-sync-help")
    assert "已检测到" in help_page.text
    assert "private-host.example" not in help_page.text and "private@example.com" not in help_page.text
    assert "manual_capture\\imap_agent.py --once" in help_page.text
    assert "重试同步邮箱" in help_page.text


def test_email_sync_missing_structured_counts_never_displays_zero(tmp_path, monkeypatch):
    import manual_capture.app as app_module

    app = create_app(tmp_path / "sync-no-counts.db")
    monkeypatch.setattr(
        app_module.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "candidate emails: 99\n", ""),
    )
    page = TestClient(app).post("/api/email-sync", follow_redirects=True)
    diagnostic = dict(app.state.store.latest_email_sync_diagnostic())
    assert "计数不可用" in page.text
    assert diagnostic["outcome"] == "failed"
    assert diagnostic["candidate_count"] is None and diagnostic["created_count"] is None and diagnostic["deduplicated_count"] is None
    assert "99 封候选邮件" not in page.text


def test_email_sync_oserror_records_safe_failure_and_releases_lock(tmp_path, monkeypatch):
    import manual_capture.app as app_module

    app = create_app(tmp_path / "sync-oserror.db")
    monkeypatch.setattr(app_module.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("unavailable executable")))
    page = TestClient(app).post("/api/email-sync", follow_redirects=True)
    diagnostic = dict(app.state.store.latest_email_sync_diagnostic())
    assert page.status_code == 200 and "同步未启动" in page.text and "检查本地配置" in page.text
    assert diagnostic["outcome"] == "failed" and diagnostic["diagnostic_category"] == "agent_unavailable"
    assert not app.state.email_sync_lock.locked()
