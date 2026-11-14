"""API duyệt tay (docs/nm/07). Bảo vệ bằng header `X-Console-Token` (demo, không đăng nhập thật).

Quyết định ghi DB trước (nguồn sự thật), rồi mới nhắn người bán; nhắn lỗi chỉ log, không huỷ quyết định.
"""

from __future__ import annotations

import hmac
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from src.channels.zalo import ZaloClient
from src.config import get_settings
from src.services import db, posting
from src.services.posting import Reply

logger = logging.getLogger("nm.reviews")

router = APIRouter(tags=["reviews"])

_DECISION_MAP = {"approve": "approved", "reject": "rejected", "needs_fix": "needs_fix"}
REVIEWER = "console"


class DecideRequest(BaseModel):
    decision: Literal["approve", "reject", "needs_fix"]
    note: str = Field(default="", max_length=500)


class DecideResponse(BaseModel):
    review_id: int
    listing_id: int
    listing_status: str
    notified: bool


def require_console_token(x_console_token: str | None = Header(default=None)) -> None:
    expected = get_settings().console_token
    if not expected:
        raise HTTPException(503, "CONSOLE_TOKEN chưa cấu hình")
    if not x_console_token or not hmac.compare_digest(x_console_token, expected):
        raise HTTPException(401, "Sai X-Console-Token")


def get_channel(request: Request) -> ZaloClient:
    """Kênh dùng chung do `lifespan` tạo (app.state.channel). Test override dependency này."""
    channel = getattr(request.app.state, "channel", None)
    if channel is None:
        raise HTTPException(503, "Kênh nhắn tin chưa khởi động")
    return channel


@router.get("/reviews", dependencies=[Depends(require_console_token)])
async def list_reviews(status: Literal["pending", "approved", "rejected", "needs_fix"] = "pending") -> list[dict]:
    keys = ("id", "listing_id", "title", "description", "price_vnd", "image_ref", "score", "reason", "created_at")
    return [{k: r[k] for k in keys} for r in db.list_reviews(status)]


@router.post("/reviews/{review_id}/decide", dependencies=[Depends(require_console_token)])
async def decide(review_id: int, body: DecideRequest, channel: ZaloClient = Depends(get_channel)) -> DecideResponse:
    review = db.get_review(review_id)
    if review is None:
        raise HTTPException(404, "Không có mục duyệt này")
    try:
        final_status = db.decide_review(review_id, _DECISION_MAP[body.decision], REVIEWER, body.note or None)
    except db.ReviewAlreadyDecidedError:
        raise HTTPException(409, "Mục này đã được quyết") from None
    except db.InvalidTransitionError as exc:
        logger.warning("decide review=%s: %s", review_id, exc)
        raise HTTPException(409, "Tin không còn ở trạng thái chờ duyệt") from None

    listing_id = review["listing_id"]
    replies = _after_decision(listing_id, final_status, body.note, review.get("reason") or "")
    notified = await _send_all(channel, replies, review_id)
    current = db.get_listing(listing_id)["status"]  # needs_fix đã được mở lại → awaiting_confirm
    return DecideResponse(review_id=review_id, listing_id=listing_id, listing_status=current, notified=notified)


def _seller_chat_id(listing: dict[str, Any]) -> str:
    """Chat 1:1: chat.id == from.id (05, ĐÃ KIỂM CHỨNG) → nhắn theo zalo_user_id."""
    seller = db.get_user(listing["seller_id"])
    if seller is None:
        raise RuntimeError(f"listing {listing['id']} không có người bán")
    return seller["zalo_user_id"]


def _after_decision(listing_id: int, final_status: str, note: str, review_reason: str) -> list[Reply]:
    listing = db.get_listing(listing_id)
    chat_id = _seller_chat_id(listing)
    lid = listing["id"]
    if final_status == "published":
        return posting.publish_replies(listing, chat_id)
    if final_status == "rejected":
        why = note or "nội dung chưa phù hợp quy định của nhóm"
        return [Reply(chat_id, f"Tin #{lid} không được đăng: {why}.")]
    # needs_fix: mở lại bản nháp để người bán "sửa ..." rồi "ok" (07). Bản nháp khác đang dở bị huỷ.
    posting.reopen_for_fix(chat_id, lid)
    head = f"Tin #{lid} cần sửa trước khi đăng: {note or review_reason or 'người duyệt yêu cầu chỉnh sửa'}."
    return [Reply(chat_id, head + "\n\n" + posting.draft_text(db.get_listing(lid)))]


async def _send_all(channel: ZaloClient, replies: list[Reply], review_id: int) -> bool:
    ok = True
    for reply in replies:
        try:
            await channel.send_text(reply.chat_id, reply.text)
        except Exception as exc:
            ok = False
            logger.error("nhắn sau duyệt lỗi review=%s chat=%s: %s", review_id, reply.chat_id, type(exc).__name__)
    return ok
