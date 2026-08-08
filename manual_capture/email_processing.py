from __future__ import annotations
import hashlib, re
from urllib.parse import urlsplit, urlunsplit
from pydantic import BaseModel, ConfigDict, Field

PARSER_VERSION = "email-v1"
CANDIDATE_WORDS = ("笔试", "面试", "测评", "offer", "拒信", "感谢投递", "面试邀请", "笔试通知", "在线测评", "录用通知", "遗憾", "下一步", "通知")
EXCLUDED_WORDS = ("宣讲", "竞赛", "内推", "推荐有礼")

def candidate_subject(subject: str) -> bool:
    text = subject.lower()
    return any(word.lower() in text for word in CANDIDATE_WORDS) and not any(word in text for word in EXCLUDED_WORDS)

def redact(value: str) -> str:
    value = re.sub(r"[\w.+-]+@[\w.-]+", "[邮箱]", value)
    value = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[手机号]", value)
    value = re.sub(r"\b\d{17}[\dXx]\b", "[身份证]", value)
    def safe_url(match):
        parts = urlsplit(match.group(0)); return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return re.sub(r"https?://[^\s<]+", safe_url, value)[:200]

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
    scheduled_date: str = Field(default="", max_length=25)
    summary: str = Field(default="", max_length=30)
    confidence: int = Field(ge=0, le=100)


def local_email_parse(subject: str, snippet: str) -> EmailParse | None:
    """Conservative no-network fallback; it never infers a company, job, or schedule."""
    text = f"{subject}\n{snippet}".lower()
    categories = (
        (("测评", "笔试", "在线考试"), "笔试", "检测到测评或笔试通知"),
        (("面试", "面谈", "interview"), "面试", "检测到面试通知"),
        (("offer", "录用"), "Offer", "检测到录用通知"),
        (("感谢您的申请", "不予录用", "遗憾"), "拒信", "检测到申请结果通知"),
    )
    for words, category, summary in categories:
        if any(word in text for word in words):
            return EmailParse(category=category, summary=summary, confidence=45)
    return None
