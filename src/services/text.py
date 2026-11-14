"""Chuẩn hoá chữ tiếng Việt: bỏ dấu để tìm kiếm/parse không phụ thuộc cách gõ."""

import re
import unicodedata

_SPACES = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    """Bỏ dấu tiếng Việt ("Xe đạp" → "Xe dap"); giữ nguyên hoa/thường.

    `đ` không tách được bằng NFD nên thay tay.
    """
    decomposed = unicodedata.normalize("NFD", text)
    no_marks = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", no_marks).replace("đ", "d").replace("Đ", "D")


def normalize_text(text: str) -> str:
    """Chữ thường, bỏ dấu, gộp khoảng trắng — dạng chuẩn để so khớp."""
    return _SPACES.sub(" ", strip_accents(text).lower()).strip()
