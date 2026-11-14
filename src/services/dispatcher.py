"""Phân loại tin đến → handler, rồi gửi các Reply qua kênh (docs/nm/02, 06)."""

from __future__ import annotations

import logging

from src.channels.zalo import Inbound, ZaloClient
from src.services import commands, posting
from src.services.posting import Reply

logger = logging.getLogger("nm.dispatcher")


def classify(inbound: Inbound) -> str:
    """'image' | 'command' | 'text' — hàm thuần để test."""
    if inbound.image_ref:
        return "image"
    if inbound.text.lstrip().startswith("/"):
        return "command"
    return "text"


async def route(inbound: Inbound, client: ZaloClient) -> list[Reply]:
    kind = classify(inbound)
    if kind == "image":
        return await posting.handle_image(inbound, client.download_image)
    if kind == "command":
        return await commands.handle(inbound)
    return await posting.handle_text(inbound)


async def handle(inbound: Inbound, client: ZaloClient) -> list[Reply]:
    """Xử lý một tin đến và gửi trả lời. Lỗi gửi một Reply được log, không chặn Reply khác."""
    replies = await route(inbound, client)
    for reply in replies:
        try:
            await client.send_text(reply.chat_id, reply.text)
        except Exception as exc:
            logger.error("gửi tin lỗi event=%s chat=%s: %s", inbound.event_key, reply.chat_id, type(exc).__name__)
    return replies
