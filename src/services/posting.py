"""Máy trạng thái đăng tin (docs/nm/06).

Handler nhận `Inbound`, trả danh sách `Reply` để dispatcher gửi — tách I/O kênh khỏi logic để test dễ.
Trạng thái hội thoại ở `conversations`, trạng thái tin ở `listings` (DB là nguồn sự thật).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from src.channels.zalo import Inbound
from src.config import get_settings
from src.services import ai, db, intent, moderation
from src.services.pii import mask_phone
from src.services.safe_ai import AIUnavailableError, call_ai, check_draft, check_price
from src.services.vnd import parse_vnd

logger = logging.getLogger("nm.posting")

FetchImage = Callable[[str], Awaitable[bytes]]

DESCRIPTION_MAX = 1200  # giữ bản nháp < 2000 ký tự
TITLE_MAX = 120

MSG_CONFIRM_HELP = (
    'Bạn đang có bản nháp chờ xác nhận. Trả lời "ok" để đăng, "giá 1tr2" để đổi giá, '
    '"đổi tên <tên mới>" để đổi tiêu đề, hoặc "thôi" để bỏ.'
)
MSG_IMAGE_FAIL = "Mình không tải được ảnh, bạn gửi lại giúp nhé."
MSG_AI_BUSY = "Hệ thống soạn tin đang bận, bạn gửi lại ảnh sau ít phút nhé."
MSG_BAD_PRICE = 'Mình chưa hiểu giá "{raw}". Ví dụ: "giá 800k", "giá 1tr2", "giá 1.200.000".'
MSG_NO_DRAFT = "Bạn chưa có bản nháp nào. Muốn bán thì gửi ảnh món đồ kèm mô tả và giá nhé."
MSG_BAD_TITLE = "Tiêu đề cần từ 1 đến 120 ký tự."
MSG_LOST = "Không tìm thấy bản nháp, bạn gửi lại ảnh để đăng mới nhé."

# Giá trong chú thích ảnh: số + đơn vị (bắt buộc đơn vị để không nhầm số khác thành giá).
_CAPTION_PRICE = re.compile(
    r"\d[\d.,]*\s*(?:triệu|trieu|tr|củ|cu|nghìn|nghin|ngàn|ngan|k|vnd|đ)(?:\s*\d{1,3}(?:\s*(?:k|nghìn|nghin))?)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Reply:
    """Một tin bot gửi đi.

    photo: URL ảnh → gửi bằng sendPhoto, `text` là chú thích (ngắn).
    notify_ok / notify_fail: báo lại cho người gửi lệnh tuỳ việc gửi tin này thành công hay không
    (vd chuyển câu hỏi tới người bán) — để không báo "đã gửi" khi thực ra gửi lỗi.
    """

    chat_id: str
    text: str
    photo: str | None = None
    notify_ok: str | None = None
    notify_fail: str | None = None


def format_vnd(n: int) -> str:
    return f"{n:,}".replace(",", ".") + " đ"


def price_from_caption(caption: str) -> int | None:
    """Giá người bán ghi kèm ảnh (vd "Xe đạp 1tr2"), None nếu không có/không chắc."""
    for m in _CAPTION_PRICE.finditer(caption):
        value = parse_vnd(m.group(0))
        if value is not None:
            return value
    return None


def draft_text(listing: dict[str, Any], price_note: str = "") -> str:
    lines = [
        f"Bản nháp tin #{listing['id']}",
        f"Tiêu đề: {listing['title']}",
        f"Mô tả: {listing['description'] or '(trống)'}",
        f"Tình trạng: {listing['condition']}",
    ]
    if listing.get("price_low") and listing.get("price_high"):
        lines.append(f"Giá gợi ý: {format_vnd(listing['price_low'])} – {format_vnd(listing['price_high'])}")
    lines.append(f"Giá đăng: {format_vnd(listing['price_vnd'])}{price_note}")
    lines.append('Trả lời: "ok" để đăng, "giá 1tr2" để đổi giá, "đổi tên ..." để đổi tiêu đề, "thôi" để bỏ.')
    return "\n".join(lines)


def public_text(listing: dict[str, Any]) -> str:
    """Nội dung đăng công khai: đã che SĐT, KHÔNG có tên/ID người bán (08)."""
    lines = [
        f"Tin #{listing['id']}: {mask_phone(listing['title'] or '')}",
        f"Giá: {format_vnd(listing['price_vnd'])}" if listing.get("price_vnd") else "Giá: thương lượng",
        f"Tình trạng: {listing['condition'] or 'không rõ'}",
    ]
    if listing.get("description"):
        lines.append(mask_phone(listing["description"]))
    lines.append(f"Hỏi người bán (ẩn danh qua bot): /hoi {listing['id']} <câu hỏi>")
    return "\n".join(lines)


def publish_replies(listing: dict[str, Any], seller_chat_id: str) -> list[Reply]:
    """Tin vừa `published`: báo người bán, và đăng vào nhóm nếu có ZALO_GROUP_CHAT_ID (06)."""
    replies = [Reply(seller_chat_id, f"Tin #{listing['id']} đã được đăng.")]
    group = get_settings().zalo_group_chat_id
    if group:
        replies.append(Reply(group, public_text(listing)))
    return replies


# ---------------------------------------------------------------- handlers
async def handle_image(inbound: Inbound, fetch_image: FetchImage) -> list[Reply]:
    """Ảnh (±chú thích) ở idle hoặc awaiting_confirm → bản nháp mới; bản cũ (nếu có) bị huỷ."""
    if not inbound.image_ref:
        raise ValueError("handle_image cần inbound.image_ref")
    try:
        image = await fetch_image(inbound.image_ref)
    except Exception as exc:
        logger.warning("tải ảnh lỗi event=%s: %s", inbound.event_key, type(exc).__name__)
        return [Reply(inbound.chat_id, MSG_IMAGE_FAIL)]
    try:
        draft = check_draft(await call_ai(ai.draft_listing, image, inbound.text))
        price = check_price(await call_ai(ai.suggest_price, draft))
    except AIUnavailableError:
        logger.warning("AI soạn nháp lỗi event=%s", inbound.event_key)
        return [Reply(inbound.chat_id, MSG_AI_BUSY)]

    _withdraw_current(inbound.chat_id, "ảnh mới thay bản cũ")

    stated = price_from_caption(inbound.text)
    price_vnd = stated if stated is not None else (price["low"] + price["high"]) // 2
    note = "" if stated is not None else " (chưa nêu giá — tạm lấy giữa khoảng gợi ý)"
    seller_id = db.upsert_user(inbound.user_id, inbound.display_name)
    listing_id = db.create_listing(
        seller_id,
        title=draft["title"][:TITLE_MAX] or "Món đồ cần bán",
        description=draft["description"][:DESCRIPTION_MAX],
        category=draft["category"],
        condition=draft["condition"],
        price_low=price["low"],
        price_high=price["high"],
        price_vnd=price_vnd,
        image_ref=inbound.image_ref,
    )
    if not db.set_status(listing_id, "draft", "awaiting_confirm"):
        raise RuntimeError(f"listing {listing_id} vừa tạo nhưng không ở draft")
    db.set_conversation(inbound.chat_id, "awaiting_confirm", listing_id)
    db.add_audit(listing_id, "draft_created", f"event={inbound.event_key}")
    return [Reply(inbound.chat_id, draft_text(db.get_listing(listing_id), note))]


def current_draft(chat_id: str) -> dict[str, Any] | None:
    """Bản nháp đang chờ xác nhận của chat; hội thoại trỏ sai thì đưa về idle (có log)."""
    conv = db.get_conversation(chat_id)
    if conv["state"] != "awaiting_confirm":
        return None
    listing = db.get_listing(conv["listing_id"]) if conv["listing_id"] else None
    if listing is None or listing["status"] != "awaiting_confirm":
        logger.warning("conversation %s trỏ tới tin không hợp lệ: %s", chat_id, conv["listing_id"])
        db.set_conversation(chat_id, "idle")
        return None
    return listing


async def handle_draft_text(inbound: Inbound, listing: dict[str, Any]) -> list[Reply] | None:
    """Câu trả lời cho bản nháp ("ok", "thôi", "giá 1tr2", "đổi tên ..."). None = không phải lệnh nháp."""
    action, rest = intent.draft_action(inbound.text)
    if action == "confirm":
        return await _confirm(inbound.chat_id, listing)
    if action == "cancel":
        _withdraw_current(inbound.chat_id, "người bán huỷ")
        return [Reply(inbound.chat_id, f"Đã huỷ bản nháp tin #{listing['id']}.")]
    if action == "price":
        return _edit_price(inbound, listing, rest)
    if action == "title":
        return _edit_title(inbound, listing, rest)
    return None


# ---------------------------------------------------------------- nội bộ
def _edit_price(inbound: Inbound, listing: dict[str, Any], raw: str) -> list[Reply]:
    value = parse_vnd(raw) if raw else None
    if value is None:
        return [Reply(inbound.chat_id, MSG_BAD_PRICE.format(raw=raw))]
    db.update_listing_fields(listing["id"], price_vnd=value)
    db.add_audit(listing["id"], "edit_price", str(value))
    return [Reply(inbound.chat_id, draft_text(db.get_listing(listing["id"])))]


def _edit_title(inbound: Inbound, listing: dict[str, Any], title: str) -> list[Reply]:
    if not 0 < len(title) <= TITLE_MAX:
        return [Reply(inbound.chat_id, MSG_BAD_TITLE)]
    db.update_listing_fields(listing["id"], title=title)
    db.add_audit(listing["id"], "edit_title", "")
    return [Reply(inbound.chat_id, draft_text(db.get_listing(listing["id"])))]


def _withdraw_current(chat_id: str, why: str) -> None:
    """Huỷ bản nháp đang chờ xác nhận của chat (nếu có) và đưa hội thoại về idle."""
    conv = db.get_conversation(chat_id)
    if conv["state"] == "awaiting_confirm" and conv["listing_id"]:
        if db.set_status(conv["listing_id"], "awaiting_confirm", "withdrawn"):
            db.add_audit(conv["listing_id"], "withdrawn", why)
    db.set_conversation(chat_id, "idle")


def reopen_for_fix(chat_id: str, listing_id: int) -> None:
    """Người duyệt trả về `needs_fix` → tin về `awaiting_confirm`, hội thoại chờ "sửa ..."/"ok".

    Bản nháp khác đang dở của chat bị huỷ (có audit) — mỗi chat chỉ giữ một bản nháp.
    """
    _withdraw_current(chat_id, f"mở lại tin #{listing_id} cần sửa")
    if not db.set_status(listing_id, "needs_fix", "awaiting_confirm"):
        raise RuntimeError(f"listing {listing_id} không ở needs_fix")
    db.set_conversation(chat_id, "awaiting_confirm", listing_id)
    db.add_audit(listing_id, "reopened_for_fix", "")


async def _confirm(chat_id: str, listing: dict[str, Any]) -> list[Reply]:
    lid = listing["id"]
    if not db.set_status(lid, "awaiting_confirm", "pending_moderation"):
        return [Reply(chat_id, MSG_LOST)]
    db.set_conversation(chat_id, "idle")
    db.add_audit(lid, "confirmed", "")
    result = await moderation.process(lid)
    if result.decision == "publish":
        return publish_replies(db.get_listing(lid), chat_id)
    if result.decision == "review":
        return [Reply(chat_id, f"Tin #{lid} đang chờ người duyệt, bạn sẽ được báo.")]
    return [Reply(chat_id, f"Tin #{lid} không được đăng: {result.reason}.")]
