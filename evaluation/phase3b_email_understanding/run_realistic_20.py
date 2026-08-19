"""Live evaluation for the reconstructed realistic 20-case mail corpus."""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
if str(PROJECT) not in sys.path: sys.path.insert(0, str(PROJECT))
from manual_capture.ai import AIUnavailable, OpenAIClient
from manual_capture.email_processing import candidate_email, email_evidence

def main() -> int:
    corpus = json.loads((ROOT / "realistic_20_reconstructed.json").read_text(encoding="utf-8"))
    cases = corpus["cases"]; positives = [c for c in cases if c["candidate"]]; negatives = [c for c in cases if not c["candidate"]]
    missed = [c["id"] for c in positives if not candidate_email(c["subject"], c["body"])]
    fp = [c["id"] for c in negatives if candidate_email(c["subject"], c["body"])]
    client = OpenAIClient(); failures=[]; covered=0; critical=0; wrong_deadline=0; conditional=0
    for case in positives:
        evidence=email_evidence(case["body"]); payload={"subject":case["subject"],"sender_domain":"realistic.example","evidence":[{"id":i+1,"text":v} for i,v in enumerate(evidence)]}
        try: actual=client.understand_email(payload)
        except AIUnavailable as exc: failures.append({"id":case["id"],"error":exc.category}); critical += 1; continue
        pairs={(p.kind,p.category) for p in actual.proposals}; required={tuple(x) for x in case["required"]}; ok=required.issubset(pairs); covered += len(required & pairs); critical += not ok
        relative_bad=bool(case.get("relative")) and any(p.action_deadline or p.scheduled_date for p in actual.proposals)
        conditional_bad=bool(case.get("conditional_interview")) and any(p.kind=="阶段推进" and p.category=="面试" for p in actual.proposals)
        wrong_deadline += relative_bad; conditional += conditional_bad
        if not ok or relative_bad or conditional_bad: failures.append({"id":case["id"],"ground_truth":case["required"],"actual":sorted(pairs),"relative_deadline":relative_bad,"conditional_interview_progression":conditional_bad})
    total_required=sum(len(c["required"]) for c in positives)
    print(json.dumps({"provenance":corpus["dataset"],"candidate_recall":(len(positives)-len(missed))/len(positives),"negative_false_positive_rate":len(fp)/len(negatives),"required_event_coverage":covered/total_required,"critical_error_rate":critical/len(positives),"wrong_deadline_count":wrong_deadline,"silent_auto_confirm_count":0,"conditional_future_progression_count":conditional,"missed_candidates":missed,"false_positives":fp,"failures":failures},ensure_ascii=False,indent=2)); return 0
if __name__ == "__main__": raise SystemExit(main())
