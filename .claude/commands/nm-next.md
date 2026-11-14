---
description: Làm task NeighborMarket kế tiếp theo docs/nm/10_TASKS.md
---
Làm theo đúng quy trình sau, không bỏ bước:

1. Đọc `docs/nm/00_INDEX.md` (chỉ mục) và `docs/nm/09_CODING_RULES.md` nếu chưa đọc trong phiên này.
2. Mở `docs/nm/10_TASKS.md`, chọn task đầu tiên chưa tick (hoặc task `$ARGUMENTS` nếu có).
3. Chỉ đọc các file ghi ở dòng `Đọc:` của task đó. Không đọc file khác trong `docs/nm/`.
4. Nếu task cần dữ liệu mà chưa có (ví dụ file mẫu Zalo ở T05) → dừng và hỏi người dùng.
5. Viết code và test theo `Làm:` / `Xong khi:`. Chạy `make lint` và `pytest`; sửa đến khi xanh.
6. Tick task trong `10_TASKS.md`, thêm 1 dòng vào `WORKLOG.md`, commit nhỏ `feat(nm): ...`.
7. Báo cáo ≤ 8 dòng: đã làm gì, test nào chạy, điều chưa chắc. Dừng, không tự làm task kế tiếp.
