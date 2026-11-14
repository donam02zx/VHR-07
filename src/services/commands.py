"""Lệnh người dùng (docs/nm/08). Lệnh không đổi trạng thái hội thoại (06), trừ khi rút chính bản nháp đang chờ."""

from __future__ import annotations

import logging

from src.channels.zalo import Inbound
from src.config import get_settings
from src.services import db, intent, posting, reviewflow, search, watches
from src.services.pii import mask_phone
from src.services.posting import Reply
from src.services.text import normalize_text

logger = logging.getLogger("nm.commands")

HELP = (
    "Cách dùng NeighborMarket:\n"
    "- Gửi ảnh món đồ (kèm mô tả, giá nếu có) để đăng tin.\n"
    "- /tim <từ khoá>: tìm tin đã đăng.\n"
    "- /xem <mã tin>: xem chi tiết một tin.\n"
    "- /hoi <mã tin> <câu hỏi>: hỏi người bán (ẩn danh qua bot).\n"
    "- /tl <mã hỏi> <trả lời>: người bán trả lời người hỏi.\n"
    "- Săn tin: \"báo mình khi có laptop dưới 5 triệu\" (xem: /santin, bỏ: /huysan <mã>).\n"
    "- /tincuatoi: xem tin của bạn.\n"
    "- /rut <mã tin>: rút tin của bạn."
)
HELP_SHORT = "Mình chưa biết lệnh này. Gõ /help để xem các lệnh."
WELCOME = (
    "Chào bạn! Mình là bot mua bán đồ cũ trong chung cư.\n"
    "- Muốn BÁN: gửi ảnh món đồ kèm mô tả và giá (vd: \"Laptop Dell còn tốt 5tr\").\n"
    "- Muốn MUA: nhắn thẳng, vd \"tìm laptop\" hoặc \"có ai bán xe đạp không\".\n"
    "- Xem tin: \"xem tin 13\". Hỏi người bán: \"hỏi 13 còn không bạn?\"."
)
DRAFT_REMINDER = 'Bạn vẫn còn bản nháp tin #{lid} chờ xác nhận ("ok" để đăng, "thôi" để bỏ).'
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
RELAY_MAX = 500  # ký tự mỗi tin chuyển
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
    if name == "/xem":
        return _view(chat, args)
    if name == "/hoi":
        return _ask(chat, user_id, args)
    if name == "/tl":
        return _answer(chat, user_id, args)
    if name == "/tincuatoi":
        return [Reply(chat, _my_listings(user_id))]
    if name == "/rut":
        return _withdraw(chat, user_id, args)
    if name in ("/duyet", "/tuchoi"):
        return _moderate(inbound, name, args)
    if name == "/santin":
        if not args:
            return [Reply(chat, watches.list_text(user_id))]
        lo, hi, rest = intent.parse_price_range(args)
        return [Reply(chat, watches.create(user_id, intent.keywords(rest), lo, hi)[1])]
    if name == "/huysan":
        wid = _parse_id(args)
        if wid is None:
            return [Reply(chat, "Gõ /huysan <mã săn>. Xem mã: /santin")]
        ok = db.cancel_watch(wid, user_id)
        return [Reply(chat, f"Đã bỏ săn tin mã {wid}." if ok else f"Không tìm thấy mã săn {wid} của bạn.")]
    return [Reply(chat, HELP_SHORT)]


async def handle_natural(inbound: Inbound, draft_id: int | None = None) -> list[Reply]:
    """Câu tự nhiên không có "/" (vd "tôi muốn tìm laptop"). Không đổi trạng thái hội thoại.

    Đang có bản nháp (`draft_id`): chỉ làm khi câu có ý định RÕ (tìm/xem/hỏi...), kèm nhắc bản nháp;
    câu mơ hồ → hướng dẫn trả lời bản nháp, tránh hiểu nhầm câu của người bán thành tìm kiếm.
    """
    user_id = db.upsert_user(inbound.user_id, inbound.display_name)
    chat = inbound.chat_id
    if draft_id is None and intent.draft_action(inbound.text)[0] in ("confirm", "cancel"):
        return [Reply(chat, posting.MSG_NO_DRAFT)]  # "ok"/"thôi" khi không có nháp
    it = intent.detect(inbound.text)
    if draft_id is not None and (not it.explicit or it.kind in ("greet", "unknown", "sell")):
        return [Reply(chat, posting.MSG_CONFIRM_HELP)]
    replies = _natural_replies(chat, user_id, it)
    if draft_id is not None:
        replies.append(Reply(chat, DRAFT_REMINDER.format(lid=draft_id)))
    return replies


def _natural_replies(chat: str, user_id: int, it: intent.Intent) -> list[Reply]:
    if it.kind in ("greet", "unknown"):
        return [Reply(chat, WELCOME)]
    if it.kind == "thanks":
        return [Reply(chat, "Không có gì ạ! Cần tìm hay bán gì cứ nhắn mình nhé.")]
    if it.kind == "help":
        return [Reply(chat, HELP)]
    if it.kind == "my_listings":
        return [Reply(chat, _my_listings(user_id))]
    if it.kind == "view":
        return _view(chat, str(it.listing_id))
    if it.kind == "ask":
        return _ask(chat, user_id, f"{it.listing_id} {it.query}")
    if it.kind == "sell":
        item = f" {it.query}" if it.query else ""
        return [Reply(chat, f"Để đăng bán{item}, bạn gửi ẢNH món đồ kèm mô tả và giá "
                            f"(vd: \"{(it.query or 'Laptop Dell').capitalize()} còn tốt 5tr\") nhé.")]
    if it.kind == "watch":
        return [Reply(chat, watches.create(user_id, it.query, it.min_price, it.max_price)[1])]
    if it.kind == "my_watches":
        return [Reply(chat, watches.list_text(user_id))]
    # search
    if not it.query and it.min_price is None and it.max_price is None:
        return [Reply(chat, 'Bạn muốn tìm gì? Ví dụ: "tìm laptop", "có ai bán xe đạp không".')]
    rows = search.search(it.query, min_price=it.min_price, max_price=it.max_price)
    what = watches.describe(it.query, it.min_price, it.max_price)
    if not rows:
        return [Reply(chat, f"Chưa có tin nào khớp {what}. Muốn mình báo khi có thì nhắn "
                            f"\"báo mình khi có {it.query or 'món này'}\" nhé.")]
    return [Reply(chat, search.format_results(rows))]


def _published(lid: int) -> dict | None:
    listing = db.get_listing(lid)
    return listing if listing is not None and listing["status"] == "published" else None


def _view(chat: str, args: str) -> list[Reply]:
    """Chi tiết tin đang đăng: ảnh (nếu là URL) + bản công khai (che SĐT, không lộ người bán)."""
    lid = _parse_id(args)
    if lid is None:
        return [Reply(chat, "Gõ /xem <mã tin>, ví dụ: /xem 23")]
    listing = _published(lid)
    if listing is None:
        return [Reply(chat, f"Không tìm thấy tin #{lid} đang đăng.")]
    replies = []
    image = listing.get("image_ref") or ""
    if image.startswith(("http://", "https://")):
        replies.append(Reply(chat, f"Tin #{lid}", photo=image))
    replies.append(Reply(chat, posting.public_text(listing)))
    return replies


def _split_id_text(args: str) -> tuple[int | None, str]:
    id_raw, _, text = args.partition(" ")
    return _parse_id(id_raw), text.strip()


def _ask(chat: str, buyer_id: int, args: str) -> list[Reply]:
    """Người mua hỏi người bán qua bot — không bên nào thấy SĐT/tên/ID của bên kia."""
    lid, question = _split_id_text(args)
    if lid is None or not question:
        return [Reply(chat, "Gõ /hoi <mã tin> <câu hỏi>, ví dụ: /hoi 13 còn không bạn?")]
    if len(question) > RELAY_MAX:
        return [Reply(chat, f"Câu hỏi tối đa {RELAY_MAX} ký tự.")]
    listing = _published(lid)
    if listing is None:
        return [Reply(chat, f"Không tìm thấy tin #{lid} đang đăng.")]
    if listing["seller_id"] == buyer_id:
        return [Reply(chat, f"Tin #{lid} là tin của bạn.")]
    tid = db.get_or_create_thread(lid, buyer_id)["id"]
    db.add_audit(lid, "relay_ask", f"thread={tid}")  # không lưu nội dung (09)
    to_seller = (
        f"Có người hỏi tin #{lid} ({listing['title']}) — mã hỏi {tid}:\n"
        f"{mask_phone(question)}\n"
        f"Trả lời: /tl {tid} <nội dung>"
    )
    return [
        Reply(
            reviewflow.seller_chat_id(listing),
            to_seller,
            notify_ok=f"Đã chuyển câu hỏi tới người bán tin #{lid}. Bot sẽ báo khi có trả lời.",
            notify_fail=f"Chưa gửi được câu hỏi tới người bán tin #{lid}. Bạn thử lại sau nhé.",
        )
    ]


def _answer(chat: str, seller_id: int, args: str) -> list[Reply]:
    """Người bán trả lời một luồng hỏi; chỉ đúng người bán của tin mới trả lời được."""
    tid, answer = _split_id_text(args)
    if tid is None or not answer:
        return [Reply(chat, "Gõ /tl <mã hỏi> <trả lời>, ví dụ: /tl 5 còn bạn nhé")]
    if len(answer) > RELAY_MAX:
        return [Reply(chat, f"Trả lời tối đa {RELAY_MAX} ký tự.")]
    thread = db.get_thread(tid)
    if thread is None or thread["seller_id"] != seller_id:
        if thread is not None:
            logger.warning("trả lời sai chủ thread=%s", tid)
        return [Reply(chat, f"Không tìm thấy mã hỏi {tid} cho tin của bạn.")]
    db.touch_thread(tid)
    lid = thread["listing_id"]
    db.add_audit(lid, "relay_answer", f"thread={tid}")
    to_buyer = (
        f"Người bán tin #{lid} ({thread['title']}) trả lời:\n"
        f"{mask_phone(answer)}\n"
        f"Hỏi tiếp: /hoi {lid} <câu hỏi>"
    )
    return [
        Reply(
            thread["buyer_zalo_id"],
            to_buyer,
            notify_ok=f"Đã chuyển trả lời (mã hỏi {tid}).",
            notify_fail=f"Chưa gửi được trả lời (mã hỏi {tid}). Bạn thử lại sau nhé.",
        )
    ]


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
