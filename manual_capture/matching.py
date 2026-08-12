"""Deterministic, local-only matching rules for the radar."""
from __future__ import annotations

import json
import re
from datetime import date

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


RELATIONSHIP_POINTS = {
    "highly_related": 52,
    "related": 40,
    "adjacent": 28,
    "weakly_related": 14,
    "unrelated": 3,
    "uncertain": 10,
}


def _contains_any(values: list[str], text: str) -> bool:
    return any(value and value in text for value in values)


def aggregate_screening(job: dict, profile: dict | None, semantic: dict | None = None) -> tuple[int | None, dict]:
    """Return an explainable 0--100 screening relevance, never a suitability probability.

    The function is deliberately usable with ``semantic=None``.  In that case the
    old n-gram signal remains a cheap deterministic fallback rather than a claim
    that the job has been semantically understood.
    """
    if not configured(profile):
        return None, {"mode": "not_configured", "components": {}, "reasons": []}
    profile = profile or {}
    text = " ".join(str(job.get(key) or "") for key in ("title", "department", "note", "description_text")).lower()
    city = str(job.get("city") or "").strip().lower()
    components: dict[str, int] = {}
    reasons: list[str] = []
    graduation_year = str(profile.get("graduation_year") or "").strip()
    years = re.findall(r"20\d{2}\s*届", text)
    if years and graduation_year and not any(graduation_year in item for item in years):
        return 0, {"mode": "hard_block", "components": {"hard_rule": 0}, "reasons": [f"届别不匹配：岗位写明 {years[0].replace(' ', '')}，画像为 {graduation_year}届"]}

    if city in {"全国", "多地", "远程", ""}:
        components["city"] = 6
        reasons.append("地点未限定或需人工确认")
    elif _contains_any(parts(profile.get("target_cities")), city):
        components["city"] = 16
        reasons.append(f"城市匹配：{job.get('city')}")
    else:
        components["city"] = -8
        reasons.append(f"城市不在目标城市中：{job.get('city')}")

    requirement = next((degree for degree in DEGREE_RANK if degree in text), None)
    degree = str(profile.get("degree") or "").strip()
    if requirement and degree and DEGREE_RANK.get(degree, 0) < DEGREE_RANK[requirement]:
        return 0, {"mode": "hard_block", "components": {"hard_rule": 0}, "reasons": [f"明确学历冲突：岗位要求至少{requirement}，画像为{degree}"]}
    components["hard_rule"] = 10 if requirement and degree else 5

    if semantic:
        relationship = str(semantic.get("relationship") or "uncertain")
        directions = {str(item).strip().lower() for item in semantic.get("directions", []) if str(item).strip()}
        technical_only = bool(directions) and directions <= {"algorithm", "engineering", "算法", "研发", "工程"}
        target_text = " ".join(parts(profile.get("target_directions")))
        if technical_only and not any(token in target_text for token in ("算法", "开发", "工程")):
            # Product/data-analysis targets can be adjacent to engineering, but
            # a pure technical role must not become "related" merely because it
            # uses data or AI terminology.
            relationship = {"highly_related": "related", "related": "adjacent"}.get(relationship, relationship)
        components["direction"] = RELATIONSHIP_POINTS.get(relationship, RELATIONSHIP_POINTS["uncertain"])
        closest = semantic.get("closest_target")
        label = {"highly_related": "方向高度相关", "related": "方向相关", "adjacent": "方向相邻", "weakly_related": "方向弱相关", "unrelated": "方向不相关", "uncertain": "方向关系尚不确定"}.get(relationship, "方向关系尚不确定")
        reasons.append(f"{label}{('：' + str(closest)) if closest else ''}")
        clues = " ".join(str(item).lower() for item in semantic.get("capability_clues", []))
        skill_hits = [skill for skill in parts(profile.get("skills")) if skill and skill in clues]
        components["skills"] = min(16, 8 * len(skill_hits))
        if skill_hits:
            reasons.append("岗位文本明确出现的相关线索：" + "、".join(skill_hits[:2]))
        mode = "semantic"
    else:
        direction_scores = [calc_tag_score(tag, text) for tag in parts(profile.get("target_directions"))]
        skill_scores = [calc_tag_score(tag, text) for tag in parts(profile.get("skills"))]
        fallback_direction = max((points for points, _ in direction_scores), default=0)
        components["direction"] = min(32, fallback_direction + 7) if fallback_direction else 0
        components["skills"] = min(12, max((points for points, _ in skill_scores), default=0) // 2)
        reasons.append("AI 语义初筛暂不可用，当前使用关键词重叠作为初始信号")
        mode = "ngram_fallback"

    if job.get("deadline"):
        try:
            components["deadline"] = -12 if date.fromisoformat(str(job["deadline"])) < date.today() else 0
            if components["deadline"]: reasons.append("投递截止日期已过")
        except ValueError:
            components["deadline"] = 0
    else:
        components["deadline"] = 0
    score = max(0, min(100, sum(components.values())))
    return score, {"mode": mode, "components": components, "reasons": reasons, "semantic": semantic or {}}


# Frozen for the next independent evaluation.  The LLM may only nudge the
# proven baseline; it can never replace it with a second scoring system.
SEMANTIC_ADJUSTMENTS = {
    "same_track": 6,
    "close_track": 3,
    "transferable_but_not_target": -3,
    "unrelated": -6,
    "uncertain": 0,
}


def is_clear_single_role_technical(job: dict, profile: dict | None) -> bool:
    """Only guard unambiguous technical roles, never mixed recruiting entries."""
    title = str(job.get("title") or "").casefold()
    if any(separator in title for separator in (",", "，", "、", "/", ";", "；")):
        return False
    target_text = " ".join(parts((profile or {}).get("target_directions")))
    target_terms = parts((profile or {}).get("target_directions")) + ["产品", "数据"]
    if any(term and term in title for term in target_terms):
        return False
    technical_terms = ["\u7b97\u6cd5\u5de5\u7a0b\u5e08", "\u540e\u7aef", "java", "\u524d\u7aef", "\u5ba2\u6237\u7aef", "\u5d4c\u5165\u5f0f", "ic", "\u82af\u7247", "\u786c\u4ef6", "\u8f6f\u4ef6\u5f00\u53d1", "\u7814\u53d1\u5de5\u7a0b\u5e08"]
    return bool(target_text and any(term in title for term in technical_terms))


def bounded_semantic_adjustment(job: dict, profile: dict | None, semantic: dict | None) -> tuple[int, dict]:
    """Return the limited career-track correction and a fully explainable trace."""
    if not semantic:
        return 0, {"relation": "unavailable", "confidence": None, "guardrail": False, "reason": "语义服务不可用，保留 baseline"}
    relation = str(semantic.get("relation_to_target_track") or "uncertain")
    confidence = int(semantic.get("confidence") or 0)
    adjustment = SEMANTIC_ADJUSTMENTS.get(relation, 0)
    # Low-confidence answers never produce a strong correction.
    if confidence < 60 and adjustment:
        adjustment = 3 if adjustment > 0 else -3
    guardrail = is_clear_single_role_technical(job, profile)
    if guardrail and adjustment > 0:
        adjustment = 0
    return adjustment, {
        "relation": relation,
        "confidence": confidence,
        "guardrail": guardrail,
        "role_family": semantic.get("role_family", ""),
        "closest_target": semantic.get("closest_target"),
        "reason": semantic.get("reason", ""),
    }


def baseline_with_semantic_adjustment(job: dict, profile: dict | None, semantic: dict | None = None) -> tuple[int | None, dict]:
    baseline, baseline_reasons = evaluate(job, profile)
    if baseline is None:
        return None, {"baseline_score": None, "semantic_adjustment": 0, "final_score": None, "baseline_reasons": json.loads(baseline_reasons or "[]"), "semantic": {}}
    adjustment, semantic_details = bounded_semantic_adjustment(job, profile, semantic)
    final_score = max(0, min(100, baseline + adjustment))
    return final_score, {
        "baseline_score": baseline,
        "semantic_adjustment": adjustment,
        "final_score": final_score,
        "baseline_reasons": json.loads(baseline_reasons or "[]"),
        "semantic": semantic_details,
    }
