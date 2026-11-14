# 12 — Việc cố ý hoãn (đừng làm trước buổi demo)

Nếu thấy muốn "làm cho tốt hơn", hãy nhìn danh sách này trước. Chỉ làm khi người dùng yêu cầu rõ.

| Việc hoãn | Vì sao hoãn | Bản tối thiểu hiện có |
|---|---|---|
| Hàng đợi việc nền (`jobs`, claim/lease/retry) | demo ít tải | xử lý trực tiếp trong handler, timeout cho AI |
| Khoá lạc quan/bi quan, tăng `version` | một người dùng một lúc | `UPDATE ... WHERE status=?` ở `set_status` |
| Circuit breaker, rate limit, cache theo hash | chưa có tải | timeout + lỗi AI → `in_review` |
| Postgres/Supabase, RLS, tenant theo hộ dân | demo một nhóm | SQLite |
| Webhook Zalo, HTTPS, deploy | cần domain | long-polling |
| Chat ẩn danh qua bot (relay, alias) | tốn thời gian | chỉ nói trong phần phát triển tiếp |
| Tìm kiếm ngữ nghĩa, Qdrant/Chroma | phụ thuộc AI | `LIKE` không dấu |
| Next.js, đăng nhập | demo bằng bot | `static/console.html` + token cứng |
| Eval precision/recall, dashboard | phần nâng cao | bạn AI làm riêng |
| Xoá tin nhắn trên Zalo | chưa kiểm chứng API | DB gỡ tin + bot nhắn "đã gỡ" |
