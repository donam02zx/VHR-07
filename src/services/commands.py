"""Lệnh người dùng (docs/nm/08). Lệnh không đổi trạng thái hội thoại (06), trừ khi rút chính bản nháp đang chờ."""

from __future__ import annotations

import logging

from src.channels.zalo import Inbound
from src.config import get_settings
from src.services import db, reviewflow, search
from src.services.posting import Reply
from src.services.text import normalize_text

logger = logging.getLogger("nm.commands")

HELP = (
    "Cách dùng NeighborMarket:\n"
    "- Gửi ảnh món đồ (kèm mô tả, giá nếu có) để đăng tin.\n"
    "- /tim <từ khoá>: tìm tin đã đăng.\n"
    "- /tincuatoi: xem tin của bạn.\n"
    "- /rut <mã tin>: rút tin của bạn."
)
HELP_SHORT = "Mình chưa biết lệnh này. Gõ /help để xem các lệnh."
STATUS_VI = {
    "draft": "nháp",
    "awaiting_confirm": "chờ bạn xác nhận",
    "pending_moderation": "đang kiểm duyệt",
    "in_review": "chờ người duyệt",
    "needs_fix": "cần sửa",
    "published": "đã đăng",
    "rejected": "bị từ chối",
    "withdrawn": "đã rút",
}
WITHDRAWABLE = ("published", "awaiting_confirm")
MODERATOR = "moderator"


def parse_command(text: str) -> tuple[str, str]:
    """'/TÌM   Xe  đạp' → ('/tim', 'Xe đạp'). Tên lệnh bỏ dấu + chữ thường; tham số giữ nguyên chữ."""
    parts = text.strip().split(maxsplit=1)
    if not parts:
        return "", ""
    name = normalize_text(parts[0])
    args = " ".join(parts[1].split()) if len(parts) > 1 else ""
    return name, args


def _parse_id(raw: str) -> int | None:
    raw = raw.strip().lstrip("#")
    return int(raw) if raw.isdigit() else None


async def handle(inbound: Inbound) -> list[Reply]:
    user_id = db.upsert_user(inbound.user_id, inbound.display_name)  # 08: tự tạo user resident
    name, args = parse_command(inbound.text)
    chat = inbound.chat_id
    if name == "/help":
        return [Reply(chat, HELP)]
    if name == "/tim":
        if not args:
            return [Reply(chat, "Gõ /tim <từ khoá>, ví dụ: /tim xe dap")]
        return [Reply(chat, search.format_results(search.search(args)))]
    if name == "/tincuatoi":
        return [Reply(chat, _my_listings(user_id))]
    if name == "/rut":
        return _withdraw(chat, user_id, args)
    if name in ("/duyet", "/tuchoi"):
        return _moderate(inbound, name, args)
    return [Reply(chat, HELP_SHORT)]


def _my_listings(user_id: int) -> str:
    rows = db.list_listings_by_seller(user_id)
    if not rows:
        return "Bạn chưa có tin nào. Gửi ảnh món đồ để đăng."
    lines = ["Tin của bạn:"]
    lines += [f"#{r['id']} {r['title'] or '(chưa có tiêu đề)'} — {STATUS_VI.get(r['status'], r['status'])}" for r in rows]
    return "\n".join(lines)


def _withdraw(chat: str, user_id: int, args: str) -> list[Reply]:
    lid = _parse_id(args)
    if lid is None:
        return [Reply(chat, "Gõ /rut <mã tin>, ví dụ: /rut 23")]
    listing = db.get_listing(lid)
    if listing is None or listing["seller_id"] != user_id:
        # Không tiết lộ tin của người khác có tồn tại hay không.
        if listing is not None:
            logger.warning("rút tin sai chủ listing=%s", lid)
        return [Reply(chat, f"Không tìm thấy tin #{lid} của bạn.")]
    status = listing["status"]
    if status not in WITHDRAWABLE or not db.set_status(lid, status, "withdrawn"):
        return [Reply(chat, f"Tin #{lid} đang ở trạng thái '{STATUS_VI.get(status, status)}', không rút được.")]
    db.add_audit(lid, "withdrawn", "người bán /rut")
    conv = db.get_conversation(chat)
    if conv["listing_id"] == lid:
        db.set_conversation(chat, "idle")
    replies = [Reply(chat, f"Tin #{lid} đã được gỡ.")]
    group = get_settings().zalo_group_chat_id
    if status == "published" and group:
        # Không xoá được tin đã gửi (05) → báo nhóm là tin đã gỡ.
        replies.append(Reply(group, f"Tin #{lid} đã được gỡ."))
    return replies


def _moderate(inbound: Inbound, name: str, args: str) -> list[Reply]:
    """Dự phòng duyệt qua Zalo (07): chỉ users.role='moderator'."""
    chat = inbound.chat_id
    user = db.get_user_by_zalo(inbound.user_id)
    if user is None or user["role"] != MODERATOR:
        return [Reply(chat, "Lệnh này chỉ dành cho người duyệt.")]
    id_raw, _, note = args.partition(" ")
    lid = _parse_id(id_raw)
    if lid is None or (name == "/tuchoi" and not note.strip()):
        usage = "/duyet <mã tin>" if name == "/duyet" else "/tuchoi <mã tin> <lý do>"
        return [Reply(chat, f"Cú pháp: {usage}")]
    review = db.pending_review_for_listing(lid)
    if review is None:
        return [Reply(chat, f"Tin #{lid} không có trong hàng chờ duyệt.")]
    decision = "approved" if name == "/duyet" else "rejected"
    try:
        _, status, replies = reviewflow.decide(review["id"], decision, f"zalo:{inbound.user_id}", note.strip())
    except (db.ReviewAlreadyDecidedError, db.InvalidTransitionError) as exc:
        logger.warning("moderator decide listing=%s: %s", lid, exc)
        return [Reply(chat, f"Tin #{lid} đã được xử lý trước đó.")]
    return [Reply(chat, f"Đã ghi: tin #{lid} → {STATUS_VI.get(status, status)}."), *replies]
