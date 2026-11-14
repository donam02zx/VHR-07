"""Agent LLM (Gemini) cho câu tự nhiên: tự chọn công cụ, nhiều bước, nhớ vài lượt gần nhất.

Vì sao vòng lặp gọi công cụ tự viết thay vì graph RAG mẫu trong `src/agents/`: graph mẫu thiết kế cho
hỏi-đáp kiến thức; ở đây công cụ là dữ liệu thật của chợ (tìm/xem/hỏi người bán/săn tin) và cần
gắn với người đang chat. Vẫn giữ các nguyên tắc của repo: giới hạn số bước (escape hatch), HITL cho
hành động thay người dùng, nội dung tin đăng coi là DỮ LIỆU (chống prompt injection), không log nội dung.

Lỗi/quá giờ/quá bước → ném lỗi; dispatcher quay về luật từ khoá (`commands.handle_natural`).
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool

from src.agents.prompts import load_prompt
from src.channels.zalo import Inbound
from src.config import get_settings
from src.services import commands, db, search, watches
from src.services.nm_llm import get_nm_llm
from src.services.pii import mask_phone
from src.services.posting import Reply, format_vnd
from src.services.text import normalize_text

logger = logging.getLogger("nm.agent")

HISTORY_MESSAGES = 8  # 4 lượt hỏi-đáp gần nhất mỗi chat (trong bộ nhớ, mất khi khởi động lại)
REPLY_MAX = 1800
PENDING_TTL_S = 600
CONFIRM_SEND = {"gui", "gui di", "gui nhe", "ok", "oke", "ok gui", "dong y", "u", "uh", "yes", "co", "co gui"}
CANCEL_SEND = {"thoi", "huy", "khong", "khong gui", "bo", "thoi khoi", "khoi"}

llm_factory: Callable[[], Any] = lambda: get_nm_llm(fast=False, temperature=0.3)  # noqa: E731 — test thay

_history: dict[str, deque[BaseMessage]] = {}
_pending: dict[str, PendingAsk] = {}


class AgentError(RuntimeError):
    """Agent không cho được câu trả lời dùng được (quá bước, trả rỗng...)."""


@dataclass
class PendingAsk:
    """Câu hỏi agent soạn hộ, CHỜ người dùng gõ "gửi" (HITL) — không tự gửi thay người dùng."""

    listing_id: int
    question: str
    created: float = field(default_factory=time.monotonic)


@dataclass
class _Ctx:
    chat: str
    user_id: int
    tools_called: list[str] = field(default_factory=list)
    photo: Reply | None = None


# ---------------------------------------------------------------- xác nhận gửi (HITL)
def clear_pending(chat: str) -> None:
    _pending.pop(chat, None)


def take_pending(chat: str, text: str) -> tuple[str, PendingAsk] | None:
    """Có câu hỏi chờ xác nhận: "gửi" → ("send", p); "thôi" → ("cancel", p); câu khác → huỷ chờ, None."""
    p = _pending.pop(chat, None)
    if p is None or time.monotonic() - p.created > PENDING_TTL_S:
        return None
    norm = normalize_text(text).strip(" .!?")
    if norm in CONFIRM_SEND:
        return "send", p
    if norm in CANCEL_SEND:
        return "cancel", p
    return None


def resolve_pending(inbound: Inbound, action: str, p: PendingAsk) -> list[Reply]:
    if action == "cancel":
        return [Reply(inbound.chat_id, "Ok, mình không gửi câu hỏi đó.")]
    user_id = db.upsert_user(inbound.user_id, inbound.display_name)
    return commands._ask(inbound.chat_id, user_id, f"{p.listing_id} {p.question}")


# ---------------------------------------------------------------- công cụ
def _price(v: int | None) -> str:
    return format_vnd(v) if v else "thương lượng"


def _make_tools(ctx: _Ctx) -> list[StructuredTool]:
    def search_listings(query: str = "", min_price: int | None = None, max_price: int | None = None) -> dict:
        """Tìm tin đang đăng theo từ khoá (tiếng Việt, có/không dấu) và khoảng giá VND. Trả tối đa 5 tin."""
        rows = search.search(query, 5, min_price, max_price)
        return {
            "count": len(rows),
            "results": [{"id": r["id"], "title": mask_phone(r["title"] or ""), "price": _price(r["price_vnd"]),
                         "condition": r["condition"] or ""} for r in rows],
        }

    def get_listing(listing_id: int) -> dict:
        """Chi tiết một tin đang đăng theo mã tin."""
        listing = db.get_listing(listing_id)
        if listing is None or listing["status"] != "published":
            return {"error": f"Không có tin #{listing_id} đang đăng."}
        image = listing.get("image_ref") or ""
        if ctx.photo is None and image.startswith(("http://", "https://")):
            ctx.photo = Reply(ctx.chat, f"Tin #{listing_id}", photo=image)
        return {
            "id": listing_id, "title": mask_phone(listing["title"] or ""), "price": _price(listing["price_vnd"]),
            "condition": listing["condition"] or "", "category": listing["category"] or "",
            "description": mask_phone(listing["description"] or ""), "has_photo": bool(image),
        }

    def my_listings() -> dict:
        """Các tin của chính người đang chat, kèm trạng thái."""
        rows = db.list_listings_by_seller(ctx.user_id)
        return {"listings": [{"id": r["id"], "title": r["title"], "status": commands.STATUS_VI.get(r["status"],
                                                                                                 r["status"])}
                             for r in rows]}

    def ask_seller(listing_id: int, question: str) -> dict:
        """Soạn câu hỏi ẩn danh gửi người bán của một tin. CHƯA gửi: chờ người dùng gõ "gửi" để xác nhận."""
        listing = db.get_listing(listing_id)
        if listing is None or listing["status"] != "published":
            return {"error": f"Không có tin #{listing_id} đang đăng."}
        if listing["seller_id"] == ctx.user_id:
            return {"error": "Đây là tin của chính người dùng."}
        question = question.strip()[: commands.RELAY_MAX]
        if not question:
            return {"error": "Câu hỏi trống."}
        _pending[ctx.chat] = PendingAsk(listing_id, question)
        return {"status": "waiting_user_confirmation", "listing_id": listing_id, "question": question,
                "tell_user": f'Hỏi người bán tin #{listing_id}: "{question}". Gõ "gửi" để gửi, "thôi" để bỏ.'}

    def watch_listings(query: str = "", min_price: int | None = None, max_price: int | None = None) -> dict:
        """Săn tin: lưu yêu cầu để bot tự nhắn người dùng khi có tin mới khớp từ khoá và khoảng giá."""
        wid, message = watches.create(ctx.user_id, query, min_price, max_price)
        return {"watch_id": wid, "message": message}

    def list_watches() -> dict:
        """Các yêu cầu săn tin đang bật của người dùng."""
        return {"watches": [{"id": w["id"], "what": watches.describe(w["query"], w["min_price"], w["max_price"])}
                            for w in db.list_watches(ctx.user_id)]}

    def cancel_watch(watch_id: int) -> dict:
        """Bỏ một yêu cầu săn tin của người dùng theo mã săn."""
        return {"cancelled": db.cancel_watch(watch_id, ctx.user_id)}

    funcs = [search_listings, get_listing, my_listings, ask_seller, watch_listings, list_watches, cancel_watch]
    return [StructuredTool.from_function(f) for f in funcs]


# ---------------------------------------------------------------- vòng lặp agent
def _text(msg: AIMessage) -> str:
    content = msg.content
    if isinstance(content, str):
        return content
    return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)


def _clean(text: str) -> str:
    """Zalo không hiển thị markdown; che SĐT lần cuối; giới hạn độ dài."""
    text = re.sub(r"\*\*|__|`|^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\*\s+", "- ", text, flags=re.MULTILINE)
    return mask_phone(text.strip())[:REPLY_MAX]


async def run(inbound: Inbound) -> list[Reply]:
    """Trả lời một câu tự nhiên bằng agent. Ném lỗi nếu không xong — nơi gọi quay về luật."""
    user_id = db.upsert_user(inbound.user_id, inbound.display_name)
    ctx = _Ctx(inbound.chat_id, user_id)
    tools = _make_tools(ctx)
    by_name = {t.name: t for t in tools}
    model = llm_factory().bind_tools(tools)
    history = _history.setdefault(inbound.chat_id, deque(maxlen=HISTORY_MESSAGES))
    messages: list[BaseMessage] = [
        SystemMessage(load_prompt("nm_agent_system.md")),
        *history,
        HumanMessage(inbound.text),
    ]
    max_steps = get_settings().nm_agent_max_steps
    for _ in range(max_steps):
        ai_msg = await model.ainvoke(messages)
        messages.append(ai_msg)
        if not ai_msg.tool_calls:
            break
        for call in ai_msg.tool_calls:
            ctx.tools_called.append(call["name"])
            tool = by_name.get(call["name"])
            try:
                result = tool.invoke(call["args"]) if tool else {"error": f"Không có công cụ {call['name']}"}
            except Exception as exc:  # tham số sai từ LLM → báo lại cho LLM tự sửa
                logger.warning("tool %s lỗi: %s", call["name"], type(exc).__name__)
                result = {"error": f"Tham số không hợp lệ: {type(exc).__name__}"}
            messages.append(ToolMessage(json.dumps(result, ensure_ascii=False), tool_call_id=call["id"]))
    else:
        raise AgentError(f"quá {max_steps} bước")
    text = _clean(_text(ai_msg))
    if not text:
        raise AgentError("trả lời rỗng")
    if ctx.chat in _pending and "gửi" not in text.lower():
        text += '\n(Gõ "gửi" để gửi câu hỏi, "thôi" để bỏ.)'
    history.append(HumanMessage(inbound.text))
    history.append(AIMessage(text))
    logger.info("agent event=%s steps=%d tools=%s", inbound.event_key, len(ctx.tools_called), ctx.tools_called)
    replies = [ctx.photo] if ctx.photo else []
    replies.append(Reply(inbound.chat_id, text))
    return replies
