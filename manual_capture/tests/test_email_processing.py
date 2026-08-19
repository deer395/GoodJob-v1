import pytest
import json
from pathlib import Path

from manual_capture.ai import OpenAIClient
from manual_capture.email_processing import (
    EmailProposal,
    EmailUnderstanding,
    candidate_email,
    candidate_subject,
    dedup_key,
    email_evidence,
    email_excerpt,
    local_email_parse,
    redact,
    remove_unanchored_relative_times,
    stabilize_exam_workflow_proposals,
)
from manual_capture.imap_agent import local_api_url

GATE_CORPUS = Path(__file__).resolve().parents[2] / "evaluation" / "phase3b_email_understanding" / "candidate_gate_cases.json"

def test_local_filter_redaction_and_dedup():
    assert candidate_subject('【笔试通知】产品经理')
    assert not candidate_subject('宣讲会与内推推荐有礼')
    hidden=redact('a@b.com 13800138000 11010519491231002X https://x.com/a?token=secret')
    assert 'a@b.com' not in hidden and '13800138000' not in hidden and 'secret' not in hidden
    assert dedup_key('INBOX','7','8',None,'s','f','d')[0] == 'uid:INBOX:7:8'
    assert dedup_key('INBOX',None,None,'<m>','s','f','d')[0] == 'mid:<m>'


def test_local_fallback_only_classifies_explicit_mail_terms():
    result = local_email_parse('在线测评邀请', '请在 72 小时内完成测评')
    assert result and result.category == '笔试' and result.confidence == 45
    assert local_email_parse('企业宣讲会通知', '欢迎参加') is None


def test_local_fallback_keeps_explicit_action_deadline_and_redacted_key_time_excerpt():
    parsed = local_email_parse('星河科技 2027 校招在线测评邀请', '请于 2026-08-12 20:00 前完成在线测评。岗位：数据产品经理，工作地：上海。')
    assert parsed and parsed.action_deadline == '2026-08-12T20:00'
    assert parsed.company == '星河科技' and parsed.title == '数据产品经理' and parsed.city == '上海'
    excerpt = email_excerpt('普通开头。请于 2026-08-12 20:00 前完成测评，联系 a@example.com。')
    assert '2026-08-12 20:00' in excerpt and 'a@example.com' not in excerpt


def test_agent_api_url_uses_configurable_port(monkeypatch):
    monkeypatch.delenv('FASTAPI_PORT', raising=False)
    assert local_api_url().endswith(':8000/api/email-events')
    monkeypatch.setenv('FASTAPI_PORT', '8010')
    assert local_api_url().endswith(':8010/api/email-events')


def test_body_signal_can_enter_candidate_queue_and_evidence_stays_redacted():
    body = '您好，您已通过简历筛选。请于 2026-08-20 14:00 参加线上面试。联系 a@example.com，链接 https://x.example/a?token=secret'
    assert candidate_email('关于您的申请', body)
    evidence = email_evidence(body)
    assert evidence and all('a@example.com' not in item and 'secret' not in item for item in evidence)


def test_email_evidence_keeps_numbered_notice_heading_with_its_value():
    body = '中国船舶集团有限公司系统工程研究院2027年度校园招聘。\n经审核通知参加综合面试。\n一、面试时间\n2026年8月22日上午09:00\n二、面试地点\n北京市海淀区示例路1号\n三、应聘岗位\n系统工程/数据分析方向\n五、请携带以下材料\n身份证原件；学生证；个人简历3份；成绩单\n请于2026年8月19日17:00前回复确认参加。'
    evidence = email_evidence(body)
    assert any('面试时间：2026年8月22日上午09:00' in item for item in evidence)
    assert any('面试地点：北京市海淀区示例路1号' in item for item in evidence)
    assert any('应聘岗位：系统工程/数据分析方向' in item for item in evidence)
    assert any('身份证原件；学生证；个人简历3份；成绩单' in item for item in evidence)
    assert any('中国船舶集团' in item for item in evidence)


@pytest.mark.parametrize("text", [
    "请于收到本邮件后 48 小时内完成在线测评。",
    "请于收到通知后三日内完成材料提交。",
    "请在明晚 24:00 前完成笔试。",
    "请于本周五前回复是否参加。",
])
def test_relative_time_without_anchor_never_keeps_llm_iso_time(text):
    understanding = EmailUnderstanding(proposals=[EmailProposal(
        kind="行动截止", category="笔试", summary="请按要求完成", confidence=80,
        action_deadline="2026-08-24T18:00", evidence_ids=[1],
    )])
    filtered = remove_unanchored_relative_times(understanding, [text])
    assert filtered.proposals[0].action_deadline == ""
    assert filtered.proposals[0].scheduled_date == ""
    assert filtered.proposals[0].evidence_ids == [1]


@pytest.mark.parametrize("text, expected", [
    ("请于 8 月 24 日 18:00 前完成测评。", "2026-08-24T18:00"),
    ("请于 2026-08-24 18:00 前完成测评。", "2026-08-24T18:00"),
])
def test_explicit_calendar_deadline_is_preserved(text, expected):
    understanding = EmailUnderstanding(proposals=[EmailProposal(
        kind="行动截止", category="笔试", summary="测评截止", confidence=80,
        action_deadline=expected, evidence_ids=[1],
    )])
    filtered = remove_unanchored_relative_times(understanding, [text])
    assert filtered.proposals[0].action_deadline == expected


def test_relative_phrase_does_not_remove_explicit_start_and_deadline():
    evidence = ["笔试于 2026-08-23 09:00 开始；请于 2026-08-24 18:00 前完成，收到邮件后请尽快安排。"]
    understanding = EmailUnderstanding(proposals=[EmailProposal(
        kind="阶段推进", category="笔试", summary="笔试安排", confidence=80,
        scheduled_date="2026-08-23T09:00", action_deadline="2026-08-24T18:00", evidence_ids=[1],
    )])
    filtered = remove_unanchored_relative_times(understanding, evidence)
    assert filtered.proposals[0].scheduled_date == "2026-08-23T09:00"
    assert filtered.proposals[0].action_deadline == "2026-08-24T18:00"


def test_understand_email_applies_relative_time_guard(monkeypatch):
    client = OpenAIClient()
    monkeypatch.setattr(client, "_call", lambda *_: {"company": "星河科技", "title": "产品经理", "city": "", "proposals": [{
        "kind": "行动截止", "category": "笔试", "summary": "完成测评", "suggested_action": "完成测评",
        "location": "", "scheduled_date": "", "action_deadline": "2026-08-24T18:00", "confidence": 85, "evidence_ids": [1],
    }]})
    result = client.understand_email({"subject": "在线测评", "sender_domain": "campus.example", "evidence": [{"id": 1, "text": "收到本邮件后48小时内完成测评"}]})
    assert result.proposals[0].action_deadline == ""
    assert result.proposals[0].evidence_ids == [1]


@pytest.mark.parametrize("text, deadline", [
    ("产品运营在线测评入口已开放，请在2026-08-23 23:59前提交。", "2026-08-23T23:59"),
    ("请于收到本邮件后48小时内完成研发岗在线测评。", ""),
    ("请在明晚24:00前完成在线笔试。", ""),
])
def test_exam_action_always_keeps_a_separate_exam_stage(text, deadline):
    understanding = EmailUnderstanding(proposals=[EmailProposal(
        kind="行动截止", category="笔试", summary="完成测评", confidence=85,
        action_deadline=deadline, evidence_ids=[1],
    )])
    result = stabilize_exam_workflow_proposals(understanding, [text])
    assert [(item.kind, item.category) for item in result.proposals] == [("阶段推进", "笔试"), ("行动截止", "笔试")]
    assert result.proposals[0].evidence_ids == [1]


def test_conditional_future_interview_is_only_a_manual_reminder():
    understanding = EmailUnderstanding(proposals=[EmailProposal(
        kind="阶段推进", category="面试", summary="后续面试", confidence=80,
        scheduled_date="2026-08-28T10:00", evidence_ids=[1],
    )])
    result = stabilize_exam_workflow_proposals(understanding, ["通过后拟于2026-08-28 10:00安排面试。"])
    assert result.proposals[0].kind == "提醒"
    assert result.proposals[0].scheduled_date == ""


@pytest.mark.parametrize("case_id, text, proposals, expected", [
    ("screen_pass", "恭喜通过初筛，请于2026-08-22 18:00前完成在线测评。", [
        EmailProposal(kind="阶段推进", category="笔试", summary="通过初筛", confidence=90, evidence_ids=[1]),
        EmailProposal(kind="行动截止", category="笔试", summary="测评截止", action_deadline="2026-08-22T18:00", confidence=90, evidence_ids=[1]),
    ], [("阶段推进", "笔试"), ("行动截止", "笔试")]),
    ("assessment", "产品运营在线测评入口已开放，请在2026-08-23 23:59前提交。", [
        EmailProposal(kind="行动截止", category="笔试", summary="测评截止", action_deadline="2026-08-23T23:59", confidence=90, evidence_ids=[1]),
    ], [("阶段推进", "笔试"), ("行动截止", "笔试")]),
    ("multiple_dates", "测评请在2026-08-25 20:00前完成；通过后拟于2026-08-28 10:00安排面试。", [
        EmailProposal(kind="行动截止", category="笔试", summary="测评截止", action_deadline="2026-08-25T20:00", confidence=90, evidence_ids=[1]),
        EmailProposal(kind="阶段推进", category="面试", summary="后续面试", scheduled_date="2026-08-28T10:00", confidence=80, evidence_ids=[2]),
    ], [("阶段推进", "笔试"), ("行动截止", "笔试"), ("提醒", "面试")]),
    ("mixed", "请于2026-08-26 18:00前完成测评。通过后，面试时间为2026-08-29 09:00。", [
        EmailProposal(kind="行动截止", category="笔试", summary="测评截止", action_deadline="2026-08-26T18:00", confidence=90, evidence_ids=[1]),
        EmailProposal(kind="阶段推进", category="面试", summary="后续面试", scheduled_date="2026-08-29T09:00", confidence=80, evidence_ids=[2]),
    ], [("阶段推进", "笔试"), ("行动截止", "笔试"), ("提醒", "面试")]),
])
def test_p0_realistic_regression_decomposes_exam_without_confirming_conditional_interview(case_id, text, proposals, expected):
    evidence = text.split("；") if "；" in text else text.split("。")
    evidence = [item for item in evidence if item]
    result = stabilize_exam_workflow_proposals(EmailUnderstanding(proposals=proposals), evidence)
    assert [(item.kind, item.category) for item in result.proposals] == expected, case_id


def test_candidate_gate_recalls_applicant_workflow_and_rejects_marketing_controls():
    cases = json.loads(GATE_CORPUS.read_text(encoding="utf-8"))["cases"]
    positives = [case for case in cases if case["candidate"]]
    negatives = [case for case in cases if not case["candidate"]]
    missed = [case["id"] for case in positives if not candidate_email(case["subject"], case["body"])]
    false_positives = [case["id"] for case in negatives if candidate_email(case["subject"], case["body"])]
    assert len(positives) >= 12 and len(negatives) >= 7
    assert missed == []
    assert false_positives == []
