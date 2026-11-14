"""parse_vnd: hiểu giá kiểu người Việt gõ ("800k", "1tr2", "1 triệu 5") → số đồng."""

import re
from decimal import Decimal, InvalidOperation

from src.services.text import normalize_text

_MILLION = r"tr|trieu|cu"
_THOUSAND = r"k|nghin|ngan"
_PRICE = re.compile(
    rf"""
    (?P<num>\d+(?:[.,]\d+)*)\s*
    (?P<unit>{_MILLION}|{_THOUSAND})?\s*
    (?P<rest>\d{{1,3}})?\s*
    (?P<rest_unit>{_THOUSAND})?\s*
    (?:d|vnd|dong)?
    """,
    re.VERBOSE,
)
_GROUPED = re.compile(r"\d{1,3}(?:([.,])\d{3})(?:\1\d{3})*")
# Số trần không đơn vị dưới ngưỡng này ("800") là mơ hồ (800đ hay 800k?) → None để hỏi lại.
MIN_BARE_VND = 1000


def _to_decimal(token: str) -> Decimal | None:
    """'800.000'/'800,000' là phân nhóm nghìn; '1,5'/'1.5' là thập phân."""
    if _GROUPED.fullmatch(token):
        return Decimal(re.sub(r"[.,]", "", token))
    if token.count(".") + token.count(",") > 1:
        return None
    try:
        return Decimal(token.replace(",", "."))
    except InvalidOperation:
        return None


def parse_vnd(s: str) -> int | None:
    """Trả số đồng (int > 0), hoặc None nếu không hiểu chắc chắn — không đoán bừa."""
    m = _PRICE.fullmatch(normalize_text(s))
    if m is None:
        return None
    num = _to_decimal(m["num"])
    if num is None:
        return None
    unit, rest, rest_unit = m["unit"], m["rest"], m["rest_unit"]
    is_million = unit is not None and re.fullmatch(_MILLION, unit) is not None

    if rest is not None and not is_million:
        return None  # "800k 5" vô nghĩa
    if rest_unit is not None and rest is None:
        return None
    if is_million:
        value = num * 1_000_000
        if rest is not None:
            if num != num.to_integral_value():
                return None  # "1,5tr2" mơ hồ
            # "1tr2" → 200k, "1tr25" → 250k, "1tr250" → 250k; "1tr500k" → 500k.
            value += int(rest) * 1000 if rest_unit else int(rest) * 10 ** (6 - len(rest))
    elif unit is not None:
        value = num * 1000
    else:
        if num < MIN_BARE_VND:
            return None
        value = num
    if value != value.to_integral_value() or value <= 0:
        return None
    return int(value)
