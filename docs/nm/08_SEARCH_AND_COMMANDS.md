# 08 — Lệnh người dùng và tìm kiếm

## Câu tự nhiên, không cần "/" (`services/intent.py`, luật từ khoá — không dùng LLM)
| Ví dụ | Hiểu là |
|---|---|
| "tôi muốn tìm laptop", "có ai bán xe đạp không", "cần mua tủ lạnh", "laptop" | tìm (bỏ từ đệm → `search`) |
| "tôi muốn bán laptop dell", "cần thanh lý tủ lạnh", "Bán xe đạp" | muốn bán → hướng dẫn gửi ẢNH kèm mô tả, giá |
| "xem tin 13", "#13" / "hỏi 13 còn không bạn?" | như `/xem 13` / `/hoi 13 ...` |
| "tin của tôi" / "hướng dẫn" / "xin chào" / "cảm ơn" | `/tincuatoi` / `/help` / lời chào / đáp lễ |
Câu không có từ khoá ý định nhưng có từ có nghĩa → coi là tìm kiếm (khi KHÔNG đang có bản nháp).
Bỏ dấu thì "bán/bạn/bàn" trùng nhau → luật mơ hồ kiểm trên chữ có dấu. Lệnh "/" vẫn dùng được như cũ.

## Lệnh (không phân biệt hoa thường, bỏ dấu cách thừa)
| Lệnh | Việc |
|---|---|
| `/help` | liệt kê lệnh và cách đăng tin |
| `/tim <từ khoá>` | tìm tin đã đăng, tối đa 5 kết quả |
| `/tincuatoi` | liệt kê tin của chính mình kèm trạng thái |
| `/rut <id>` | rút tin của mình (kiểm tra đúng chủ) → `withdrawn` |
| `/duyet <id>`, `/tuchoi <id> <lý do>` | chỉ moderator (dự phòng, xem 07) |
| `/xem <id>` | ảnh (nếu có, `sendPhoto`) + bản công khai đã che SĐT |
| `/hoi <id> <câu hỏi>` | người mua hỏi người bán qua bot; bot gửi người bán "Có người hỏi tin #id — mã hỏi N" |
| `/tl <mã hỏi> <trả lời>` | chỉ người bán của tin; bot chuyển về đúng người mua của luồng đó |

### Chuyển tin ẩn danh (`/hoi` – `/tl`)
Cả hai bên chỉ thấy bot: không có tên thật, Zalo ID hay SĐT (nội dung chuyển đi qua `mask_phone`).
DB chỉ lưu luồng (`relay_threads`), không lưu nội dung. Người mua chỉ thấy "đã chuyển" khi gửi tới người bán thành công;
người bán chưa từng nhắn bot thì Zalo không gửi được (05) → người mua được báo "chưa gửi được".
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
