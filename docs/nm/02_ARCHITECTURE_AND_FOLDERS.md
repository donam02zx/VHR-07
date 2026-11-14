# 02 — Kiến trúc và thư mục

## Luồng tổng quát
```
Zalo ──getUpdates──► channels/poller ──► services/dispatcher
                                            ├─ services/posting      (luồng đăng tin)
                                            ├─ services/search       (/tim)
                                            └─ services/commands     (/help, /rut ...)
posting ─► services/ai_stub (hoặc AI thật) ─► services/moderation ─► db
api/reviews + static/console.html  ◄── người duyệt ──► db ──► channels/zalo (nhắn kết quả)
```
Một process FastAPI. Poller chạy trong `lifespan` của `src/main.py`. DB: SQLite file `data/app.db`.

## Thư mục MỚI (SW sở hữu) — tạo đúng tên này
```
src/channels/__init__.py
src/channels/zalo.py          # client HTTP tới Zalo Bot API (xem 05)
src/channels/poller.py        # vòng lặp getUpdates
src/services/db.py            # kết nối SQLite + schema + hàm truy vấn (xem 03)
src/services/dispatcher.py    # phân loại tin đến → handler
src/services/posting.py       # máy trạng thái đăng tin (xem 06)
src/services/moderation.py    # luật + định tuyến theo điểm (xem 07)
src/services/search.py        # tìm kiếm (xem 08)
src/services/pii.py           # che SĐT
src/services/vnd.py           # parse_vnd: "1tr2" → 1200000
src/services/ai_stub.py       # bản giả 4 hàm AI (xem 04)
src/api/reviews.py            # endpoint duyệt tay
src/static/console.html       # trang duyệt
scripts/seed.py               # dữ liệu mẫu
tests/test_nm/                # test của phần này
```

## Thư mục của bạn AI (KHÔNG sửa trừ khi người dùng bảo)
`src/agents/**`, `src/services/ai_*.py` ngoại trừ `ai_stub.py`, `prompts/**`, `eval/**`.
Hàm AI thật sẽ thay stub bằng đổi MỘT dòng import trong `src/services/ai.py` (xem 04).

## File gốc của repo: sửa tối thiểu
- `src/main.py`: chỉ thêm router `reviews`, mount `static/`, khởi động/dừng poller trong `lifespan`.
- `src/config.py`: chỉ THÊM trường (token Zalo, ngưỡng, id nhóm, token trang duyệt).
- `.env.example`: thêm biến mới tương ứng.
- KHÔNG sửa: `src/agents/graph.py`, `state.py`, `guardrails.py`, `scripts/log_hook.py`, `.claude/settings.json`, `.github/**`.

## Quyết định đã chốt (không bàn lại)
- Không dùng ReAct graph cho luồng đăng tin: pipeline thẳng, trạng thái lưu SQLite.
- SQLite + module `sqlite3` chuẩn, KHÔNG SQLAlchemy (không thêm phụ thuộc).
- Poller dùng long-polling `getUpdates`, không webhook (không cần URL công khai).
