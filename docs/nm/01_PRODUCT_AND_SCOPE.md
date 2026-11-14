# 01 — Sản phẩm và phạm vi

## Bài toán
Nhóm mua bán của cư dân trên Zalo lộn xộn: khó tìm, nhiều tin rác/lừa đảo, không kiểm duyệt.
Giải pháp: một bot Zalo (Zalo Bot Platform, KHÔNG phải Official Account) làm cổng duy nhất để đăng tin.

## Vai trò
- **resident**: gửi ảnh để đăng, tìm tin, rút tin của mình.
- **moderator**: duyệt tin bị gắn cờ (qua trang web hoặc lệnh Zalo).
- Hệ thống: tự soạn tin, gợi ý giá, kiểm duyệt tự động.

## TRONG phạm vi (demo)
1. Bot nhận ảnh + chú thích từ người dùng (ưu tiên chat riêng 1:1).
2. Soạn bản nháp + gợi ý giá, người bán trả lời `ok` / sửa / huỷ.
3. Kiểm duyệt: luật (từ khoá, SĐT, link) + điểm từ hàm AI → 3 nhánh đăng / chờ duyệt / từ chối.
4. Hàng chờ duyệt + trang web duyệt rất đơn giản.
5. `/tim <từ khoá>` trả tối đa 5 tin đã đăng.
6. Che số điện thoại trong nội dung đăng.

## NGOÀI phạm vi (không làm, kể cả khi thấy hay)
Chat ẩn danh qua bot, tenant/hộ dân, đăng nhập Supabase, Next.js, Qdrant/embedding thật, eval precision/recall, dashboard,
chống race nâng cao, circuit breaker, rate limit, deploy. Xem `12_DEFER_LATER.md`.

## Tiêu chí thành công
Chạy trọn kịch bản `11_DEMO_SCRIPT.md` hai lần liên tiếp không lỗi.

## Nguyên tắc sản phẩm
- Bot là cổng đăng tin duy nhất; DB là nguồn sự thật (không phụ thuộc việc xoá tin nhắn trên Zalo).
- Chưa chắc chắn thì đưa người duyệt xem, không tự chặn (tránh chặn nhầm).
- Tin nhắn Zalo tối đa 2000 ký tự, không markdown.
