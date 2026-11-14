# Worklog — Team [Tên Team]

> Ghi lại tất cả công việc đã làm theo ngày. Ai làm gì, kết quả gì.

---

## [YYYY-MM-DD]

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Tên] | [mô tả task] | ✅ Done | [link/kết quả] | 2h |
| [Tên] | [mô tả task] | 🔄 WIP | [mô tả tiến độ] | 1.5h |
| [Tên] | [mô tả task] | ❌ Blocked | [lý do block] | - |

**Tổng kết ngày:** [1-2 câu về tiến độ chung]

---

## [YYYY-MM-DD]

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| | | | | |

**Tổng kết ngày:**

---

<!-- Format: copy block trên cho mỗi ngày làm việc -->

## 2026-11-14

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Claude Code | NM T01 — cấu hình Settings + .env.example + khung thư mục | ✅ Done | src/config.py, tests/test_nm/test_config_nm.py | 0.3h |
| Claude Code | NM T02 — services/db.py: schema SQLite, máy trạng thái, hàng chờ duyệt | ✅ Done | src/services/db.py, tests/test_nm/test_db.py (30 test) | 0.5h |
| Claude Code | NM T03 — parse_vnd, mask_phone, strip_accents | ✅ Done | src/services/{vnd,pii,text}.py, tests/test_nm/test_utils.py (62 test) | 0.4h |
| Claude Code | NM T04 — AI stub + điểm import ai.py | ✅ Done | src/services/{ai_stub,ai}.py, tests/test_nm/test_ai_stub.py (11 test) | 0.3h |
| Claude Code | NM T05 — Zalo client + sim, parse_update theo mẫu thật; cập nhật 05 mục ĐÃ KIỂM CHỨNG | ✅ Done | src/channels/zalo.py, tests/test_nm/test_zalo.py (34 test) | 0.6h |
| Claude Code | NM T06 — luồng đăng tin + dispatcher + safe_ai (timeout/kiểm dạng) + moderation tạm | ✅ Done | src/services/{posting,dispatcher,safe_ai,moderation}.py, tests/test_nm/test_posting.py (30 test) | 0.8h |
| Claude Code | NM T07 — kiểm duyệt: luật cứng + điểm AI + route theo ngưỡng + AI lỗi → in_review | ✅ Done | src/services/moderation.py, tests/test_nm/test_moderation.py (41 test) | 0.6h |
| Claude Code | NM T08 — API duyệt (token, 401/404/409), /console, nhắn người bán sau duyệt | ✅ Done | src/api/reviews.py, src/static/console.html, src/main.py, tests/test_nm/test_reviews_api.py (16 test) | 0.7h |
| Claude Code | NM T09 — poller getUpdates (chống trùng, backoff, handler lỗi không dừng) + nối lifespan | ✅ Done | src/channels/poller.py, src/main.py, tests/test_nm/test_poller.py (12 test) | 0.4h |
| Claude Code | NM T10 — /help /tim /tincuatoi /rut /duyet /tuchoi + search bỏ dấu; tách reviewflow dùng chung | ✅ Done | src/services/{commands,search,reviewflow}.py, tests/test_nm/test_commands.py (24 test) | 0.7h |
| Claude Code | NM T11 — seed.py (10 tin, --moderator) + simulate.py (4 cảnh demo, sim) + /xem | ✅ Done | scripts/{seed,simulate}.py, tests/test_nm/test_simulate.py; simulate.py: TẤT CẢ 4 CẢNH ĐÚNG | 0.8h |
| Claude Code | NM T12a — chuyển tin ẩn danh /hoi–/tl, /xem kèm ảnh (sendPhoto kiểm chứng thật), log tin đến | ✅ Done | src/services/{commands,dispatcher}.py, db relay_threads, tests/test_nm/test_relay.py (18 test) | 0.8h |
| Claude Code | NM T12b — nhắn tự nhiên không cần "/" (tìm/bán/xem/hỏi; nháp: oke/thôi/giá 1tr2) | ✅ Done | src/services/intent.py, commands.handle_natural, tests/test_nm/test_intent.py (56 test) | 0.8h |
| Claude Code | NM T12c — AI thật Gemini (4 hàm) + agent gọi công cụ (HITL, quay về luật) + săn tin + lọc giá | ✅ Done | src/services/{ai_gemini,agent,watches,nm_llm}.py, prompts/nm_*.md, 45 test; thử thật với gemini-3.5-flash-lite: ảnh → tin đúng, agent tìm/hỏi/săn đúng | 2h |

