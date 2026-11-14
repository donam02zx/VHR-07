"""Gọi hàm AI an toàn (docs/nm/04 — "Xử lý lỗi từ hàm AI").

Hàm AI là sync → chạy trong thread, bọc `asyncio.wait_for` 20 giây. Lỗi, quá giờ, hoặc kết quả
sai dạng đều thành `AIUnavailableError` — nơi gọi quyết định hành vi, không ai "sửa khéo cho qua".
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("nm.safe_ai")

AI_TIMEOUT_S = 20.0


class AIUnavailableError(RuntimeError):
    """Hàm AI ném lỗi, quá giờ, hoặc trả sai hợp đồng."""


async def call_ai(fn: Callable[..., Any], *args: Any, timeout_s: float | None = None) -> Any:
    """Chạy hàm AI trong thread với timeout (mặc định AI_TIMEOUT_S, đọc lúc gọi)."""
    name = getattr(fn, "__name__", "ai")
    timeout_s = AI_TIMEOUT_S if timeout_s is None else timeout_s
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout=timeout_s)
    except TimeoutError:
        logger.error("AI %s quá %.0fs", name, timeout_s)
        raise AIUnavailableError(f"{name}: timeout") from None
    except Exception as exc:  # hàm AI của nhóm khác — lỗi gì cũng coi là sự cố AI
        logger.error("AI %s lỗi: %s", name, type(exc).__name__)
        raise AIUnavailableError(f"{name}: {type(exc).__name__}") from exc


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def check_draft(d: Any) -> dict[str, str]:
    keys = ("title", "description", "category", "condition")
    if not isinstance(d, dict) or not all(isinstance(d.get(k), str) for k in keys):
        raise AIUnavailableError("draft_listing: sai dạng")
    return {k: d[k] for k in keys}


def check_price(p: Any) -> dict[str, Any]:
    if not isinstance(p, dict) or not _is_int(p.get("low")) or not _is_int(p.get("high")):
        raise AIUnavailableError("suggest_price: sai dạng")
    if not 0 < p["low"] <= p["high"]:
        raise AIUnavailableError("suggest_price: khoảng giá vô lý")
    return {"low": p["low"], "high": p["high"], "rationale": str(p.get("rationale", ""))}


def check_moderation(m: Any) -> dict[str, Any]:
    if not isinstance(m, dict) or not isinstance(m.get("layers"), dict) or not isinstance(m.get("reason"), str):
        raise AIUnavailableError("moderate: sai dạng")
    score = m.get("score")
    if isinstance(score, bool) or not isinstance(score, int | float) or not 0.0 <= score <= 1.0:
        raise AIUnavailableError("moderate: score ngoài 0..1")
    return {"score": float(score), "layers": m["layers"], "reason": m["reason"]}
