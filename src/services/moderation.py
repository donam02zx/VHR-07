"""Kiểm duyệt (docs/nm/07). TẠM cho T06: luôn đăng. T07 thay bằng luật + định tuyến theo điểm."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from src.services import db

logger = logging.getLogger("nm.moderation")

Decision = Literal["publish", "review", "reject"]


@dataclass(frozen=True)
class ModerationResult:
    decision: Decision
    reason: str = ""


async def process(listing_id: int) -> ModerationResult:
    """Nhận tin ở `pending_moderation`, chuyển trạng thái và trả quyết định.

    Bản tạm: chuyển thẳng `published`. Không khớp trạng thái → lỗi tường minh.
    """
    if not db.set_status(listing_id, "pending_moderation", "published"):
        raise RuntimeError(f"listing {listing_id} không ở pending_moderation")
    db.add_audit(listing_id, "moderation_publish", "stub T06")
    return ModerationResult("publish")
