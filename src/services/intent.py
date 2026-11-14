"""Hiểu câu tự nhiên (không cần "/"): "tôi muốn tìm laptop", "cần bán xe đạp", "xem tin 13"...

Vì sao luật từ khoá thay vì LLM: chạy tức thì, xác định (demo ổn định), không cần API key, và phần AI
thuộc nhóm AI (04) — muốn thay bằng mô hình thì thêm hàm vào hợp đồng 04 rồi gọi qua `services/ai.py`.

Lưu ý tiếng Việt: bỏ dấu thì "bán", "bạn", "bàn" đều thành "ban" → các luật mơ hồ kiểm trên chữ CÓ dấu.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from src.services.text import normalize_text
from src.services.vnd import parse_vnd

IntentKind = Literal[
    "greet", "thanks", "help", "my_listings", "view", "ask", "search", "sell", "watch", "my_watches", "unknown"
]
DraftAction = Literal["confirm", "cancel", "price", "title", "none"]

# ---- Từ khoá (sửa ở đây) ----
GREETINGS = {"xin chao", "chao", "chao ban", "chao bot", "hello", "hi", "hey", "alo", "a lo"}
THANKS = {"cam on", "cam on ban", "cam on nhe", "cam on nha", "thanks", "thank you", "tks", "thank"}
# "giúp" đứng một mình KHÔNG là xin hướng dẫn ("giúp mình tìm laptop", "săn giúp").
HELP_RE = re.compile(
    r"\b(huong dan|help|lam sao|lam the nao|cach dang|cach dung|dung the nao|giup (gi|duoc gi)|lam duoc gi)\b"
)
MY_RE = re.compile(r"\b(tin cua (toi|minh|em)|tin (toi|minh|em) (da )?dang|cac tin cua)\b")
# Khớp ở BẤT KỲ đâu trong câu ("tôi muốn xem tin 13", "cho mình hỏi tin 13 còn không").
VIEW_RE = re.compile(r"\bxem\s+(?:chi tiet\s+)?(?:tin\s+)?(?:so\s+)?#?(\d+)\b|^(?:tin\s+(?:so\s+)?|#)(\d+)$")
ASK_RE = re.compile(r"(?:^|\s)h[oỏ]i\s+(?:tin\s+)?(?:số\s+|so\s+)?#?(\d+)\s*[:,\-]?\s*(.+)$", re.IGNORECASE | re.DOTALL)
BUYER_ASKS_SELLER_RE = re.compile(r"\b(có )?ai (đang )?bán\b|\bai ban\b")  # "có ai bán laptop không" = người MUA
SELL_RE = re.compile(
    r"\b(muon ban|can ban|ban gap|thanh ly|pass lai|nhuong lai|dang tin|dang ban|can pass|muon dang)\b"
)
SELL_START_ACCENTED = re.compile(r"^(bán|mình bán|em bán|tôi bán)\s")
SEARCH_TRIGGER_RE = re.compile(r"\b(tim|kiem|mua|can tim|hoi mua|co .+ khong|con .+ khong)\b")
# Săn tin: "báo mình khi có laptop dưới 5tr", "săn giúp tủ lạnh", "có xe đạp thì nhắn em".
WATCH_RE = re.compile(r"\b(san tin|san giup|san ho|theo doi)\b|\b(bao|nhan|nhac)\b.*\b(khi|neu|thi)\b|\bthi (bao|nhan)\b")
MY_WATCHES_RE = re.compile(r"\b(dang san|tin dang san|danh sach san|cac yeu cau san|san tin cua)\b")

# Khoảng giá trong câu (chữ thường CÓ dấu): "dưới 5 triệu", "từ 1 đến 2tr", "trên 500k".
_UNIT = r"(?:triệu|trieu|tr|củ|cu|k|nghìn|nghin|ngàn|ngan)"
_NUM = rf"\d[\d.,]*\s*{_UNIT}?(?:\s*\d{{1,3}}(?!\d))?"
PRICE_RANGE_RE = re.compile(
    rf"(?:từ|tu|khoảng|khoang|tầm|tam)?\s*(?P<a>{_NUM})\s*(?:đến|den|tới|toi|-|~)\s*(?P<b>{_NUM})"
)
PRICE_MAX_RE = re.compile(
    rf"(?:dưới|duoi|không quá|khong qua|tối đa|toi da|max|ít hơn|it hon|rẻ hơn|re hon|<=?)\s*(?P<v>{_NUM})"
)
PRICE_MIN_RE = re.compile(rf"(?:trên|tren|ít nhất|it nhat|tối thiểu|toi thieu|hơn|>=?)\s*(?P<v>{_NUM})")

# Cụm ý định bỏ trước khi tách từ (để "ban" không dấu trong "co ai ban"/"muon ban" không lọt vào từ khoá).
INTENT_PHRASES_RE = re.compile(
    r"\b(?:có\s+|co\s+)?ai\s+(?:đang\s+|dang\s+)?(?:bán|ban)\b"
    r"|\b(?:muốn|muon|cần|can|đang|dang|đăng|dang)\s+(?:bán|ban)\b"
)
# Đại từ chỉ bỏ khi đứng ĐẦU câu ("em muốn tìm..."), để giữ "trẻ em", "anh đào"...
PRONOUNS = {"tôi", "toi", "mình", "minh", "em", "anh", "chị", "chi", "mk", "e", "a", "tui", "tớ", "to"}
# ...hoặc ngay sau động từ hướng tới người nói ("nhắn em", "báo mình", "giúp tôi").
_PRONOUN_AFTER = {"báo", "bao", "nhắn", "nhan", "nhắc", "nhac", "giúp", "giup", "cho", "hộ", "ho", "với", "voi"}
# Từ đệm bỏ đi trước khi tìm. "bạn"/"bán" chỉ bỏ dạng CÓ dấu để giữ "bàn" (bàn học) và "ban" gõ không dấu.
STOPWORDS = {
    "tôi", "toi", "mình", "minh", "bạn", "bán", "muốn", "muon", "cần", "can",
    "tìm", "tim", "kiếm", "kiem", "mua", "có", "co", "ai", "không", "khong", "ko", "k", "hỏi", "hoi",
    "nào", "nao", "đâu", "dau", "ở", "cái", "cai", "chiếc", "chiec", "một", "mot", "vài", "vai",
    "những", "nhung", "các", "cac", "cho", "với", "voi", "đi", "di", "nhé", "nhe", "nha", "ạ", "à",
    "ơi", "oi", "vậy", "vay", "thế", "the", "là", "la", "được", "duoc", "đang", "dang", "đồ", "món",
    "mon", "giá", "gia", "rẻ", "re", "hàng", "hang", "còn", "con", "ạ.", "hả", "ha", "gì", "gi",
    "thanh", "lý", "ly", "pass", "lại", "lai", "nhượng", "nhuong", "gấp", "gap", "đăng", "tin",
    "please", "pls", "shop", "nhà", "nha", "mấy", "may", "cũ", "cu",
    "báo", "bao", "nhắn", "nhan", "nhắc", "nhac", "khi", "nếu", "neu", "thì", "thi", "giúp", "giup",
    "săn", "san", "theo", "dõi", "doi", "mới", "moi", "lúc", "luc", "hộ", "ho", "tầm", "tam", "khoảng", "khoang",
}

CONFIRM = {
    "ok", "oke", "okay", "oki", "okie", "ok ban", "ok nhe", "ok dang di", "dang", "dang di", "dang luon",
    "dong y", "duoc", "u", "uh", "um", "chot", "chot di", "yes", "dung roi", "ok luon",
}
CANCEL = {
    "huy", "huy di", "thoi", "thoi khong dang", "bo", "bo di", "khong dang nua", "khong ban nua",
    "thoi khong ban", "cancel", "huy tin",
}
PRICE_PREFIXES = ("sua gia", "doi gia", "gia")
TITLE_PREFIXES = ("sua tieu de", "doi tieu de", "tieu de", "doi ten", "sua ten")


@dataclass(frozen=True)
class Intent:
    kind: IntentKind
    query: str = ""  # search/watch: từ khoá đã lọc; sell: tên món (nếu có); ask: câu hỏi
    listing_id: int | None = None
    explicit: bool = True  # False = không có từ khoá ý định, chỉ đoán "tìm" từ nội dung
    min_price: int | None = None
    max_price: int | None = None


def _lower(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).lower().split())


def _price(raw: str, unit_from: str = "") -> int | None:
    """Giá trong câu; "1" trong "từ 1 đến 2 triệu" mượn đơn vị của vế sau."""
    value = parse_vnd(raw)
    if value is None and unit_from:
        unit = re.search(_UNIT + r"$", unit_from.strip())
        if unit and re.fullmatch(r"\d[\d.,]*", raw.strip()):
            value = parse_vnd(raw.strip() + unit.group(0))
    return value


def parse_price_range(text: str) -> tuple[int | None, int | None, str]:
    """Tách điều kiện giá khỏi câu → (min, max, phần câu còn lại). Không có/không hiểu → (None, None, câu)."""
    lowered = _lower(text)
    if m := PRICE_RANGE_RE.search(lowered):
        b = _price(m["b"])
        a = _price(m["a"], m["b"])
        if a is not None and b is not None:
            lo, hi = sorted((a, b))
            return lo, hi, lowered[: m.start()] + " " + lowered[m.end():]
    if m := PRICE_MAX_RE.search(lowered):
        if (v := _price(m["v"])) is not None:
            return None, v, lowered[: m.start()] + " " + lowered[m.end():]
    if m := PRICE_MIN_RE.search(lowered):
        if (v := _price(m["v"])) is not None:
            return v, None, lowered[: m.start()] + " " + lowered[m.end():]
    return None, None, text


def keywords(text: str) -> str:
    """Bỏ từ đệm/dấu câu, giữ từ có nghĩa (giữ dấu gốc): "tôi muốn tìm laptop cũ ạ" → "laptop"."""
    tokens = re.findall(r"\w+", INTENT_PHRASES_RE.sub(" ", _lower(text)))
    while tokens and tokens[0] in PRONOUNS:
        tokens.pop(0)
    kept = [t for i, t in enumerate(tokens) if not (t in PRONOUNS and i > 0 and tokens[i - 1] in _PRONOUN_AFTER)]
    return " ".join(t for t in kept if t not in STOPWORDS and len(t) > 1)


def detect(text: str) -> Intent:
    """Ý định của một câu tự do (không bắt đầu bằng "/")."""
    lowered = _lower(text)
    norm = normalize_text(text)
    if not norm:
        return Intent("unknown", explicit=False)
    if norm.strip(" .!?") in GREETINGS:
        return Intent("greet")
    if norm.strip(" .!?") in THANKS:
        return Intent("thanks")
    if m := ASK_RE.search(text.strip()):
        return Intent("ask", query=m.group(2).strip(), listing_id=int(m.group(1)))
    if m := VIEW_RE.search(norm):
        return Intent("view", listing_id=int(m.group(1) or m.group(2)))
    if MY_RE.search(norm):
        return Intent("my_listings")
    if MY_WATCHES_RE.search(norm):
        return Intent("my_watches")
    if HELP_RE.search(norm):
        return Intent("help")
    lo, hi, rest = parse_price_range(text)
    if WATCH_RE.search(norm):
        return Intent("watch", query=keywords(rest), min_price=lo, max_price=hi)
    if BUYER_ASKS_SELLER_RE.search(lowered):
        return Intent("search", query=keywords(rest), min_price=lo, max_price=hi)
    if SELL_RE.search(norm) or SELL_START_ACCENTED.match(lowered):
        return Intent("sell", query=keywords(rest))
    if SEARCH_TRIGGER_RE.search(norm):
        return Intent("search", query=keywords(rest), min_price=lo, max_price=hi)
    words = keywords(rest)
    if words or lo is not None or hi is not None:
        return Intent("search", query=words, explicit=False, min_price=lo, max_price=hi)
    return Intent("unknown", explicit=False)


def draft_action(text: str) -> tuple[DraftAction, str]:
    """Câu trả lời khi đang có bản nháp: xác nhận / huỷ / sửa giá / sửa tiêu đề.

    Trả (hành động, phần còn lại của câu GỐC — giữ dấu). Giá trần có đơn vị ("1tr2") cũng hiểu là sửa giá.
    """
    norm = normalize_text(text).strip(" .!?")
    if norm in CONFIRM:
        return "confirm", ""
    if norm in CANCEL:
        return "cancel", ""
    for p in TITLE_PREFIXES:
        if norm == p or norm.startswith(p + " "):
            return "title", _drop_words(text, len(p.split()))
    for p in PRICE_PREFIXES:
        if norm == p or norm.startswith(p + " "):
            rest = _drop_words(text, len(p.split()))
            # "sửa giá thành 15 triệu" → "15 triệu"; không thấy giá → giữ nguyên để báo "chưa hiểu giá"
            return "price", find_price(rest, need_unit=False) or rest
    if parse_vnd(text) is not None:
        return "price", text.strip()
    # Giá nằm giữa câu: "tôi muốn giá 15 triệu", "để 15tr nhé". Có chữ "giá" → nhận cả số trần ≥ 1000;
    # không có → phải có đơn vị, và bỏ qua câu kể giá đã mua ("mua 2tr năm ngoái").
    words = set(norm.split())
    if "gia" in words or "mua" not in words:
        found = find_price(text, need_unit="gia" not in words)
        if found:
            return "price", found
    return "none", ""


_PRICE_UNIT_RE = re.compile(r"\d\s*(?:tr|trieu|cu|k|nghin|ngan|d|vnd|dong)\b|\d(?:tr|k)\d")


def find_price(text: str, need_unit: bool = True) -> str | None:
    """Tìm cụm giá đầu tiên trong câu (ưu tiên cụm dài: "1 triệu 5" hơn "1 triệu"). Trả cụm gốc hoặc None."""
    words = [w.strip(",!?;:") for w in text.split()]
    words = [w[:-1] if w.endswith(".") and not w[:-1].endswith(".") else w for w in words]
    for i in range(len(words)):
        for n in (4, 3, 2, 1):
            if i + n > len(words):
                continue
            frag = " ".join(words[i : i + n])
            if not frag or parse_vnd(frag) is None:
                continue
            if need_unit and not _PRICE_UNIT_RE.search(normalize_text(frag)):
                continue
            return frag
    return None


def _drop_words(text: str, n: int) -> str:
    parts = text.strip().split(maxsplit=n)
    return parts[n].strip() if len(parts) > n else ""
