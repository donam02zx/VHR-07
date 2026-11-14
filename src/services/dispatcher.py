"""Phân loại tin đến → handler, rồi gửi các Reply qua kênh (docs/nm/02, 06)."""

from __future__ import annotations

import asyncio
import logging

from src.channels.zalo import Inbound, ZaloClient
from src.config import get_settings
from src.services import agent, commands, posting
from src.services.posting import Reply

logger = logging.getLogger("nm.dispatcher")

AGENT_TIMEOUT_S = 40.0  # nhiều bước gọi LLM; quá giờ → luật từ khoá


def classify(inbound: Inbound) -> str:
    """'image' | 'command' | 'text' — hàm thuần để test."""
    if inbound.image_ref:
        return "image"
    if inbound.text.lstrip().startswith("/"):
        return "command"
    return "text"


async def route(inbound: Inbound, client: ZaloClient) -> list[Reply]:
    kind = classify(inbound)
    if kind != "text":
        agent.clear_pending(inbound.chat_id)
    if kind == "image":
        return await posting.handle_image(inbound, client.download_image)
    if kind == "command":
        return await commands.handle(inbound)
    if pending := agent.take_pending(inbound.chat_id, inbound.text):
        return agent.resolve_pending(inbound, *pending)
    draft = posting.current_draft(inbound.chat_id)
    if draft is not None:
        replies = await posting.handle_draft_text(inbound, draft)
        if replies is not None:
            return replies
    elif get_settings().nm_agent_enabled:
        try:
            return await asyncio.wait_for(agent.run(inbound), AGENT_TIMEOUT_S)
        except Exception as exc:  # agent là lớp "thông minh hơn"; hỏng thì luật từ khoá vẫn trả lời được
            logger.warning("agent lỗi event=%s (%s) → dùng luật từ khoá", inbound.event_key, type(exc).__name__)
    return await commands.handle_natural(inbound, draft["id"] if draft else None)


async def send_reply(client: ZaloClient, reply: Reply) -> None:
    if reply.photo:
        await client.send_photo(reply.chat_id, reply.photo, reply.text)
    else:
        await client.send_text(reply.chat_id, reply.text)


async def deliver(client: ZaloClient, replies: list[Reply], origin_chat: str | None, ref: str) -> bool:
    """Gửi lần lượt; lỗi một tin chỉ log, không chặn tin khác. Trả True nếu tất cả gửi được.

    notify_ok / notify_fail của Reply được gửi về `origin_chat` (người ra lệnh).
    """
    all_ok = True
    for reply in replies:
        try:
            await send_reply(client, reply)
            ok = True
        except Exception as exc:
            ok = all_ok = False
            logger.error("gửi tin lỗi ref=%s chat=%s: %s", ref, reply.chat_id, type(exc).__name__)
        notice = reply.notify_ok if ok else reply.notify_fail
        if notice and origin_chat:
            try:
                await client.send_text(origin_chat, notice)
            except Exception as exc:
                all_ok = False
                logger.error("gửi thông báo lỗi ref=%s chat=%s: %s", ref, origin_chat, type(exc).__name__)
    return all_ok


async def handle(inbound: Inbound, client: ZaloClient) -> list[Reply]:
    """Xử lý một tin đến và gửi trả lời."""
    kind = classify(inbound)
    # Không log nội dung tin (09) — chỉ loại, tên lệnh, có ảnh, độ dài chữ.
    command = inbound.text.split(maxsplit=1)[0][:20] if kind == "command" and inbound.text.strip() else "-"
    logger.info(
        "in event=%s kind=%s cmd=%s has_image=%s text_len=%d",
        inbound.event_key, kind, command, bool(inbound.image_ref), len(inbound.text),
    )
    replies = await route(inbound, client)
    await deliver(client, replies, inbound.chat_id, inbound.event_key)
    logger.info("out event=%s replies=%d", inbound.event_key, len(replies))
    return replies
