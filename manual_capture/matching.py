"""Deterministic, local-only matching rules for the radar."""
from __future__ import annotations

import json
import re

DELIMITERS = re.compile(r"[,，、/;；|&+\s]+")
DEGREE_RANK = {"大专": 1, "本科": 2, "硕士": 3, "博士": 4}


def parts(value: str | None) -> list[str]:
    return [item.strip().lower() for item in DELIMITERS.split(value or "") if item.strip()]


def canonical_tags(value: str | None) -> str:
    """Normalize tag input for storage without inventing or changing its meaning."""
    return ",".join(dict.fromkeys(parts(value)))


def char_ngrams(value: str, n: int = 2) -> set[str]:
    compact = re.sub(r"\s+", "", value.lower())
    if len(compact) < n:
        return {compact} if compact else set()
    return {compact[index:index + n] for index in range(len(compact) - n + 1)}


def ngram_overlap(tag: str, text: str) -> float:
    """Directional char 2-gram coverage: tag grams explained by the job text."""
    tag_grams = char_ngrams(tag)
    if not tag_grams:
        return 0.0
    return len(tag_grams & char_ngrams(text)) / len(tag_grams)


def calc_tag_score(tag: str, job_text: str) -> tuple[int, float]:
    ratio = ngram_overlap(tag, job_text)
    if ratio >= .8: return 25, ratio
    if ratio >= .6: return 20, ratio
    if ratio >= .4: return 15, ratio
    return 0, ratio


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
    for label, values in (("方向", parts(profile.get("target_directions"))), ("技能", parts(profile.get("skills")))):
        scored = [(tag, *calc_tag_score(tag, text)) for tag in values]
        hit = next(((tag, points, ratio) for tag, points, ratio in scored if points), None)
        if hit:
            tag, points, ratio = hit
            score += points; reasons.append(f"{label}匹配：{tag}（重叠率 {ratio:.0%} → +{points}）")
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
