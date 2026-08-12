from manual_capture.matching import baseline_with_semantic_adjustment, bounded_semantic_adjustment, evaluate
from fastapi.testclient import TestClient
from manual_capture.app import create_app


def profile():
    return {"target_cities": "北京", "target_directions": "数据分析,产品经理", "skills": "python,用户研究", "degree": "本科", "graduation_year": "2026"}


def job(**extra):
    return {"company": "示例公司", "title": "商业分析", "city": "北京", "department": "增长", "note": "用户洞察", "description_text": "", "deadline": "", **extra}


def signal(relation="same_track", confidence=90, **extra):
    return {"role_family": "product", "relation_to_target_track": relation, "confidence": confidence, **extra}


def test_python_adds_only_bounded_adjustment_to_baseline():
    baseline, _ = evaluate(job(), profile())
    final, details = baseline_with_semantic_adjustment(job(), profile(), signal())
    assert details["baseline_score"] == baseline
    assert details["semantic_adjustment"] == 6
    assert final == baseline + 6


def test_provider_failure_keeps_baseline_exactly_unchanged():
    baseline, _ = evaluate(job(), profile())
    final, details = baseline_with_semantic_adjustment(job(), profile(), None)
    assert final == baseline and details["semantic_adjustment"] == 0


def test_explicit_hard_conflict_cannot_be_overridden_by_semantic_signal():
    final, details = baseline_with_semantic_adjustment(job(title="数据分析 2025届"), profile(), signal())
    assert final is None and details["semantic_adjustment"] == 0


def test_clear_single_role_technical_job_cannot_receive_positive_lift():
    adjustment, details = bounded_semantic_adjustment(job(title="NLP 算法工程师"), profile(), signal("same_track"))
    assert adjustment == 0 and details["guardrail"] is True


def test_multi_role_entry_with_product_is_not_misclassified_as_pure_technical():
    adjustment, details = bounded_semantic_adjustment(job(title="算法、数据、产品、运营"), profile(), signal("close_track"))
    assert adjustment == 3 and details["guardrail"] is False


def test_low_confidence_limits_a_strong_adjustment():
    adjustment, _ = bounded_semantic_adjustment(job(), profile(), signal("same_track", confidence=40))
    assert adjustment == 3


def test_pool_has_no_semantic_screening_refresh_entry(tmp_path):
    app = create_app(tmp_path / "baseline-only.db")
    app.state.store.save_profile({**profile(), "school": "", "major": "", "target_industries": "", "constraints": ""})
    job_id = app.state.store.create({**job(), "application_url": "", "salary_range": "", "source": "其他"})
    client = TestClient(app)
    assert "更新语义初筛" not in client.get("/jobs").text
    assert client.post(f"/jobs/{job_id}/ai-screen").status_code == 404
