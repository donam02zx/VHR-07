"""API duyệt tay (docs/nm/07). Bảo vệ bằng header `X-Console-Token` (demo, không đăng nhập thật).

Quyết định ghi DB trước (nguồn sự thật), rồi mới nhắn người bán; nhắn lỗi chỉ log, không huỷ quyết định.
"""

from __future__ import annotations

import hmac
import logging
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from src.channels.zalo import ZaloClient
from src.config import get_settings
from src.services import db, reviewflow
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
    try:
        listing_id, status, replies = reviewflow.decide(review_id, _DECISION_MAP[body.decision], REVIEWER, body.note)
    except LookupError:
        raise HTTPException(404, "Không có mục duyệt này") from None
    except db.ReviewAlreadyDecidedError:
        raise HTTPException(409, "Mục này đã được quyết") from None
    except db.InvalidTransitionError as exc:
        logger.warning("decide review=%s: %s", review_id, exc)
        raise HTTPException(409, "Tin không còn ở trạng thái chờ duyệt") from None
    notified = await _send_all(channel, replies, review_id)
    return DecideResponse(review_id=review_id, listing_id=listing_id, listing_status=status, notified=notified)


async def _send_all(channel: ZaloClient, replies: list[Reply], review_id: int) -> bool:
    ok = True
    for reply in replies:
        try:
            await channel.send_text(reply.chat_id, reply.text)
        except Exception as exc:
            ok = False
            logger.error("nhắn sau duyệt lỗi review=%s chat=%s: %s", review_id, reply.chat_id, type(exc).__name__)
    return ok
