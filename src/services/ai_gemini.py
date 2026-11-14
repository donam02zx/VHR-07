"""4 hàm AI thật bằng Gemini — đúng chữ ký hợp đồng docs/nm/04 (sync, trả dict).

Lỗi/timeout/sai dạng KHÔNG xử lý ở đây: ném ra để `safe_ai` + nơi gọi quyết định (04: AI lỗi → in_review).
Prompt ở `prompts/nm_*.md`. Dùng structured output (Pydantic) để hạn chế sai dạng.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from src.agents.prompts import load_prompt
from src.services import ai_stub, db
from src.services.nm_llm import get_nm_llm

logger = logging.getLogger("nm.ai_gemini")

CATEGORIES = ("Thể thao", "Điện tử", "Gia dụng", "Nội thất", "Thời trang", "Đồ trẻ em", "Sách", "Khác")
SEARCH_CANDIDATES = 100


class DraftOut(BaseModel):
    title: str = Field(description="Tiêu đề ngắn ≤ 60 ký tự")
    description: str = Field(description="1–3 câu mô tả")
    category: str = Field(description="Một trong danh mục cho trước")
    condition: str = Field(description="Tình trạng ngắn, vd 'Cũ 80%'")


class PriceOut(BaseModel):
    low: int = Field(gt=0, description="Giá thấp (VND)")
    high: int = Field(gt=0, description="Giá cao (VND)")
    rationale: str


class ModerationOut(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    reason: str


class SearchOut(BaseModel):
    ids: list[int] = Field(description="id tin liên quan, liên quan nhất trước")


def _render(name: str, **values: Any) -> str:
    text = load_prompt(name)
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def _image_part(image: bytes) -> dict[str, Any]:
    if image.startswith(b"\x89PNG"):
        mime = "image/png"
    elif image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        mime = "image/jpeg"
    return {"type": "image_url", "image_url": f"data:{mime};base64,{base64.b64encode(image).decode()}"}


def _structured(schema: type[BaseModel], content: str | list[dict[str, Any]], fast: bool = False) -> BaseModel:
    """Gọi Gemini với structured output. Điểm duy nhất chạm mạng — test thay hàm này."""
    llm = get_nm_llm(fast=fast).with_structured_output(schema)
    result = llm.invoke([HumanMessage(content=content)])
    if not isinstance(result, schema):
        raise ValueError(f"Gemini trả sai dạng cho {schema.__name__}")
    return result


def draft_listing(image: bytes | None, caption: str) -> dict:
    prompt = _render("nm_draft_listing.md", categories=", ".join(CATEGORIES), caption=caption.strip() or "(trống)")
    content: str | list[dict[str, Any]] = prompt
    if image:
        content = [{"type": "text", "text": prompt}, _image_part(image)]
    out = _structured(DraftOut, content)
    category = out.category if out.category in CATEGORIES else "Khác"
    return {
        "title": out.title.strip()[:60] or "Món đồ cần bán",
        "description": out.description.strip(),
        "category": category,
        "condition": out.condition.strip() or "Đã qua sử dụng",
    }


def suggest_price(listing: dict) -> dict:
    prompt = _render(
        "nm_suggest_price.md",
        title=listing.get("title") or "",
        description=listing.get("description") or "",
        category=listing.get("category") or "Khác",
        condition=listing.get("condition") or "",
    )
    out = _structured(PriceOut, prompt)
    low, high = sorted((out.low, out.high))
    return {"low": low, "high": high, "rationale": out.rationale.strip()}


def moderate(listing: dict) -> dict:
    """Điểm = max(luật từ khoá lừa đảo, điểm mô hình). Luật hàng cấm đã chạy ở services/moderation (SW)."""
    text = " ".join(str(listing.get(k) or "") for k in ("caption", "title", "description"))
    rule = ai_stub.SCORE_SCAM if ai_stub._matches(text, ai_stub.SCAM_KEYWORDS) else 0.0
    price = listing.get("price_vnd")
    prompt = _render(
        "nm_moderate.md",
        title=listing.get("title") or "",
        description=listing.get("description") or "",
        category=listing.get("category") or "",
        price=f"{price:,} đ".replace(",", ".") if isinstance(price, int) else "chưa có",
    )
    out = _structured(ModerationOut, prompt, fast=True)
    score = max(rule, out.score)
    reason = out.reason.strip()
    if rule > out.score:
        reason = "Có dấu hiệu đòi chuyển khoản/đặt cọc trước. " + reason
    return {"score": score, "layers": {"rule": rule, "model": out.score}, "reason": reason}


def search_semantic(query: str, k: int = 5) -> list[int]:
    rows = db.search_candidates(SEARCH_CANDIDATES)
    if not rows or not query.strip():
        return []
    lines = "\n".join(f"{r['id']} | {r['title']} | {r['category'] or ''}" for r in rows)
    out = _structured(SearchOut, _render("nm_search_semantic.md", k=k, query=query, listings=lines), fast=True)
    valid = {r["id"] for r in rows}
    return [i for i in dict.fromkeys(out.ids) if i in valid][:k]
