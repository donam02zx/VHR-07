"""Săn tin: người dùng đặt yêu cầu ("laptop dưới 5 triệu"), bot TỰ NHẮN khi có tin mới khớp.

Khớp khi tin vừa `published` có ĐỦ mọi từ khoá (bỏ dấu) và giá nằm trong khoảng. Không nhắn chính người bán.
Gọi từ `posting.publish_replies` — mọi đường đăng tin (tự động hoặc người duyệt) đều đi qua đó.
"""

from __future__ import annotations

import logging
from typing import Any

from src.services import db, search
from src.services.posting import Reply, format_vnd

logger = logging.getLogger("nm.watches")

MAX_ACTIVE_PER_USER = 5


def describe(query: str, min_price: int | None, max_price: int | None) -> str:
    parts = [f'"{query}"' if query else "mọi món"]
    if min_price is not None and max_price is not None:
        parts.append(f"từ {format_vnd(min_price)} đến {format_vnd(max_price)}")
    elif max_price is not None:
        parts.append(f"dưới {format_vnd(max_price)}")
    elif min_price is not None:
        parts.append(f"trên {format_vnd(min_price)}")
    return " ".join(parts)


def create(user_id: int, query: str, min_price: int | None, max_price: int | None) -> tuple[int | None, str]:
    """Trả (watch_id, câu trả lời). watch_id None = không tạo (thiếu điều kiện / quá giới hạn)."""
    query = query.strip()
    if not query and min_price is None and max_price is None:
        return None, 'Bạn muốn săn món gì? Ví dụ: "báo mình khi có laptop dưới 5 triệu".'
    if len(db.list_watches(user_id)) >= MAX_ACTIVE_PER_USER:
        return None, f"Bạn đang săn tối đa {MAX_ACTIVE_PER_USER} món. Gõ /santin để xem và /huysan <mã> để bỏ bớt."
    wid = db.create_watch(user_id, query, min_price, max_price)
    text = (
        f"Đã bật săn tin {describe(query, min_price, max_price)} (mã săn {wid}). "
        "Có tin mới khớp mình sẽ nhắn bạn ngay. Bỏ săn: /huysan " + str(wid)
    )
    existing = search.search(query, 3, min_price, max_price)
    if existing:
        text += "\nHiện đã có: " + "; ".join(f"#{r['id']} {r['title']}" for r in existing)
    return wid, text


def list_text(user_id: int) -> str:
    rows = db.list_watches(user_id)
    if not rows:
        return 'Bạn chưa săn món nào. Ví dụ: "báo mình khi có xe đạp dưới 2 triệu".'
    lines = ["Bạn đang săn:"]
    lines += [f"- mã {w['id']}: {describe(w['query'], w['min_price'], w['max_price'])}" for w in rows]
    lines.append("Bỏ săn: /huysan <mã>")
    return "\n".join(lines)


def matches(watch: dict[str, Any], listing: dict[str, Any]) -> bool:
    if not search.in_price_range(listing.get("price_vnd"), watch["min_price"], watch["max_price"]):
        return False
    words = search.tokenize(watch["query"])
    return search.match_count(listing, words) == len(words)


def notify_for(listing: dict[str, Any]) -> list[Reply]:
    """Tin vừa đăng → tin nhắn cho những người đang săn món này (mỗi người tối đa 1 tin)."""
    notified: set[str] = set()
    replies: list[Reply] = []
    for w in db.list_watches():
        if w["user_id"] == listing["seller_id"] or w["zalo_user_id"] in notified or not matches(w, listing):
            continue
        notified.add(w["zalo_user_id"])
        price = format_vnd(listing["price_vnd"]) if listing.get("price_vnd") else "thương lượng"
        replies.append(
            Reply(
                w["zalo_user_id"],
                f"Có tin mới khớp yêu cầu săn {describe(w['query'], w['min_price'], w['max_price'])}:\n"
                f"#{listing['id']} {listing['title']} — {price}\n"
                f'Nhắn "xem tin {listing["id"]}" để xem, hoặc "hỏi {listing["id"]} còn không?"',
            )
        )
        db.add_audit(listing["id"], "watch_notify", f"watch={w['id']}")
    if replies:
        logger.info("listing=%s khớp %d yêu cầu săn tin", listing["id"], len(replies))
    return replies
