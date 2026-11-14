# 11 — Kịch bản demo 5 phút và dữ liệu mẫu

## Chuẩn bị
- Chạy `python scripts/seed.py` (8–10 tin đã đăng, gồm 2 tin "xe đạp", 1 "tủ lạnh", 1 "bàn học", 1 "nồi chiên không dầu").
- 2 tài khoản Zalo: người bán A (resident), người duyệt B (moderator, đặt role trong DB bằng `scripts/seed.py --moderator <zalo_user_id>`).
- 3 ảnh: xe đạp, một ảnh dùng cho tin vi phạm, một ảnh cho tin ở ngưỡng giữa. Quay sẵn video dự phòng.
- Mở sẵn `/console` trên trình duyệt (nhập `CONSOLE_TOKEN`).

## 4 cảnh
1. **Đăng tin thuận lợi (1,5 phút).** A gửi ảnh xe đạp, chú thích "Xe đạp thể thao còn mới". Bot trả bản nháp + giá gợi ý. A: `sửa giá 1tr2`, rồi `ok`. Bot: "Tin #… đã được đăng."
2. **Tin bị từ chối tự động (1 phút).** A gửi tin chú thích có từ hàng cấm. Bot từ chối kèm lý do ngắn.
3. **Tin vào hàng chờ và người duyệt (1,5 phút).** A gửi tin có "chuyển khoản trước/đặt cọc". Bot: "đang chờ người duyệt". Mở `/console`: thấy tin, điểm, lý do → bấm Duyệt. A nhận thông báo đã đăng.
4. **Tìm kiếm (1 phút).** `/tim xe dap` → danh sách; số điện thoại trong mô tả hiển thị đã che.

## Lời giải thích kèm theo (3 câu)
Bot là cổng đăng tin duy nhất; DB là nguồn sự thật; chưa chắc chắn thì đưa người duyệt, không tự chặn.
Các phần AI hiện dùng bản giả hay bản thật → nói rõ từng phần.
Phần hoãn lại (chống race, cache, tenant) nêu trong 12.

## Phương án khi sự cố
Zalo lỗi → chạy `scripts/simulate.py` (chế độ sim) và nói rõ. Bot không vào được nhóm → demo 1:1.
