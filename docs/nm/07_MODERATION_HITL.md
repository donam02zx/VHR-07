# 07 — Kiểm duyệt và hàng chờ duyệt (HITL)

## Hai tầng trong `services/moderation.py`
1. **Luật cứng (SW viết, chạy trước, không cần AI):** từ khoá hàng cấm, SĐT lộ trong mô tả, link lạ, giá bất thường (≤ 0 hoặc > 1 tỷ).
   Khớp luật "cấm" → từ chối ngay, KHÔNG gọi AI. SĐT/link → không từ chối, nhưng ghi nhận và tăng điểm tối thiểu lên 0.3 (chuyển người duyệt).
2. **Điểm từ AI:** `moderate(listing)` (04). Điểm cuối = `max(điểm luật, điểm AI)`.

## Định tuyến theo điểm (ngưỡng đọc từ `Settings`, không hard-code)
| Điểm | Hành động | Trạng thái |
|---|---|---|
| `< 0.3` | đăng | published |
| `0.3` đến `< 0.8` | tạo dòng `review_queue(pending)` | in_review |
| `>= 0.8` | từ chối, lưu lý do | rejected |
Biến cấu hình: `MOD_PUBLISH_BELOW=0.3`, `MOD_REJECT_FROM=0.8`.
Hàm thuần `route(score) -> "publish"|"review"|"reject"` có test biên (0.29, 0.3, 0.79, 0.8).

## Xử lý lỗi AI
Theo `04`: lỗi/timeout/sai dạng → `in_review`, reason `ai_unavailable`. Không bao giờ tự đăng khi AI lỗi.

## API duyệt (`src/api/reviews.py`, prefix `/api/v1`)
Bảo vệ bằng header `X-Console-Token` so với `CONSOLE_TOKEN` trong `.env` (demo, không cần đăng nhập thật).
- `GET /reviews?status=pending` → `[{id, listing_id, title, description, price_vnd, image_ref, score, reason, created_at}]`
- `POST /reviews/{id}/decide` body `{"decision":"approve|reject|needs_fix","note":"..."}`
  - `approve` → listing `published` + (nếu có nhóm) đăng nhóm + nhắn người bán.
  - `reject` → listing `rejected` + nhắn lý do.
  - `needs_fix` → listing `needs_fix`, `resubmit_count += 1` (quá 3 → `rejected`), nhắn người bán sửa và gửi `ok` lại.
  - Quyết định hai lần cho cùng review → `409`. Dùng `UPDATE ... WHERE status='pending'` kiểm tra số dòng ảnh hưởng.
- Mọi quyết định ghi `audit_log`.

## Trang `static/console.html`
Một file HTML + JS thuần (không build, không framework). Ô nhập token → bảng tin chờ duyệt (ảnh, tiêu đề, điểm, lý do) → nút Duyệt / Từ chối / Cần sửa. Tự tải lại mỗi 5 giây. Phục vụ ở `/console`.

## Dự phòng nếu hết giờ
Lệnh Zalo cho moderator: `/duyet <id>`, `/tuchoi <id> <lý do>` (kiểm tra `users.role='moderator'`).
