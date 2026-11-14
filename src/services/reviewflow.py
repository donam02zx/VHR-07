"""Quyết định duyệt tay dùng chung cho API `/reviews` và lệnh moderator `/duyet`, `/tuchoi` (07, 08).

Ghi DB trước (nguồn sự thật), rồi trả các Reply để nơi gọi gửi — gửi lỗi không huỷ quyết định.
"""

from __future__ import annotations

from typing import Any

from src.services import db, posting
from src.services.posting import Reply

MSG_REJECT_DEFAULT = "nội dung chưa phù hợp quy định của nhóm"


def seller_chat_id(listing: dict[str, Any]) -> str:
    """Chat 1:1: chat.id == from.id (05, ĐÃ KIỂM CHỨNG) → nhắn theo zalo_user_id."""
    seller = db.get_user(listing["seller_id"])
    if seller is None:
        raise RuntimeError(f"listing {listing['id']} không có người bán")
    return seller["zalo_user_id"]


def decide(review_id: int, decision: str, reviewer: str, note: str = "") -> tuple[int, str, list[Reply]]:
    """`decision` ∈ approved|rejected|needs_fix. Trả (listing_id, trạng thái tin hiện tại, replies).

    Ném lỗi của db (LookupError / ReviewAlreadyDecidedError / InvalidTransitionError) cho nơi gọi xử lý.
    """
    review = db.get_review(review_id)
    if review is None:
        raise LookupError(f"review {review_id} không tồn tại")
    final_status = db.decide_review(review_id, decision, reviewer, note or None)
    lid = review["listing_id"]
    listing = db.get_listing(lid)
    chat_id = seller_chat_id(listing)
    if final_status == "published":
        replies = posting.publish_replies(listing, chat_id)
    elif final_status == "rejected":
        replies = [Reply(chat_id, f"Tin #{lid} không được đăng: {note or MSG_REJECT_DEFAULT}.")]
    else:
        # needs_fix: mở lại bản nháp để người bán "sửa ..." rồi "ok". Bản nháp khác đang dở bị huỷ.
        posting.reopen_for_fix(chat_id, lid)
        why = note or review.get("reason") or "người duyệt yêu cầu chỉnh sửa"
        head = f"Tin #{lid} cần sửa trước khi đăng: {why}."
        replies = [Reply(chat_id, head + "\n\n" + posting.draft_text(db.get_listing(lid)))]
    return lid, db.get_listing(lid)["status"], replies
