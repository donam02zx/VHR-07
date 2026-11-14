"""Bản giả 4 hàm AI (docs/nm/04) — hành vi xác định để demo/test ổn định, không gọi mạng.

So khớp từ khoá trên chữ đã bỏ dấu, nên "xe dap" và "xe đạp" cho cùng kết quả.
"""

from typing import Any

from src.services.text import normalize_text

# ---- Từ khoá (sửa ở đây) ----
BICYCLE_KEYWORDS = ("xe đạp",)
SCAM_KEYWORDS = ("chuyển khoản trước", "cọc trước", "đặt cọc")
PROHIBITED_KEYWORDS = ("thuốc lá điện tử", "vũ khí", "pháo")

SCORE_PROHIBITED = 0.9
SCORE_SCAM = 0.55
SCORE_CLEAN = 0.1

DEFAULT_CATEGORY = "Khác"
# Khoảng giá gợi ý theo danh mục (VND).
PRICE_TABLE: dict[str, tuple[int, int]] = {
    "Thể thao": (800_000, 1_500_000),
    "Điện tử": (500_000, 3_000_000),
    "Gia dụng": (200_000, 1_000_000),
    "Nội thất": (300_000, 2_000_000),
    "Thời trang": (50_000, 300_000),
    DEFAULT_CATEGORY: (100_000, 500_000),
}
TITLE_MAX = 60


def _matches(text: str, keywords: tuple[str, ...]) -> list[str]:
    norm = normalize_text(text)
    return [kw for kw in keywords if normalize_text(kw) in norm]


def draft_listing(image: bytes | None, caption: str) -> dict[str, str]:
    """Soạn nháp từ chú thích; ảnh bị bỏ qua trong bản giả."""
    if _matches(caption, BICYCLE_KEYWORDS):
        return {
            "title": "Xe đạp thể thao đã qua sử dụng",
            "description": caption.strip(),
            "category": "Thể thao",
            "condition": "Cũ 80%",
        }
    return {
        "title": caption.strip()[:TITLE_MAX],
        "description": caption.strip(),
        "category": DEFAULT_CATEGORY,
        "condition": "Đã qua sử dụng",
    }


def suggest_price(listing: dict[str, Any]) -> dict[str, Any]:
    """Khoảng giá theo bảng cố định; danh mục lạ dùng dòng `Khác`."""
    category = listing.get("category") or DEFAULT_CATEGORY
    known = category in PRICE_TABLE
    low, high = PRICE_TABLE[category if known else DEFAULT_CATEGORY]
    note = "" if known else f" (danh mục '{category}' chưa có trong bảng, dùng '{DEFAULT_CATEGORY}')"
    return {"low": low, "high": high, "rationale": f"Bảng giá giả theo danh mục {category}{note}"}


def moderate(listing: dict[str, Any]) -> dict[str, Any]:
    """Điểm nghi ngờ theo từ khoá trong caption/title/description. Hàng cấm ưu tiên hơn lừa đảo."""
    text = " ".join(str(listing.get(k) or "") for k in ("caption", "title", "description"))
    prohibited = _matches(text, PROHIBITED_KEYWORDS)
    scam = _matches(text, SCAM_KEYWORDS)
    if prohibited:
        score, reason = SCORE_PROHIBITED, "Hàng cấm: " + ", ".join(prohibited)
    elif scam:
        score, reason = SCORE_SCAM, "Dấu hiệu lừa đảo: " + ", ".join(scam)
    else:
        score, reason = SCORE_CLEAN, "Không khớp từ khoá rủi ro"
    return {"score": score, "layers": {"rule": score, "model": 0.0}, "reason": reason}


def search_semantic(query: str, k: int = 5) -> list[int]:
    """Bản giả không có chỉ mục ngữ nghĩa — SW dùng tìm LIKE (docs/nm/08)."""
    return []
