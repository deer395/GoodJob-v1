from manual_capture.email_processing import candidate_subject, dedup_key, email_excerpt, local_email_parse, redact
from manual_capture.imap_agent import local_api_url

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
