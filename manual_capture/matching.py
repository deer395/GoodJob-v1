"""Deterministic, local-only matching rules for the radar."""
from __future__ import annotations

import json
import re

DELIMITERS = re.compile(r"[,，、/;；]+")
DEGREE_RANK = {"大专": 1, "本科": 2, "硕士": 3, "博士": 4}


def parts(value: str | None) -> list[str]:
    return [item.strip().lower() for item in DELIMITERS.split(value or "") if item.strip()]


def configured(profile: dict | None) -> bool:
    return bool(profile and (parts(profile.get("target_cities")) or parts(profile.get("target_directions")) or parts(profile.get("skills"))))


def evaluate(job: dict, profile: dict | None) -> tuple[int | None, str | None]:
    if not configured(profile):
        return None, None
    profile = profile or {}
    text = " ".join(str(job.get(key) or "") for key in ("title", "department", "note")).lower()
    city = str(job.get("city") or "").strip().lower()
    reasons: list[str] = []
    years = re.findall(r"20\d{2}\s*届", text)
    graduation_year = (profile.get("graduation_year") or "").strip()
    if years and graduation_year and not any(graduation_year in item for item in years):
        required = years[0].replace(" ", "")
        return None, json.dumps([f"届别不匹配：岗位要求 {required}，当前画像为 {graduation_year} 届"], ensure_ascii=False)
    score = 0
    if city in {"全国", "多地", "远程"}:
        reasons.append("工作地点需人工确认")
    elif any(item in city for item in parts(profile.get("target_cities"))):
        score += 30; reasons.append(f"城市匹配：{job.get('city')}（+30）")
    for label, values, points in (("方向", parts(profile.get("target_directions")), 25), ("技能", parts(profile.get("skills")), 25)):
        hit = next((item for item in values if item in text), None)
        if hit:
            score += points; reasons.append(f"{label}匹配：{hit}（+{points}）")
    requirement = next((degree for degree in DEGREE_RANK if degree in text), None)
    current = (profile.get("degree") or "").strip()
    if requirement:
        if DEGREE_RANK.get(current, 0) >= DEGREE_RANK[requirement]:
            score += 20; reasons.append(f"学历要求：{requirement}，当前学历：{current}（+20）")
        else:
            reasons.append("学历要求可能不匹配")
    else:
        reasons.append("未提供学历要求")
    reasons.append(f"总分：{score}")
    return score, json.dumps(reasons, ensure_ascii=False)
