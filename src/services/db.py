"""SQLite cho NeighborMarket (docs/nm/03_DATA_MODEL.md).

Vì sao `sqlite3` chuẩn, mỗi lệnh một kết nối ngắn: không thêm phụ thuộc, gọi được từ
`asyncio.to_thread` mà không chia sẻ connection giữa các thread.
Mọi truy vấn dùng tham số `?`; mọi thao tác ghi nằm trong một transaction ngắn.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.config import get_settings

logger = logging.getLogger("nm.db")

# Chuyển trạng thái hợp lệ của listings.status — chỉ các cạnh này (xem 03).
TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"awaiting_confirm", "withdrawn"}),
    "awaiting_confirm": frozenset({"pending_moderation", "withdrawn"}),
    "pending_moderation": frozenset({"published", "in_review", "rejected"}),
    "in_review": frozenset({"published", "rejected", "needs_fix"}),
    "needs_fix": frozenset({"awaiting_confirm"}),
    "published": frozenset({"withdrawn"}),
    "rejected": frozenset(),
    "withdrawn": frozenset(),
}
LISTING_STATUSES = frozenset(TRANSITIONS)
CONVERSATION_STATES = frozenset({"idle", "awaiting_confirm", "awaiting_edit"})
REVIEW_DECISIONS = frozenset({"approved", "rejected", "needs_fix"})
MAX_RESUBMIT = 3
# Cột người dùng/AI được phép sửa qua update_listing_fields (status đi qua set_status).
EDITABLE_FIELDS = frozenset(
    {
        "title",
        "description",
        "category",
        "condition",
        "price_vnd",
        "price_low",
        "price_high",
        "image_ref",
        "moderation_score",
        "moderation_reason",
    }
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY,
  zalo_user_id TEXT UNIQUE NOT NULL,
  display_name TEXT,
  role TEXT NOT NULL DEFAULT 'resident',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS listings(
  id INTEGER PRIMARY KEY,
  seller_id INTEGER NOT NULL REFERENCES users(id),
  title TEXT, description TEXT, category TEXT, condition TEXT,
  price_vnd INTEGER,
  price_low INTEGER, price_high INTEGER,
  image_ref TEXT,
  status TEXT NOT NULL,
  moderation_score REAL, moderation_reason TEXT,
  resubmit_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, published_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status);
CREATE TABLE IF NOT EXISTS conversations(
  chat_id TEXT PRIMARY KEY,
  state TEXT NOT NULL DEFAULT 'idle',
  listing_id INTEGER REFERENCES listings(id),
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_queue(
  id INTEGER PRIMARY KEY,
  listing_id INTEGER NOT NULL REFERENCES listings(id),
  reason TEXT, score REAL,
  status TEXT NOT NULL DEFAULT 'pending',
  reviewer TEXT, note TEXT,
  created_at TEXT NOT NULL, decided_at TEXT
);
CREATE TABLE IF NOT EXISTS processed_events(event_key TEXT PRIMARY KEY, created_at TEXT NOT NULL);
-- Chuyển tin ẩn danh người mua <-> người bán qua bot (/hoi, /tl). Mỗi người mua một luồng mỗi tin.
CREATE TABLE IF NOT EXISTS relay_threads(
  id INTEGER PRIMARY KEY,
  listing_id INTEGER NOT NULL REFERENCES listings(id),
  buyer_id INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL, last_at TEXT NOT NULL,
  UNIQUE(listing_id, buyer_id)
);
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY, listing_id INTEGER, action TEXT, detail TEXT, created_at TEXT NOT NULL
);
"""

_db_path_override: str | None = None


class InvalidTransitionError(ValueError):
    """Chuyển trạng thái không có trong sơ đồ 03 — lỗi lập trình, không được bỏ qua."""


class ReviewAlreadyDecidedError(Exception):
    """Mục duyệt không còn `pending` (đã có người quyết) — API sẽ trả 409."""


def now_iso() -> str:
    """Thời gian ISO 8601 UTC (quy ước 03)."""
    return datetime.now(UTC).isoformat()


def db_path() -> str:
    """Đường dẫn DB hiện dùng: override của test, nếu không thì `nm_db_path` trong cấu hình."""
    return _db_path_override or get_settings().nm_db_path


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Kết nối ngắn: bật foreign_keys, trả Row; commit khi thoát êm, rollback khi lỗi."""
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Tạo bảng nếu chưa có. Idempotent — gọi trong `lifespan` mỗi lần khởi động."""
    path = Path(db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
    logger.info("init_db xong: %s", path)


def use_db(path: str | Path) -> None:
    """Trỏ module sang file DB khác và tạo schema (script seed/simulate, test)."""
    global _db_path_override
    _db_path_override = str(path)
    init_db()


def reset_for_tests(path: str | Path) -> None:
    """Trỏ module sang DB tạm và tạo schema — chỉ dùng trong test."""
    use_db(path)


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


# ---------------------------------------------------------------- users
def upsert_user(zalo_user_id: str, display_name: str | None = None) -> int:
    """Tạo hoặc cập nhật tên người dùng theo zalo_user_id; trả users.id."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO users(zalo_user_id, display_name, created_at) VALUES(?,?,?) "
            "ON CONFLICT(zalo_user_id) DO UPDATE SET display_name=COALESCE(excluded.display_name, display_name)",
            (zalo_user_id, display_name, now_iso()),
        )
        row = conn.execute("SELECT id FROM users WHERE zalo_user_id=?", (zalo_user_id,)).fetchone()
    return int(row["id"])


USER_ROLES = frozenset({"resident", "moderator"})


def set_role(zalo_user_id: str, role: str) -> None:
    """Đặt vai trò (07: moderator cho /duyet, /tuchoi). Người dùng chưa có → tạo."""
    if role not in USER_ROLES:
        raise ValueError(f"role không hợp lệ: {role}")
    upsert_user(zalo_user_id)
    with connect() as conn:
        conn.execute("UPDATE users SET role=? WHERE zalo_user_id=?", (role, zalo_user_id))


def get_user(user_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        return _row(conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())


# ---------------------------------------------------------------- listings
def create_listing(seller_id: int, **fields: Any) -> int:
    """Tạo tin ở trạng thái `draft`; `fields` chỉ nhận cột trong EDITABLE_FIELDS."""
    _check_fields(fields)
    ts = now_iso()
    cols = ["seller_id", "status", "created_at", "updated_at", *fields]
    vals = [seller_id, "draft", ts, ts, *fields.values()]
    with connect() as conn:
        cur = conn.execute(
            f"INSERT INTO listings({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
            vals,
        )
        listing_id = int(cur.lastrowid)
    return listing_id


def get_listing(listing_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        return _row(conn.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone())


def _check_fields(fields: dict[str, Any]) -> None:
    bad = set(fields) - EDITABLE_FIELDS
    if bad:
        raise ValueError(f"Cột không được phép sửa: {sorted(bad)}")


def update_listing_fields(listing_id: int, **fields: Any) -> bool:
    """Sửa các cột nội dung của tin; trả False nếu không có tin đó."""
    if not fields:
        raise ValueError("update_listing_fields cần ít nhất một cột")
    _check_fields(fields)
    sets = ", ".join(f"{k}=?" for k in fields)  # tên cột đã qua whitelist
    with connect() as conn:
        cur = conn.execute(
            f"UPDATE listings SET {sets}, updated_at=? WHERE id=?",
            [*fields.values(), now_iso(), listing_id],
        )
    return cur.rowcount == 1


def _set_status(conn: sqlite3.Connection, listing_id: int, from_status: str, to_status: str) -> bool:
    if to_status not in TRANSITIONS.get(from_status, frozenset()):
        raise InvalidTransitionError(f"{from_status} -> {to_status} không hợp lệ")
    ts = now_iso()
    extra = ""
    if to_status == "published":
        extra = ", published_at=:ts"
    elif to_status == "needs_fix":
        extra = ", resubmit_count=resubmit_count+1"
    cur = conn.execute(
        f"UPDATE listings SET status=:to, updated_at=:ts{extra} WHERE id=:id AND status=:frm",
        {"to": to_status, "ts": ts, "id": listing_id, "frm": from_status},
    )
    if cur.rowcount != 1:
        logger.warning("set_status không khớp listing=%s %s->%s", listing_id, from_status, to_status)
        return False
    return True


def set_status(listing_id: int, from_status: str, to_status: str) -> bool:
    """Chuyển trạng thái nguyên tử (`WHERE id=? AND status=?`).

    Cạnh không có trong sơ đồ → InvalidTransitionError. Trạng thái hiện tại không khớp
    (tin đã bị chuyển bởi luồng khác, hoặc không tồn tại) → False.
    """
    with connect() as conn:
        return _set_status(conn, listing_id, from_status, to_status)


# ---------------------------------------------------------------- conversations
def get_conversation(chat_id: str) -> dict[str, Any]:
    """Trạng thái hội thoại; chat chưa từng thấy → `idle`, không có listing."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM conversations WHERE chat_id=?", (chat_id,)).fetchone()
    if row is None:
        return {"chat_id": chat_id, "state": "idle", "listing_id": None, "updated_at": None}
    return dict(row)


def set_conversation(chat_id: str, state: str, listing_id: int | None = None) -> None:
    if state not in CONVERSATION_STATES:
        raise ValueError(f"state hội thoại không hợp lệ: {state}")
    with connect() as conn:
        conn.execute(
            "INSERT INTO conversations(chat_id, state, listing_id, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET state=excluded.state, listing_id=excluded.listing_id, "
            "updated_at=excluded.updated_at",
            (chat_id, state, listing_id, now_iso()),
        )


# ---------------------------------------------------------------- events / audit
def try_mark_event(event_key: str) -> bool:
    """Đánh dấu event đã xử lý. True lần đầu, False nếu đã có (chống xử lý trùng update)."""
    with connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO processed_events(event_key, created_at) VALUES(?,?)",
            (event_key, now_iso()),
        )
    return cur.rowcount == 1


def add_audit(listing_id: int | None, action: str, detail: str = "") -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO audit_log(listing_id, action, detail, created_at) VALUES(?,?,?,?)",
            (listing_id, action, detail, now_iso()),
        )


def list_audit(listing_id: int) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM audit_log WHERE listing_id=? ORDER BY id", (listing_id,)).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- review queue
def create_review(listing_id: int, reason: str | None, score: float | None) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO review_queue(listing_id, reason, score, created_at) VALUES(?,?,?,?)",
            (listing_id, reason, score, now_iso()),
        )
        return int(cur.lastrowid)


def get_review(review_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        return _row(conn.execute("SELECT * FROM review_queue WHERE id=?", (review_id,)).fetchone())


def list_reviews(status: str = "pending") -> list[dict[str, Any]]:
    """Hàng chờ duyệt kèm nội dung tin (cũ nhất trước) cho trang duyệt."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT r.*, l.title, l.description, l.category, l.price_vnd, l.image_ref, "
            "l.status AS listing_status, l.resubmit_count "
            "FROM review_queue r JOIN listings l ON l.id = r.listing_id "
            "WHERE r.status=? ORDER BY r.id",
            (status,),
        ).fetchall()
    return [dict(r) for r in rows]


def decide_review(review_id: int, decision: str, reviewer: str, note: str | None = None) -> str:
    """Ghi quyết định duyệt và chuyển trạng thái tin trong cùng một transaction.

    Trả trạng thái tin sau cùng. `needs_fix` khi tin đã sửa lại đủ MAX_RESUBMIT lần
    → chuyển `rejected` (quy tắc 03). Mục không còn pending → ReviewAlreadyDecidedError.
    """
    if decision not in REVIEW_DECISIONS:
        raise ValueError(f"decision không hợp lệ: {decision}")
    with connect() as conn:
        review = conn.execute("SELECT * FROM review_queue WHERE id=?", (review_id,)).fetchone()
        if review is None:
            raise LookupError(f"review {review_id} không tồn tại")
        listing = conn.execute(
            "SELECT status, resubmit_count FROM listings WHERE id=?", (review["listing_id"],)
        ).fetchone()
        target = {"approved": "published", "rejected": "rejected", "needs_fix": "needs_fix"}[decision]
        final_decision = decision
        if decision == "needs_fix" and listing["resubmit_count"] >= MAX_RESUBMIT:
            target, final_decision = "rejected", "rejected"
            note = f"{note or ''} [tự từ chối: đã sửa {listing['resubmit_count']} lần]".strip()
        cur = conn.execute(
            "UPDATE review_queue SET status=?, reviewer=?, note=?, decided_at=? WHERE id=? AND status='pending'",
            (final_decision, reviewer, note, now_iso(), review_id),
        )
        if cur.rowcount != 1:
            raise ReviewAlreadyDecidedError(f"review {review_id} đã được quyết")
        if not _set_status(conn, review["listing_id"], "in_review", target):
            # Tin không ở in_review → huỷ cả transaction để review vẫn pending, dữ liệu nhất quán.
            raise InvalidTransitionError(
                f"listing {review['listing_id']} đang {listing['status']}, không phải in_review"
            )
        conn.execute(
            "INSERT INTO audit_log(listing_id, action, detail, created_at) VALUES(?,?,?,?)",
            (review["listing_id"], f"review_{final_decision}", f"review={review_id} by={reviewer}", now_iso()),
        )
    return target


# ---------------------------------------------------------------- search
def search_candidates(limit: int = 200) -> list[dict[str, Any]]:
    """Tin đã đăng (mới nhất trước) để services/search lọc/xếp hạng trong Python."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT l.id, l.title, l.description, l.category, l.condition, l.price_vnd, l.image_ref, "
            "l.published_at, u.display_name AS seller_name, u.zalo_user_id AS seller_zalo_id "
            "FROM listings l JOIN users u ON u.id = l.seller_id "
            "WHERE l.status='published' ORDER BY l.published_at DESC, l.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- lệnh người dùng (08)
def get_user_by_zalo(zalo_user_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        return _row(conn.execute("SELECT * FROM users WHERE zalo_user_id=?", (zalo_user_id,)).fetchone())


def list_listings_by_seller(seller_id: int, limit: int = 20) -> list[dict[str, Any]]:
    """Tin của một người bán, mới nhất trước (cho /tincuatoi)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, title, status, price_vnd, updated_at FROM listings WHERE seller_id=? ORDER BY id DESC LIMIT ?",
            (seller_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def pending_review_for_listing(listing_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        return _row(
            conn.execute(
                "SELECT * FROM review_queue WHERE listing_id=? AND status='pending' ORDER BY id DESC LIMIT 1",
                (listing_id,),
            ).fetchone()
        )


# ---------------------------------------------------------------- chuyển tin /hoi /tl
def get_or_create_thread(listing_id: int, buyer_id: int) -> dict[str, Any]:
    """Luồng hỏi đáp của một người mua với một tin; tạo nếu chưa có, cập nhật last_at."""
    ts = now_iso()
    with connect() as conn:
        conn.execute(
            "INSERT INTO relay_threads(listing_id, buyer_id, created_at, last_at) VALUES(?,?,?,?) "
            "ON CONFLICT(listing_id, buyer_id) DO UPDATE SET last_at=excluded.last_at",
            (listing_id, buyer_id, ts, ts),
        )
        row = conn.execute(
            "SELECT * FROM relay_threads WHERE listing_id=? AND buyer_id=?", (listing_id, buyer_id)
        ).fetchone()
    return dict(row)


def get_thread(thread_id: int) -> dict[str, Any] | None:
    """Luồng kèm người bán (qua listing) và zalo id người mua."""
    with connect() as conn:
        return _row(
            conn.execute(
                "SELECT t.*, l.seller_id, l.title, ub.zalo_user_id AS buyer_zalo_id "
                "FROM relay_threads t JOIN listings l ON l.id=t.listing_id JOIN users ub ON ub.id=t.buyer_id "
                "WHERE t.id=?",
                (thread_id,),
            ).fetchone()
        )


def touch_thread(thread_id: int) -> None:
    with connect() as conn:
        conn.execute("UPDATE relay_threads SET last_at=? WHERE id=?", (now_iso(), thread_id))
