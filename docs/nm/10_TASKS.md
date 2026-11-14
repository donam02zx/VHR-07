# 10 — Danh sách task (làm tuần tự, tick khi xong)

Quy ước: mỗi task độc lập, có `Đọc:` (file cần đọc, KHÔNG đọc thêm), `Làm:`, `Xong khi:`.
Giữ nguyên số thứ tự. Mỗi lượt chỉ làm MỘT task rồi báo cáo.

- [x] **T01 — Cấu hình và khung** — Đọc: 02, 09
  Làm: thêm vào `Settings`: `zalo_bot_token`, `channel_mode` ("sim"|"zalo", mặc định "sim"), `zalo_group_chat_id` (rỗng), `mod_publish_below=0.3`, `mod_reject_from=0.8`, `console_token`, `nm_db_path="data/app.db"`. Cập nhật `.env.example`. Tạo thư mục và `__init__.py` theo 02.
  Xong khi: `make lint` và `pytest` xanh; `from src.config import get_settings` đọc được trường mới.

- [ ] **T02 — Cơ sở dữ liệu** — Đọc: 03, 09
  Làm: `services/db.py` đủ bảng + `init_db()` + hàm: `upsert_user`, `create_listing`, `get_listing`, `set_status(from,to)`, `update_listing_fields`, conversation get/set, `try_mark_event(event_key)->bool`, `add_audit`, review queue (create/list/decide), `search_candidates`.
  Xong khi: test tạo tin, chuyển trạng thái hợp lệ OK / sai bị từ chối, `try_mark_event` lần 2 trả False.

- [ ] **T03 — Tiện ích thuần** — Đọc: 06 (mục parse_vnd), 08 (mục che SĐT), 09
  Làm: `services/vnd.py` (`parse_vnd`), `services/pii.py` (`mask_phone`), hàm bỏ dấu tiếng Việt.
  Xong khi: test bảng ≥ 10 ví dụ mỗi hàm.

- [ ] **T04 — AI stub** — Đọc: 04, 09
  Làm: `services/ai_stub.py` và `services/ai.py` đúng 04.
  Xong khi: test hành vi xác định cho 3 chú thích mẫu (xe đạp, lừa đảo, hàng cấm).

- [ ] **T05 — Zalo client (CẦN MẪU THẬT)** — Đọc: 05, 09
  Điều kiện: có file trong `docs/nm/samples/`. **Không có → dừng, hỏi người dùng.**
  Làm: `channels/zalo.py` đúng giao diện 05, gồm chế độ `sim`. Test `parse_update` bằng file mẫu thật.
  Xong khi: test xanh; `send_text` cắt đúng 2000 ký tự (test); chế độ sim ghi lại tin gửi đi.

- [ ] **T06 — Luồng đăng tin** — Đọc: 06, 04, 03
  Làm: `services/posting.py` + `services/dispatcher.py` (phân loại ảnh/text/lệnh). Chưa gọi kiểm duyệt thật: sau `ok` gọi `moderation.process(listing_id)` (tạm là hàm trả "publish").
  Xong khi: test kịch bản giả: ảnh → nháp → `sửa giá 1tr2` → `ok`; `huy`; ảnh mới thay bản cũ.

- [ ] **T07 — Kiểm duyệt** — Đọc: 07, 04
  Làm: `services/moderation.py`: luật cứng, `route()`, `process()` nối trạng thái, xử lý lỗi/timeout AI.
  Xong khi: test 3 nhánh + biên 0.29/0.3/0.79/0.8 + AI ném lỗi → `in_review` `ai_unavailable`.

- [ ] **T08 — API duyệt và trang duyệt** — Đọc: 07, 02
  Làm: `api/reviews.py`, đăng ký router + mount static trong `main.py`, `static/console.html`. Duyệt xong nhắn người bán qua kênh.
  Xong khi: test API (token sai → 401, quyết định hai lần → 409); mở `/console` thấy hàng chờ.

- [ ] **T09 — Poller và nối vào app** — Đọc: 05 (mục Poller), 02
  Làm: `channels/poller.py`, khởi động/dừng trong `lifespan` khi `channel_mode="zalo"`; chống trùng bằng `try_mark_event`.
  Xong khi: test với client giả: 3 update → 3 lần handler, update lặp bị bỏ qua, handler ném lỗi không dừng vòng lặp.

- [ ] **T10 — Lệnh và tìm kiếm** — Đọc: 08
  Làm: `services/commands.py`, `services/search.py`; nối vào dispatcher.
  Xong khi: test `/tim xe dap` (không dấu) ra tin "Xe đạp...", `/rut` sai chủ bị từ chối, SĐT trong kết quả đã che.

- [ ] **T11 — Dữ liệu mẫu và chạy thử toàn tuyến** — Đọc: 11
  Làm: `scripts/seed.py` (8–10 tin đã đăng), script `scripts/simulate.py` chạy kịch bản demo ở chế độ sim, in từng bước.
  Xong khi: chạy `simulate.py` ra đúng 4 cảnh trong 11.

- [ ] **T12 — Thử với Zalo thật** — Đọc: 05, 11
  Làm (người dùng cầm token): đặt `CHANNEL_MODE=zalo`, chạy, thử từng cảnh bằng điện thoại. Ghi lỗi/khác biệt vào "Câu hỏi mở" và sửa client.
  Xong khi: chạy trọn kịch bản trên Zalo thật 2 lần liên tiếp.

- [ ] **T13 — Dọn và tài liệu** — Đọc: 09
  Làm: cập nhật `PROJECT_CONTEXT.md`, `README.md` (cách chạy), `docs/architecture_diagram.md` (sơ đồ ở 02), `WORKLOG.md`. `make lint` và `pytest` xanh.

## Câu hỏi mở (ghi vào đây, đừng tự đoán)
- (trống) — repo: https://github.com/donam02zx/VHR-07
