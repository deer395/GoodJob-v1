"""Repeat the six P0 audit cases against the configured email model."""
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

CASES = (
    ("screen_pass", "中国电信简历筛选结果", "恭喜您通过云网运营岗简历筛选，请于2026年8月22日18:00前完成在线测评。", {("阶段推进", "笔试"), ("行动截止", "笔试")}),
    ("assessment", "字节跳动测评邀请", "产品运营在线测评入口已开放，请在2026-08-23 23:59前提交。", {("阶段推进", "笔试"), ("行动截止", "笔试")}),
    ("reschedule", "中国移动面试时间调整", "原定2026-08-21 10:00的面试调整至2026-08-30 15:00。", {("改期取消", "面试")}),
    ("thread_update", "京东面试安排更新", "最新通知：面试改为2026-09-01 11:00。历史邮件：2026-08-20 09:00。", {("改期取消", "面试")}),
    ("relative_48", "OPPO测评提醒", "请于收到本邮件后48小时内完成研发岗在线测评。", {("阶段推进", "笔试"), ("行动截止", "笔试")}),
    ("mixed", "海尔校招通知", "请于2026-08-26 18:00前完成测评。通过后，面试时间为2026-08-29 09:00。", {("阶段推进", "笔试"), ("行动截止", "笔试")}),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    client = OpenAIClient()
    report = []
    for case_id, subject, body, required in CASES:
        successes = dangerous = bad_deadline = failures = 0
        for _ in range(args.runs):
            evidence = email_evidence(body)
            payload = {"subject": subject, "sender_domain": "benchmark.example", "evidence": [{"id": i + 1, "text": text} for i, text in enumerate(evidence)]}
            try:
                actual = client.understand_email(payload)
            except AIUnavailable:
                failures += 1
                continue
            pairs = {(item.kind, item.category) for item in actual.proposals}
            successes += required.issubset(pairs)
            dangerous += any(item.kind == "阶段推进" and item.category == "面试" for item in actual.proposals if "通过后" in " ".join(evidence))
            bad_deadline += any(item.action_deadline for item in actual.proposals if case_id == "relative_48")
        report.append({"id": case_id, "runs": args.runs, "required_event_success_rate": successes / args.runs, "dangerous_event_runs": dangerous, "wrong_deadline_runs": bad_deadline, "provider_failures": failures, "candidate": candidate_email(subject, body)})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
