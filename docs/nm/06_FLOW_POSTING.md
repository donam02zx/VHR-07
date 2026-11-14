# 06 — Luồng đăng tin (máy trạng thái hội thoại)

Trạng thái ở `conversations.state`. Cài trong `services/posting.py`. Handler nhận `Inbound` và trả về danh sách tin để gửi lại.

## Bảng chuyển
| Trạng thái | Sự kiện | Hành động | Trạng thái mới |
|---|---|---|---|
| idle | ảnh (±chú thích) | tải ảnh → `draft_listing` + `suggest_price` → tạo listing `awaiting_confirm` → gửi bản nháp | awaiting_confirm |
| idle | text thường | hiểu câu tự nhiên (08 — `services/intent.py`): tìm / muốn bán / xem / hỏi / chào | idle |
| awaiting_confirm | `ok`, `oke`, `đăng đi`, `ừ`, `đồng ý`... | listing → `pending_moderation` → chạy kiểm duyệt (07) → báo kết quả | idle |
| awaiting_confirm | `sửa giá`/`giá`/`đổi giá ...`, giá trần có đơn vị (`1tr2`), `sửa tiêu đề`/`đổi tên ...` | cập nhật giá/title → gửi bản nháp mới | awaiting_confirm |
| awaiting_confirm | `huy`, `hủy`, `thôi`, `bỏ`, `không đăng nữa` | listing → `withdrawn` | idle |
| awaiting_confirm | câu có ý định rõ (vd "tìm laptop") | làm việc đó + nhắc bản nháp còn chờ; câu mơ hồ → hướng dẫn trả lời bản nháp | awaiting_confirm |
| awaiting_confirm | ảnh mới | coi như huỷ bản cũ, tạo bản mới | awaiting_confirm |
| bất kỳ | lệnh `/...` | chuyển sang `commands` (08), không đổi trạng thái | giữ nguyên |

## Định dạng bản nháp (text thuần, < 2000 ký tự)
```
Bản nháp tin #23
Tiêu đề: Xe đạp thể thao đã qua sử dụng
Mô tả: ...
Tình trạng: Cũ 80%
Giá gợi ý: 800.000 – 1.500.000 đ
Trả lời: "ok" để đăng, "sửa giá 1tr2" để đổi, "huy" để bỏ.
```
- `sửa giá <số>`: dùng `parse_vnd` (xem dưới). `sửa tiêu đề <chuỗi>` cũng hỗ trợ. Không hiểu thì hỏi lại, không đoán.
- Nếu người bán chưa nêu giá, dùng điểm giữa của khoảng gợi ý làm `price_vnd` mặc định và nói rõ điều đó.

## `parse_vnd(s)` (đặt ở `services/vnd.py`)
Hiểu: `800k`, `800.000`, `800000đ`, `1tr`, `1tr2`, `1,5 triệu`, `1 triệu 5`. Trả `int | None`. Có test bảng nhiều ví dụ.

## Báo kết quả sau `ok`
- Đăng ngay: "Tin #23 đã được đăng."
- Vào hàng chờ: "Tin #23 đang chờ người duyệt, bạn sẽ được báo."
- Từ chối: "Tin #23 không được đăng: <reason> (ngắn gọn, lịch sự)."

## Đăng ở đâu
Nếu `ZALO_GROUP_CHAT_ID` có giá trị → `send_text` nội dung công khai (đã che SĐT, không có thông tin người bán) vào nhóm.
Không có (demo 1:1) → chỉ lưu `published` và gửi người bán xác nhận. DB luôn là nguồn sự thật.
