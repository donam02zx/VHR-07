"""Kiểm duyệt hai tầng (docs/nm/07): luật cứng của SW, rồi điểm AI; định tuyến theo ngưỡng trong Settings.

Vì sao luật cứng chạy trước: hàng cấm bị từ chối kể cả khi AI sập/sai, và không tốn lượt gọi AI.
AI lỗi/timeout/sai dạng → `in_review` với reason `ai_unavailable` — không bao giờ tự đăng (04).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal

from src.config import get_settings
from src.services import ai, db
from src.services.pii import contains_phone
from src.services.safe_ai import AIUnavailableError, call_ai, check_moderation
from src.services.text import normalize_text

logger = logging.getLogger("nm.moderation")

Decision = Literal["publish", "review", "reject"]

# ---- Luật cứng (sửa ở đây) ----
PROHIBITED_KEYWORDS = (
    "thuốc lá điện tử",
    "vape",
    "vũ khí",
    "súng",
    "đạn",
    "pháo",
    "ma tuý",
    "cần sa",
    "thuốc kê đơn",
)
_LINK = re.compile(
    r"(?:https?://|www\.)\S+|\b[\w-]+\.(?:com|net|org|vn|xyz|info|top|io|me|ly|link|site|online|shop)\b",
    re.IGNORECASE,
)
PRICE_MAX_VND = 1_000_000_000
FLAG_MIN_SCORE = 0.3  # SĐT/link/giá lạ: không từ chối, nhưng ít nhất phải qua người duyệt
REASON_AI_UNAVAILABLE = "ai_unavailable"


@dataclass(frozen=True)
class ModerationResult:
    decision: Decision
    reason: str = ""
    score: float | None = None


@dataclass
class RuleResult:
    prohibited: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        if self.prohibited:
            return 1.0
        return FLAG_MIN_SCORE if self.flags else 0.0


def route(score: float, publish_below: float | None = None, reject_from: float | None = None) -> Decision:
    """Điểm → hành động. Ngưỡng mặc định lấy từ Settings (MOD_PUBLISH_BELOW / MOD_REJECT_FROM)."""
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"score ngoài 0..1: {score}")
    s = get_settings()
    publish_below = s.mod_publish_below if publish_below is None else publish_below
    reject_from = s.mod_reject_from if reject_from is None else reject_from
    if score >= reject_from:
        return "reject"
    if score < publish_below:
        return "publish"
    return "review"


def check_rules(listing: dict[str, Any]) -> RuleResult:
    """Luật cứng trên title + description + giá. Hàm thuần."""
    text = f"{listing.get('title') or ''} {listing.get('description') or ''}"
    lowered = unicodedata.normalize("NFC", text).lower()
    norm = normalize_text(text)
    result = RuleResult()
    for kw in PROHIBITED_KEYWORDS:
        # Từ đơn so khớp CÓ dấu: bỏ dấu thì "súng"→"sung", "pháo"→"phao" (phao bơi) bắt nhầm.
        # Cụm nhiều từ đủ đặc trưng để so cả dạng không dấu ("thuoc la dien tu").
        hit = re.search(rf"\b{re.escape(kw)}\b", lowered) or (
            " " in kw and re.search(rf"\b{re.escape(normalize_text(kw))}\b", norm)
        )
        if hit:
            result.prohibited.append(kw)
    if contains_phone(text):
        result.flags.append("lộ SĐT trong tin")
    if _LINK.search(text):
        result.flags.append("có đường link")
    price = listing.get("price_vnd")
    if price is None or price <= 0 or price > PRICE_MAX_VND:
        result.flags.append("giá bất thường")
    return result


def _move(listing_id: int, to_status: str) -> None:
    if not db.set_status(listing_id, "pending_moderation", to_status):
        raise RuntimeError(f"listing {listing_id} rời pending_moderation giữa chừng")


def _send_to_review(listing_id: int, score: float, reason: str) -> None:
    _move(listing_id, "in_review")
    db.create_review(listing_id, reason, score)


async def process(listing_id: int) -> ModerationResult:
    """Kiểm duyệt tin đang `pending_moderation`, chuyển trạng thái, ghi audit, trả quyết định."""
    listing = db.get_listing(listing_id)
    if listing is None or listing["status"] != "pending_moderation":
        raise RuntimeError(f"listing {listing_id} không ở pending_moderation")

    rules = check_rules(listing)
    if rules.prohibited:
        reason = "mặt hàng không được phép (" + ", ".join(rules.prohibited) + ")"
        db.update_listing_fields(listing_id, moderation_score=1.0, moderation_reason=reason)
        _move(listing_id, "rejected")
        db.add_audit(listing_id, "moderation_reject", f"rule: {reason}")
        return ModerationResult("reject", reason, 1.0)

    ai_input = {k: listing[k] for k in ("title", "description", "category", "condition", "price_vnd")}
    try:
        verdict = check_moderation(await call_ai(ai.moderate, ai_input))
    except AIUnavailableError as exc:
        logger.error("moderate lỗi listing=%s: %s", listing_id, exc)
        db.update_listing_fields(listing_id, moderation_reason=REASON_AI_UNAVAILABLE)
        _send_to_review(listing_id, rules.score, REASON_AI_UNAVAILABLE)
        db.add_audit(listing_id, "moderation_review", f"{REASON_AI_UNAVAILABLE}: {exc}")
        return ModerationResult("review", REASON_AI_UNAVAILABLE, None)

    score = max(rules.score, verdict["score"])
    reason = "; ".join([*rules.flags, verdict["reason"]])
    decision = route(score)
    db.update_listing_fields(listing_id, moderation_score=score, moderation_reason=reason)
    if decision == "publish":
        _move(listing_id, "published")
    elif decision == "review":
        _send_to_review(listing_id, score, reason)
    else:
        _move(listing_id, "rejected")
    db.add_audit(listing_id, f"moderation_{decision}", f"score={score:.2f} rule={rules.score:.2f} ai={verdict['score']:.2f}")
    return ModerationResult(decision, verdict["reason"] if decision == "reject" else reason, score)
