import json
from pathlib import Path

from manual_capture.email_processing import EmailProposal, candidate_email, email_evidence, redact


CORPUS = Path(__file__).resolve().parents[2] / "evaluation" / "phase3b_email_understanding" / "email_cases.json"


def test_phase3b_synthetic_corpus_local_gate_and_redaction():
    cases = json.loads(CORPUS.read_text(encoding="utf-8"))["cases"]
    assert len(cases) >= 12
    for case in cases:
        assert candidate_email(case["subject"], case["body"]) is case["candidate"], case["id"]
        for evidence in email_evidence(case["body"]):
            assert len(evidence) <= 220
            assert "13812345678" not in evidence
            assert "?token=" not in evidence
    assert "[手机号]" in redact("联系电话 13812345678")


def test_phase3b_synthetic_corpus_gold_proposals_fit_the_strict_schema():
    cases = json.loads(CORPUS.read_text(encoding="utf-8"))["cases"]
    for case in cases:
        for expected in case["expected"].get("proposals", []):
            proposal = EmailProposal.model_validate({"summary": "评测标准答案", "suggested_action": "人工确认", "confidence": 80, "evidence_ids": [1], **expected})
            assert proposal.kind
            assert proposal.category
