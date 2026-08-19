"""Optional live evaluation for the synthetic Phase 3B email corpus."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from manual_capture.ai import AIUnavailable, OpenAIClient
from manual_capture.email_processing import candidate_email, email_evidence

ROOT = Path(__file__).resolve().parent
GATE_CORPUS = ROOT / "candidate_gate_cases.json"


def required_pairs(case: dict) -> set[tuple[str, str]]:
    return {(item["kind"], item["category"]) for item in case["expected"].get("proposals", [])}


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the synthetic Phase 3B email corpus.")
    parser.add_argument("--live", action="store_true", help="Call the configured AI provider; without this, only validate corpus coverage.")
    args = parser.parse_args()
    corpus = json.loads((ROOT / "email_cases.json").read_text(encoding="utf-8"))
    cases = corpus["cases"]
    local = [{"id": c["id"], "expected_candidate": c["candidate"], "actual_candidate": candidate_email(c["subject"], c["body"]), "evidence_count": len(email_evidence(c["body"]))} for c in cases]
    report: dict = {"dataset": corpus["dataset"], "total_cases": len(cases), "local_gate_passed": sum(item["expected_candidate"] == item["actual_candidate"] for item in local), "local_gate": local}
    gate_cases = json.loads(GATE_CORPUS.read_text(encoding="utf-8"))["cases"]
    positives = [case for case in gate_cases if case["candidate"]]
    negatives = [case for case in gate_cases if not case["candidate"]]
    missed = [case["id"] for case in positives if not candidate_email(case["subject"], case["body"])]
    false_positives = [case["id"] for case in negatives if candidate_email(case["subject"], case["body"])]
    report["candidate_gate"] = {
        "dataset": "phase3b-candidate-gate-v1",
        "positive_total": len(positives),
        "positive_recall": (len(positives) - len(missed)) / len(positives) if positives else 1,
        "missed_ids": missed,
        "negative_total": len(negatives),
        "negative_false_positive_rate": len(false_positives) / len(negatives) if negatives else 0,
        "false_positive_ids": false_positives,
    }
    if not args.live:
        report["note"] = "No provider call was made. Run with --live only after confirming the configured AI provider and its cost."
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    client = OpenAIClient()
    outcomes = []
    for case in cases:
        if not case["candidate"]:
            continue
        evidence = email_evidence(case["body"])
        payload = {"subject": case["subject"], "sender_domain": case["sender_domain"], "evidence": [{"id": index + 1, "text": text} for index, text in enumerate(evidence)]}
        try:
            actual = client.understand_email(payload)
            actual_pairs = {(item.kind, item.category) for item in actual.proposals}
            expected_pairs = required_pairs(case)
            expected_times = {key: value for item in case["expected"].get("proposals", []) for key, value in item.items() if key in {"scheduled_date", "action_deadline"}}
            actual_times = {key: value for item in actual.proposals for key, value in (("scheduled_date", item.scheduled_date), ("action_deadline", item.action_deadline)) if value}
            outcomes.append({"id": case["id"], "status": "ok", "expected_pairs": sorted(expected_pairs), "actual_pairs": sorted(actual_pairs), "pair_match": expected_pairs.issubset(actual_pairs), "expected_times": expected_times, "actual_times": actual_times, "time_match": all(actual_times.get(key) == value for key, value in expected_times.items()), "all_evidence_ids_valid": all(item.evidence_ids and all(1 <= i <= len(evidence) for i in item.evidence_ids) for item in actual.proposals)})
        except AIUnavailable as exc:
            outcomes.append({"id": case["id"], "status": "provider_failure", "reason": exc.category})
    successful = [item for item in outcomes if item["status"] == "ok"]
    report["live"] = {"attempted": len(outcomes), "successful": len(successful), "proposal_pair_matches": sum(item["pair_match"] for item in successful), "time_matches": sum(item["time_match"] for item in successful), "valid_evidence_citations": sum(item["all_evidence_ids_valid"] for item in successful), "cases": outcomes}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
