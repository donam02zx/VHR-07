# 04 — Hợp đồng với phần AI (3 bạn AI)

SW không viết logic mô hình. SW chỉ gọi 4 hàm dưới đây qua `src/services/ai.py`.

## Chữ ký (cố định, không đổi nếu chưa thống nhất cả nhóm)
```python
# src/services/ai.py  — điểm duy nhất SW import
from src.services.ai_stub import draft_listing, suggest_price, moderate, search_semantic
# Khi AI có bản thật: đổi dòng import trên sang module thật. KHÔNG sửa nơi gọi.

def draft_listing(image: bytes | None, caption: str) -> dict:
    # {"title": str, "description": str, "category": str, "condition": str}

def suggest_price(listing: dict) -> dict:
    # {"low": int, "high": int, "rationale": str}      đơn vị VND

def moderate(listing: dict) -> dict:
    # {"score": float 0..1, "layers": {"rule": float, "model": float, ...}, "reason": str}
    # score cao = nghi ngờ cao

def search_semantic(query: str, k: int = 5) -> list[int]:
    # danh sách listing_id đã đăng, xếp theo độ liên quan
```
Tất cả đồng bộ (sync) và PHẢI trả đúng dạng trên. Gọi từ code async bằng `asyncio.to_thread(...)`.

## Bản giả `ai_stub.py` (SW viết, hành vi xác định để demo ổn định)
- `draft_listing`: dựa vào `caption` — có "xe đạp" → title "Xe đạp thể thao đã qua sử dụng", category "Thể thao", condition "Cũ 80%"; không có thì title = 60 ký tự đầu caption.
- `suggest_price`: theo `category` (bảng cố định nhỏ), ví dụ Thể thao 800000–1500000.
- `moderate`: caption/title chứa từ khoá lừa đảo ("chuyển khoản trước", "cọc trước", "đặt cọc") → score 0.55;
  chứa hàng cấm ("thuốc lá điện tử", "vũ khí", "pháo") → 0.9; còn lại 0.1. `reason` nêu từ khoá khớp.
- `search_semantic`: trả `[]` (SW dùng `LIKE`, xem 08).
Danh sách từ khoá để trong một hằng số ở đầu file, dễ sửa.

## Xử lý lỗi từ hàm AI (bắt buộc)
- Hàm AI ném lỗi hoặc quá 20 giây → coi là sự cố AI: tin chuyển `in_review` với reason `ai_unavailable`,
  người bán được báo "đang chờ người duyệt". KHÔNG đăng tự động khi AI lỗi. Ghi `audit_log`.
- Kết quả sai dạng (thiếu khoá, score ngoài 0..1) → xử lý như lỗi ở trên, KHÔNG sửa khéo cho qua.
- Đặt timeout bằng `asyncio.wait_for`.

## Với bạn AI
Khi thay bản thật: giữ nguyên chữ ký, có docstring, có test trong `tests/` của bạn.
Prompt để ở `prompts/*.md`, không nhúng chuỗi dài trong Python (quy ước repo).
