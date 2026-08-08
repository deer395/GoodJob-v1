from manual_capture.email_processing import candidate_subject, dedup_key, local_email_parse, redact
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


def test_agent_api_url_uses_configurable_port(monkeypatch):
    monkeypatch.delenv('FASTAPI_PORT', raising=False)
    assert local_api_url().endswith(':8000/api/email-events')
    monkeypatch.setenv('FASTAPI_PORT', '8010')
    assert local_api_url().endswith(':8010/api/email-events')
