"""Che số điện thoại VN trong nội dung công khai (docs/nm/08)."""

import re

# Di động VN: 0 hoặc +84/84, rồi đầu số 3/5/7/8/9 và 8 chữ số; cho phép dấu cách/chấm/gạch giữa chữ số.
_PHONE = re.compile(r"(?<![\d+])(?:\+84|84|0)[ .\-]?([35789])((?:[ .\-]?\d){8})(?!\d)")


def _mask(m: re.Match[str]) -> str:
    digits = "0" + m[1] + re.sub(r"\D", "", m[2])  # chuẩn hoá về 0xxxxxxxxx
    return f"{digits[:2]}xx xxx {digits[7:]}"


def mask_phone(text: str) -> str:
    """Thay mọi SĐT bằng dạng che giữa `09xx xxx 678` (giữ 2 số đầu + 3 số cuối)."""
    return _PHONE.sub(_mask, text)


def contains_phone(text: str) -> bool:
    """Có SĐT di động VN trong text không (luật cứng kiểm duyệt, 07)."""
    return _PHONE.search(text) is not None
