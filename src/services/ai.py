"""Điểm DUY NHẤT phần SW import hàm AI (docs/nm/04).

Khi bạn AI có bản thật: đổi dòng import dưới sang module thật, KHÔNG sửa nơi gọi.
Các hàm đều sync — gọi từ async bằng `asyncio.to_thread(...)`, bọc `asyncio.wait_for`.
"""

from src.services.ai_stub import draft_listing, moderate, search_semantic, suggest_price

__all__ = ["draft_listing", "moderate", "search_semantic", "suggest_price"]
