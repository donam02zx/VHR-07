# 09 — Quy ước code (đọc một lần đầu)

## Môi trường
Python 3.11+ (ruff target py311). Chạy: `make run`. Test: `make test` (pytest, `asyncio_mode=auto`). Lint: `make lint` (ruff, line 120).
Không thêm thư viện mới nếu không bắt buộc. Cần thêm → ghi vào `requirements.txt` và nói rõ lý do trong báo cáo.

## Phong cách
- Type hint đầy đủ cho hàm công khai. Docstring tiếng Việt, ngắn, nêu *vì sao* (repo dùng style này).
- Hàm nhỏ, thuần khi có thể (`route`, `parse_vnd`, `mask_phone`, `parse_update`) để test dễ.
- Cấu hình qua `get_settings()` (`src/config.py`). Không `os.getenv` rải rác, không hard-code token/ngưỡng.
- Async cho I/O mạng. SQLite là sync: gọi từ async bằng `asyncio.to_thread` hoặc giữ truy vấn rất ngắn.

## Xử lý lỗi (quan trọng)
- **Không nuốt lỗi im lặng.** Bắt lỗi thì phải log (`logging.getLogger("nm.<module>")`, kèm id liên quan) và có hành vi rõ ràng.
- **Không fallback ngầm.** Dữ liệu sai dạng → lỗi tường minh hoặc đưa người duyệt, không "sửa cho qua".
- Không log token, nội dung tin nhắn đầy đủ của người dùng, hay SĐT thật.
- Lỗi một tin nhắn không được làm chết poller.

## Test (mỗi task phải có)
- Đặt trong `tests/test_nm/`, dùng DB SQLite tạm (`tmp_path`), kênh giả (`CHANNEL_MODE=sim`), AI giả (stub). KHÔNG gọi mạng/Zalo/OpenAI thật trong test.
- Test hàm thuần theo bảng (nhiều ví dụ), test biên của ngưỡng, test chuyển trạng thái sai bị từ chối.
- Chạy cả bộ test cũ của repo; không làm hỏng chúng.

## Quy tắc của repo (không phá)
- Hook log trong `.claude/` tự ghi prompt vào `.ai-log/`: KHÔNG tắt, KHÔNG dùng `--no-verify`.
- Prompt dài ở `prompts/*.md`, không nhúng trong Python.
- `scripts/check_docs.py` kiểm link tương đối trong `docs/guide/`; tài liệu của ta ở `docs/nm/` (không bị quét) nhưng vẫn giữ link đúng.
- Khi code và tài liệu mâu thuẫn: **code thắng**, rồi sửa tài liệu.
- Sau mỗi task: thêm 1 dòng vào `WORKLOG.md` (ai/việc/trạng thái/thời gian).

## Git
Một task = một commit nhỏ, thông điệp dạng `feat(nm): <việc>` hoặc `test(nm): ...`. Không commit `.env`, `data/*.db`, ảnh tải về.
