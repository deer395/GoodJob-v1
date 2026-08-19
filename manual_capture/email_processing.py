from __future__ import annotations
import hashlib, re
from datetime import date, datetime
from urllib.parse import urlsplit, urlunsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator

PARSER_VERSION = "email-v3"
CANDIDATE_WORDS = ("笔试", "面试", "测评", "offer", "拒信", "感谢投递", "面试邀请", "笔试通知", "在线测评", "录用通知", "遗憾", "下一步", "通知")
EXCLUDED_WORDS = ("宣讲", "竞赛", "内推", "推荐有礼")
BODY_CANDIDATE_WORDS = CANDIDATE_WORDS + ("简历筛选", "材料", "改期", "取消", "回复", "申请进度")

# A calendar date can stand on its own, while phrases such as “明晚” and
# “收到邮件后 48 小时” need a trustworthy message-time anchor.  The current
# email-understanding payload deliberately does not contain such an anchor, so
# these expressions must remain manual rather than becoming guessed ISO times.
RELATIVE_TIME_RE = re.compile(
    r"(?:收到(?:本)?(?:邮件|通知)?后\s*(?:\d+|[一二三四五六七八九十]+)\s*(?:个)?(?:小时|天|日)(?:内|后)?|"
    r"(?:明天|明晚|后天|今晚|今天|本周[一二三四五六日天]|下周[一二三四五六日天]|(?:\d+|[一二三四五六七八九十]+)\s*天后))"
)
EXPLICIT_CALENDAR_DATE_RE = re.compile(
    r"(?:20\d{2}\s*(?:年|[-/])\s*\d{1,2}\s*(?:月|[-/])\s*\d{1,2}\s*日?|\d{1,2}\s*月\s*\d{1,2}\s*日?)"
)

def candidate_subject(subject: str) -> bool:
    text = subject.lower()
    return any(word.lower() in text for word in CANDIDATE_WORDS) and not any(word in text for word in EXCLUDED_WORDS)


def candidate_email(subject: str, body: str) -> bool:
    """Local recall gate.  It never persists the body and excludes obvious campaigns."""
    joined = f"{subject}\n{body}".lower()
    return any(word.lower() in joined for word in BODY_CANDIDATE_WORDS) and not (
        any(word in subject.lower() for word in EXCLUDED_WORDS) and not any(word.lower() in body.lower() for word in ("面试", "笔试", "测评", "offer"))
    )

def _redact(value: str) -> str:
    value = re.sub(r"[\w.+-]+@[\w.-]+", "[邮箱]", value)
    value = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[手机号]", value)
    value = re.sub(r"\b\d{17}[\dXx]\b", "[身份证]", value)
    def safe_url(match):
        parts = urlsplit(match.group(0)); return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return re.sub(r"https?://[^\s<]+", safe_url, value)


def redact(value: str) -> str:
    return _redact(value)[:200]


def email_excerpt(value: str) -> str:
    """Keep a short, redacted excerpt but retain sentences most likely to contain a key time."""
    chunks = [chunk.strip() for chunk in re.split(r"[\r\n。！？;；]+", value) if chunk.strip()]
    keywords = ("截止", "完成", "前", "测评", "笔试", "面试", "回复", "offer", "材料", "时间")
    selected = [chunk for chunk in chunks if any(word.lower() in chunk.lower() for word in keywords)]
    if chunks:
        selected.insert(0, chunks[0])
    return _redact("。".join(dict.fromkeys(selected)))[:200]


def email_evidence(value: str, limit: int = 8) -> list[str]:
    """Return short, locally-redacted evidence sentences for optional AI parsing."""
    chunks = [chunk.strip() for chunk in re.split(r"[\r\n。！？;；]+", value) if chunk.strip()]
    # Long recruiting notices often put a numbered heading on one line and
    # its value on the next. Keep that pair together: otherwise an
    # evidence-only model sees “面试时间” but never receives the date.
    heading = re.compile(r"^(?:[一二三四五六七八九十]+[、.．])?\s*(?:面试时间|面试地点|应聘岗位|现场签到|请携带以下材料|材料要求)\s*[:：]?$")
    units: list[str] = []
    index = 0
    while index < len(chunks):
        if heading.match(chunks[index]) and index + 1 < len(chunks):
            if "材料" in chunks[index]:
                # Semicolon-separated material lists are split above. Keep a
                # bounded run together until a new numbered section or a
                # separate reply/deadline instruction begins.
                values = [chunks[index]]
                next_index = index + 1
                while next_index < len(chunks) and len(values) < 7:
                    candidate = chunks[next_index]
                    if heading.match(candidate) or candidate.startswith("请于") or candidate.startswith("如有"):
                        break
                    values.append(candidate)
                    next_index += 1
                units.append("：".join((values[0], "；".join(values[1:]))))
                index = next_index
            else:
                units.append(f"{chunks[index]}：{chunks[index + 1]}")
                index += 2
        else:
            units.append(chunks[index])
            index += 1
    keywords = ("截止", "完成", "测评", "笔试", "面试", "offer", "录用", "遗憾", "取消", "改期", "材料", "回复", "筛选", "岗位", "地点", "签到")
    relevant = [chunk for chunk in units if any(word.lower() in chunk.lower() for word in keywords)]
    company_context = [chunk for chunk in units[:3] if any(word in chunk for word in ("公司", "集团", "研究院", "招聘"))]
    selected = list(dict.fromkeys(company_context + relevant))[:limit] or units[:limit]
    return [_redact(chunk)[:220] for chunk in selected if _redact(chunk).strip()]


def explicit_key_times(value: str) -> tuple[str, str]:
    """Extract only explicit ISO-like key times; relative and yearless phrases remain manual."""
    scheduled = action_deadline = ""
    for match in re.finditer(r"\b(20\d{2})[/-](\d{1,2})[/-](\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?", value):
        year, month, day, hour, minute = match.groups()
        normalized = f"{year}-{int(month):02d}-{int(day):02d}" + (f"T{int(hour):02d}:{minute}" if hour else "")
        try:
            (datetime.fromisoformat(normalized) if hour else date.fromisoformat(normalized))
        except ValueError:
            continue
        context = value[max(0, match.start() - 24):match.end() + 24].lower()
        if any(word in context for word in ("截止", "完成", "回复", "提交", "前")) and not action_deadline:
            action_deadline = normalized
        elif any(word in context for word in ("面试", "笔试", "测评", "开始", "安排")) and not scheduled:
            scheduled = normalized
    return scheduled, action_deadline

def dedup_key(mailbox: str, uidvalidity: str | None, uid: str | None, message_id: str | None, subject: str, sender: str, received_at: str) -> tuple[str, str]:
    if uid: return (f"uid:{mailbox}:{uidvalidity or 'unknown'}:{uid}", "uid")
    if message_id: return (f"mid:{message_id.strip().lower()}", "message_id")
    digest = hashlib.sha256(f"{subject.strip().lower()}|{sender.strip().lower()}|{received_at}".encode()).hexdigest()
    return (f"hash:{digest}", "hash")

class EmailParse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str = Field(pattern="^(面试|笔试|Offer|拒信|群发广告|其他)$")
    company: str = Field(default="", max_length=120)
    title: str = Field(default="", max_length=160)
    city: str = Field(default="", max_length=120)
    scheduled_date: str = Field(default="", max_length=25)
    action_deadline: str = Field(default="", max_length=25)
    summary: str = Field(default="", max_length=30)
    confidence: int = Field(ge=0, le=100)

    @field_validator("scheduled_date", "action_deadline")
    @classmethod
    def key_time_must_be_iso(cls, value: str) -> str:
        if not value:
            return ""
        try:
            return datetime.fromisoformat(value).isoformat(timespec="minutes")
        except ValueError:
            try:
                return date.fromisoformat(value).isoformat()
            except ValueError as exc:
                raise ValueError("key time must use ISO date or datetime") from exc


def local_email_parse(subject: str, snippet: str) -> EmailParse | None:
    """Conservative no-network fallback; it never infers a company, job, or key time."""
    text = f"{subject}\n{snippet}".lower()
    source_text = f"{subject}\n{snippet}"
    scheduled, action_deadline = explicit_key_times(source_text)
    company_match = re.match(r"\s*([^\s【】·—-]{2,40}?)(?:\s*20\d{2}|\s*(?:校园招聘|校招|招聘|在线测评|笔试|面试))", subject)
    title_match = re.search(r"(?:岗位|职位)\s*[：:]\s*([^，。；\n]{2,80})", source_text)
    city_match = re.search(r"(?:工作地(?:点)?|地点)\s*[：:]\s*([^，。；\n]{1,60})", source_text)
    company = company_match.group(1).strip() if company_match else ""
    title = title_match.group(1).strip() if title_match else ""
    city = city_match.group(1).strip() if city_match else ""
    categories = (
        (("测评", "笔试", "在线考试"), "笔试", "检测到测评或笔试通知"),
        (("面试", "面谈", "interview"), "面试", "检测到面试通知"),
        (("offer", "录用"), "Offer", "检测到录用通知"),
        (("感谢您的申请", "不予录用", "遗憾"), "拒信", "检测到申请结果通知"),
    )
    for words, category, summary in categories:
        if any(word in text for word in words):
            return EmailParse(category=category, company=company, title=title, city=city, summary=summary, confidence=45, scheduled_date=scheduled, action_deadline=action_deadline)
    return None


class EmailProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern="^(阶段推进|行动截止|补充材料|提醒|改期取消|其他)$")
    category: str = Field(pattern="^(面试|笔试|Offer|拒信|群发广告|其他)$")
    summary: str = Field(default="", max_length=60)
    suggested_action: str = Field(default="", max_length=120)
    location: str = Field(default="", max_length=180)
    scheduled_date: str = Field(default="", max_length=25)
    action_deadline: str = Field(default="", max_length=25)
    confidence: int = Field(ge=0, le=100)
    evidence_ids: list[int] = Field(default_factory=list, max_length=4)

    @field_validator("scheduled_date", "action_deadline")
    @classmethod
    def proposal_time_must_be_iso(cls, value: str) -> str:
        return EmailParse.key_time_must_be_iso(value)


class EmailUnderstanding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company: str = Field(default="", max_length=120)
    title: str = Field(default="", max_length=160)
    city: str = Field(default="", max_length=120)
    proposals: list[EmailProposal] = Field(default_factory=list, max_length=3)


def remove_unanchored_relative_times(understanding: EmailUnderstanding, evidence: list[str]) -> EmailUnderstanding:
    """Clear LLM-inferred times when cited evidence only gives a relative phrase.

    This function intentionally does not calculate against ``received_at``:
    email understanding currently receives only redacted evidence and has no
    explicit timezone contract.  The proposal, summary and evidence remain so
    the user can still review the relative instruction manually.
    """
    safe_proposals: list[EmailProposal] = []
    for proposal in understanding.proposals:
        cited = "\n".join(
            evidence[index - 1]
            for index in proposal.evidence_ids
            if isinstance(index, int) and 1 <= index <= len(evidence)
        )
        if RELATIVE_TIME_RE.search(cited) and not EXPLICIT_CALENDAR_DATE_RE.search(cited):
            proposal = proposal.model_copy(update={"scheduled_date": "", "action_deadline": ""})
        safe_proposals.append(proposal)
    return understanding.model_copy(update={"proposals": safe_proposals})
