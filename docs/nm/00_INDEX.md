# NeighborMarket — INDEX (đọc file này đầu tiên)

> Bộ tài liệu cho Claude Code. Mỗi file ngắn, chỉ nói MỘT chủ đề.
> **Quy tắc chống quên: KHÔNG đọc hết. Đọc file 00, 01, 09 một lần, rồi chỉ đọc file mà task hiện tại trỏ tới.**

## Dự án trong 3 dòng
Bot Zalo cho cư dân chung cư: gửi ảnh → bot soạn tin + gợi ý giá → qua kiểm duyệt (tự động + người duyệt) → đăng; cư dân tìm bằng `/tim`.
Repo là boilerplate FastAPI + LangGraph. Ta THÊM code vào `src/`, không viết lại repo.
Deadline: demo 5 phút vào chủ nhật 2026-11-15. **Ưu tiên chạy được end-to-end hơn là đầy đủ.**

## Bản đồ file

| File | Nội dung | Đọc khi |
|---|---|---|
| 01_PRODUCT_AND_SCOPE.md | Làm gì / không làm gì | Bắt đầu, và khi phân vân phạm vi |
| 02_ARCHITECTURE_AND_FOLDERS.md | Thư mục, ai sở hữu, file cấm sửa | Tạo file mới |
| 03_DATA_MODEL.md | Bảng SQLite, trạng thái tin | Đụng DB |
| 04_AI_CONTRACT.md | 4 hàm AI + bản giả (stub) | Gọi hoặc viết hàm AI |
| 05_ZALO_CHANNEL.md | Sự thật về Zalo Bot API, phần chưa kiểm chứng | Đụng kênh Zalo |
| 06_FLOW_POSTING.md | Máy trạng thái đăng tin | Luồng đăng tin |
| 07_MODERATION_HITL.md | Ngưỡng điểm, hàng chờ duyệt, API duyệt | Kiểm duyệt / trang duyệt |
| 08_SEARCH_AND_COMMANDS.md | Lệnh người dùng, tìm kiếm | Lệnh / tìm kiếm |
| 09_CODING_RULES.md | Quy ước code, test, lint, log | LUÔN đọc một lần đầu |
| 10_TASKS.md | Danh sách task có thứ tự + tiêu chí xong | Chọn việc kế tiếp |
| 11_DEMO_SCRIPT.md | Kịch bản demo 5 phút + dữ liệu mẫu | Cuối, chuẩn bị demo |
| 12_DEFER_LATER.md | Việc cố ý hoãn | Khi muốn "làm cho tốt hơn" |

## Quy trình mỗi lượt làm việc
1. Mở `10_TASKS.md`, lấy task đầu tiên chưa tick.
2. Đọc ĐÚNG các file mà task đó ghi ở dòng `Đọc:`.
3. Làm, chạy `make lint` và `pytest`, tick task, thêm 1 dòng vào `WORKLOG.md`.
4. Dừng và báo cáo ngắn. Không làm task kế tiếp nếu người dùng chưa bảo.
5. Gặp điều không rõ → ghi vào mục "Câu hỏi mở" cuối `10_TASKS.md` rồi hỏi người dùng. Không đoán cho Zalo (xem 05).
