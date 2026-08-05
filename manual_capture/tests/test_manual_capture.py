from datetime import date, timedelta

from fastapi.testclient import TestClient

from manual_capture.app import create_app


def client(tmp_path):
    return TestClient(create_app(tmp_path / "jobs.db"))


def payload(**overrides):
    data = {"company": "字节跳动", "title": "产品经理", "city": "北京", "source": "其他"}
    data.update(overrides)
    return data


def test_saves_job_and_persists_to_sqlite(tmp_path):
    app = create_app(tmp_path / "jobs.db")
    response = TestClient(app).post("/jobs", data=payload(), follow_redirects=True)
    assert response.status_code == 200
    assert "已收录：" in response.text
    assert app.state.store.list()[0]["status"] == "待评估"


def test_required_fields_are_validated(tmp_path):
    response = client(tmp_path).post("/jobs", data=payload(company="", city=""))
    assert "请填写公司名" in response.text
    assert "请填写工作地点" in response.text


def test_duplicate_is_blocked_and_can_be_updated(tmp_path):
    test_client = client(tmp_path)
    test_client.post("/jobs", data=payload())
    response = test_client.post("/jobs", data=payload(note="重复提交"))
    assert "该岗位已收录" in response.text
    assert "更新原记录" in response.text
    assert len(test_client.app.state.store.list()) == 1


def test_near_and_expired_deadlines_are_shown(tmp_path):
    test_client = client(tmp_path)
    near = (date.today() + timedelta(days=2)).isoformat()
    past = (date.today() - timedelta(days=1)).isoformat()
    assert "临近截止" in test_client.post("/jobs", data=payload(deadline=near), follow_redirects=True).text
    assert "已逾期" in test_client.post("/jobs", data=payload(company="腾讯", deadline=past), follow_redirects=True).text


def test_pool_search_filters_and_sorts_by_deadline(tmp_path):
    test_client = client(tmp_path)
    near = (date.today() + timedelta(days=1)).isoformat()
    later = (date.today() + timedelta(days=10)).isoformat()
    past = (date.today() - timedelta(days=1)).isoformat()
    test_client.post("/jobs", data=payload(company="腾讯", title="后端开发", deadline=later))
    test_client.post("/jobs", data=payload(company="字节跳动", title="产品经理", deadline=near))
    test_client.post("/jobs", data=payload(company="阿里巴巴", title="算法工程师", deadline=past))

    pool = test_client.get("/jobs")
    assert pool.text.index("字节跳动") < pool.text.index("腾讯")
    assert "阿里巴巴" in test_client.get("/jobs?state=expired").text
    assert "腾讯" not in test_client.get("/jobs?state=near").text
    assert "产品经理" in test_client.get("/jobs?q=字节").text
    assert "腾讯" not in test_client.get("/jobs?q=字节").text


def test_note_limit_and_delete_from_edit_page(tmp_path):
    test_client = client(tmp_path)
    too_long = test_client.post("/jobs", data=payload(note="x" * 501))
    assert "备注最多 500 字" in too_long.text

    test_client.post("/jobs", data=payload())
    job_id = test_client.app.state.store.list()[0]["id"]
    deleted = test_client.post(f"/jobs/{job_id}/delete", follow_redirects=True)
    assert "岗位记录已删除" in deleted.text
    assert test_client.app.state.store.list() == []


def test_pool_shows_external_link_only_when_a_job_has_one(tmp_path):
    test_client = client(tmp_path)
    test_client.post("/jobs", data=payload(application_url="https://jobs.example.com/byte"))
    pool = test_client.get("/jobs")
    assert 'href="https://jobs.example.com/byte"' in pool.text
    assert 'target="_blank"' in pool.text


def test_profile_recomputes_explainable_match_and_persists(tmp_path):
    test_client = client(tmp_path)
    test_client.post("/jobs", data=payload(title="后端开发 2027届 硕士", city="北京", department="云产品", note="Python"))
    test_client.post("/profile", data={"graduation_year": "2027", "degree": "硕士", "target_cities": "北京,上海", "target_directions": "后端开发", "skills": "Python"})
    job = test_client.app.state.store.list()[0]
    assert job["match_score"] == 100
    assert "城市匹配" in job["match_reasons"]


def test_graduation_mismatch_is_not_scored_or_high_match(tmp_path):
    test_client = client(tmp_path)
    test_client.post("/jobs", data=payload(title="后端开发 2026届", note="Python"))
    test_client.post("/profile", data={"graduation_year": "2027", "target_cities": "北京", "target_directions": "后端开发", "skills": "Python"})
    job = test_client.app.state.store.list()[0]
    assert job["match_score"] is None
    assert "届别不匹配" in job["match_reasons"]
    assert "字节跳动" not in test_client.get("/jobs?state=high").text


def test_favorite_and_radar_search_include_department(tmp_path):
    test_client = client(tmp_path)
    test_client.post("/jobs", data=payload(department="增长业务"))
    job_id = test_client.app.state.store.list()[0]["id"]
    test_client.post(f"/jobs/{job_id}/favorite")
    assert "字节跳动" in test_client.get("/jobs?state=favorite").text
    assert "字节跳动" in test_client.get("/jobs?q=增长").text
