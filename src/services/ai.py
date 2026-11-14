"""Điểm DUY NHẤT phần SW gọi hàm AI (docs/nm/04).

Chọn bản cài đặt theo `NM_AI_MODE` trong .env: "stub" (bản giả xác định, mặc định) hoặc "gemini".
Nơi gọi không đổi. Các hàm đều sync — gọi từ async qua `safe_ai.call_ai` (thread + timeout).
"""

from __future__ import annotations

from types import ModuleType

from src.config import get_settings
from src.services import ai_stub


def _impl() -> ModuleType:
    if get_settings().nm_ai_mode == "gemini":
        from src.services import ai_gemini  # import muộn: chế độ stub không cần thư viện/khóa Gemini

        return ai_gemini
    return ai_stub


def draft_listing(image: bytes | None, caption: str) -> dict:
    return _impl().draft_listing(image, caption)


def suggest_price(listing: dict) -> dict:
    return _impl().suggest_price(listing)


def moderate(listing: dict) -> dict:
    return _impl().moderate(listing)


def search_semantic(query: str, k: int = 5) -> list[int]:
    return _impl().search_semantic(query, k)


def mode() -> str:
    return get_settings().nm_ai_mode


__all__ = ["draft_listing", "moderate", "search_semantic", "suggest_price", "mode"]
