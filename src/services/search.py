"""Tìm kiếm Giai đoạn 1 (docs/nm/08): bỏ dấu + khớp chuỗi con trên title+description của tin `published`.

Vì sao tính trong Python thay vì cột bỏ dấu + LIKE: dữ liệu demo nhỏ, không cần migration; kết quả
tương đương LIKE '%từ%' trên chữ đã bỏ dấu. Giai đoạn 2 (search_semantic) chỉ làm khi AI sẵn sàng.
"""

from __future__ import annotations

from typing import Any

from src.services import db
from src.services.pii import mask_phone
from src.services.posting import format_vnd
from src.services.text import normalize_text

MAX_RESULTS = 5
CANDIDATE_LIMIT = 500
MSG_NO_RESULT = "Chưa có tin phù hợp."


def tokenize(query: str) -> list[str]:
    """Chữ thường, bỏ dấu, tách từ, bỏ trùng (giữ thứ tự)."""
    return list(dict.fromkeys(normalize_text(query).split()))


def search(query: str, limit: int = MAX_RESULTS) -> list[dict[str, Any]]:
    """Tin đã đăng khớp ≥ 1 từ; xếp theo số từ khớp, rồi mới nhất."""
    words = tokenize(query)
    if not words:
        return []
    scored: list[tuple[int, dict[str, Any]]] = []
    for row in db.search_candidates(CANDIDATE_LIMIT):  # đã sắp mới nhất trước
        haystack = normalize_text(f"{row['title'] or ''} {row['description'] or ''}")
        hits = sum(1 for w in words if w in haystack)
        if hits:
            scored.append((hits, row))
    scored.sort(key=lambda t: t[0], reverse=True)  # sort ổn định → giữ thứ tự mới nhất khi bằng điểm
    return [row for _, row in scored[:limit]]


def format_results(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return MSG_NO_RESULT
    lines = [f"Tìm thấy {len(rows)} tin:"]
    for r in rows:
        price = format_vnd(r["price_vnd"]) if r.get("price_vnd") else "thương lượng"
        lines.append(f"#{r['id']} {mask_phone(r['title'] or '')} — {price}")
    lines.append(f'Nhắn "/xem {rows[0]["id"]}" để xem chi tiết.')
    return "\n".join(lines)
