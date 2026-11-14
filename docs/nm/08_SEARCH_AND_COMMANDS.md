# 08 — Lệnh người dùng và tìm kiếm

## Lệnh (không phân biệt hoa thường, bỏ dấu cách thừa)
| Lệnh | Việc |
|---|---|
| `/help` | liệt kê lệnh và cách đăng tin |
| `/tim <từ khoá>` | tìm tin đã đăng, tối đa 5 kết quả |
| `/tincuatoi` | liệt kê tin của chính mình kèm trạng thái |
| `/rut <id>` | rút tin của mình (kiểm tra đúng chủ) → `withdrawn` |
| `/duyet <id>`, `/tuchoi <id> <lý do>` | chỉ moderator (dự phòng, xem 07) |
Lệnh lạ → trả `/help` ngắn. Người dùng chưa có trong `users` → tạo tự động (role resident).

## Tìm kiếm (`services/search.py`)
- Giai đoạn 1 (làm): chuẩn hoá chữ thường, bỏ dấu tiếng Việt (`unicodedata`), tách từ; tin phải ở `published`; khớp `LIKE` trên title+description đã bỏ dấu; xếp theo số từ khớp rồi mới nhất.
  Lưu thêm cột/chỉ mục bỏ dấu hoặc tính khi truy vấn (chọn cách đơn giản nhất, dữ liệu demo nhỏ).
- Giai đoạn 2 (chỉ khi AI sẵn sàng): `search_semantic(query)` trả id; hợp nhất với kết quả Giai đoạn 1, bỏ trùng.
- Không có kết quả → "Chưa có tin phù hợp".

## Định dạng kết quả (text thuần)
```
Tìm thấy 2 tin:
#23 Xe đạp thể thao đã qua sử dụng — 1.200.000 đ
#31 Xe đạp trẻ em — 450.000 đ
Nhắn "/xem 23" để xem chi tiết.
```
(`/xem <id>` là tuỳ chọn, chỉ làm nếu còn thời gian; SĐT luôn bị che.)

## Che thông tin liên hệ (`services/pii.py`)
`mask_phone(text)`: số VN (`0xxxxxxxxx`, `+84...`, có dấu cách/chấm/gạch) → `09xx xxx xxx` dạng che giữa. Có test nhiều dạng.
Nội dung đăng công khai KHÔNG chứa tên thật/ID người bán.
