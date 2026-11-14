# 03 — Mô hình dữ liệu (SQLite)

Mọi truy vấn nằm trong `src/services/db.py`. Dùng tham số `?`, không nối chuỗi SQL.
Mỗi thao tác ghi dùng một transaction ngắn. Bật `PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;`.

## Bảng
```sql
users(
  id INTEGER PRIMARY KEY,
  zalo_user_id TEXT UNIQUE NOT NULL,
  display_name TEXT,
  role TEXT NOT NULL DEFAULT 'resident',      -- resident | moderator
  created_at TEXT NOT NULL
);

listings(
  id INTEGER PRIMARY KEY,
  seller_id INTEGER NOT NULL REFERENCES users(id),
  title TEXT, description TEXT, category TEXT, condition TEXT,
  price_vnd INTEGER,                          -- giá người bán chốt
  price_low INTEGER, price_high INTEGER,      -- gợi ý giá
  image_ref TEXT,                             -- đường dẫn/URL ảnh
  status TEXT NOT NULL,                       -- xem bên dưới
  moderation_score REAL, moderation_reason TEXT,
  resubmit_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, published_at TEXT
);

conversations(                                 -- trạng thái hội thoại theo chat
  chat_id TEXT PRIMARY KEY,
  state TEXT NOT NULL DEFAULT 'idle',          -- idle | awaiting_confirm | awaiting_edit
  listing_id INTEGER REFERENCES listings(id),
  updated_at TEXT NOT NULL
);

review_queue(
  id INTEGER PRIMARY KEY,
  listing_id INTEGER NOT NULL REFERENCES listings(id),
  reason TEXT, score REAL,
  status TEXT NOT NULL DEFAULT 'pending',      -- pending | approved | rejected | needs_fix
  reviewer TEXT, note TEXT,
  created_at TEXT NOT NULL, decided_at TEXT
);

processed_events(event_key TEXT PRIMARY KEY, created_at TEXT NOT NULL);  -- chống xử lý trùng

audit_log(id INTEGER PRIMARY KEY, listing_id INTEGER, action TEXT, detail TEXT, created_at TEXT NOT NULL);

watches(                                       -- săn tin: bot tự nhắn khi có tin mới khớp (08)
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
  query TEXT NOT NULL, min_price INTEGER, max_price INTEGER,
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);

relay_threads(                                 -- chuyển tin ẩn danh /hoi – /tl (08)
  id INTEGER PRIMARY KEY,                      -- "mã hỏi" người bán dùng với /tl
  listing_id INTEGER NOT NULL REFERENCES listings(id),
  buyer_id INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL, last_at TEXT NOT NULL,
  UNIQUE(listing_id, buyer_id)                 -- mỗi người mua một luồng mỗi tin; KHÔNG lưu nội dung tin nhắn
);
```

## Trạng thái `listings.status` và chuyển hợp lệ
```
draft ─► awaiting_confirm ─► pending_moderation ─┬─► published
   │            │                                ├─► in_review ─┬─► published
   └─► withdrawn└─► withdrawn                    │              ├─► rejected
                                                 │              └─► needs_fix ─► awaiting_confirm
                                                 └─► rejected
published ─► withdrawn
```
- Chỉ cho phép các chuyển trên; hàm `set_status(listing_id, from_status, to_status)` dùng
  `UPDATE ... WHERE id=? AND status=?` và trả `False` nếu không khớp (chống chuyển sai/trùng).
- `needs_fix` tăng `resubmit_count`; tối đa 3, quá thì chuyển `rejected`.

## Quy ước
- Thời gian: ISO 8601 UTC, tạo bằng `datetime.now(timezone.utc).isoformat()`.
- Hàm `init_db()` idempotent, gọi trong `lifespan`. Có `reset_for_tests(path)` cho test (DB tạm).
- Dữ liệu mẫu ở `scripts/seed.py`, chạy lặp lại không nhân đôi.
