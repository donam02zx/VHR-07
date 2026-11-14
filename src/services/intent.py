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

IntentKind = Literal["greet", "thanks", "help", "my_listings", "view", "ask", "search", "sell", "unknown"]
DraftAction = Literal["confirm", "cancel", "price", "title", "none"]

# ---- Từ khoá (sửa ở đây) ----
GREETINGS = {"xin chao", "chao", "chao ban", "chao bot", "hello", "hi", "hey", "alo", "a lo"}
THANKS = {"cam on", "cam on ban", "cam on nhe", "cam on nha", "thanks", "thank you", "tks", "thank"}
HELP_RE = re.compile(r"\b(huong dan|giup|help|lam sao|lam the nao|cach dang|cach dung|dung the nao)\b")
MY_RE = re.compile(r"\b(tin cua (toi|minh|em)|tin (toi|minh|em) (da )?dang|cac tin cua)\b")
VIEW_RE = re.compile(r"^(?:xem\s+)?(?:tin\s+(?:so\s+)?|#)(\d+)$|^xem\s+(\d+)$")
ASK_RE = re.compile(r"^\s*h[oỏ]i\s+(?:tin\s+)?#?(\d+)\s*[:,\-]?\s*(.+)$", re.IGNORECASE | re.DOTALL)
BUYER_ASKS_SELLER_RE = re.compile(r"\b(có )?ai (đang )?bán\b|\bai ban\b")  # "có ai bán laptop không" = người MUA
SELL_RE = re.compile(
    r"\b(muon ban|can ban|ban gap|thanh ly|pass lai|nhuong lai|dang tin|dang ban|can pass|muon dang)\b"
)
SELL_START_ACCENTED = re.compile(r"^(bán|mình bán|em bán|tôi bán)\s")
SEARCH_TRIGGER_RE = re.compile(r"\b(tim|kiem|mua|can tim|hoi mua|co .+ khong|con .+ khong)\b")

# Cụm ý định bỏ trước khi tách từ (để "ban" không dấu trong "co ai ban"/"muon ban" không lọt vào từ khoá).
INTENT_PHRASES_RE = re.compile(
    r"\b(?:có\s+|co\s+)?ai\s+(?:đang\s+|dang\s+)?(?:bán|ban)\b"
    r"|\b(?:muốn|muon|cần|can|đang|dang|đăng|dang)\s+(?:bán|ban)\b"
)
# Đại từ chỉ bỏ khi đứng ĐẦU câu ("em muốn tìm..."), để giữ "trẻ em", "anh đào"...
PRONOUNS = {"tôi", "toi", "mình", "minh", "em", "anh", "chị", "chi", "mk", "e", "a"}
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
    query: str = ""  # search: từ khoá đã lọc; sell: tên món (nếu có); ask: câu hỏi
    listing_id: int | None = None
    explicit: bool = True  # False = không có từ khoá ý định, chỉ đoán "tìm" từ nội dung


def _lower(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).lower().split())


def keywords(text: str) -> str:
    """Bỏ từ đệm/dấu câu, giữ từ có nghĩa (giữ dấu gốc): "tôi muốn tìm laptop cũ ạ" → "laptop"."""
    tokens = re.findall(r"\w+", INTENT_PHRASES_RE.sub(" ", _lower(text)))
    while tokens and tokens[0] in PRONOUNS:
        tokens.pop(0)
    return " ".join(t for t in tokens if t not in STOPWORDS and len(t) > 1)


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
    if m := ASK_RE.match(text.strip()):
        return Intent("ask", query=m.group(2).strip(), listing_id=int(m.group(1)))
    if m := VIEW_RE.match(norm):
        return Intent("view", listing_id=int(m.group(1) or m.group(2)))
    if MY_RE.search(norm):
        return Intent("my_listings")
    if HELP_RE.search(norm):
        return Intent("help")
    if BUYER_ASKS_SELLER_RE.search(lowered):
        return Intent("search", query=keywords(text))
    if SELL_RE.search(norm) or SELL_START_ACCENTED.match(lowered):
        return Intent("sell", query=keywords(text))
    if SEARCH_TRIGGER_RE.search(norm):
        return Intent("search", query=keywords(text))
    words = keywords(text)
    if words:
        return Intent("search", query=words, explicit=False)
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
    for prefixes, action in ((TITLE_PREFIXES, "title"), (PRICE_PREFIXES, "price")):
        for p in prefixes:
            if norm == p or norm.startswith(p + " "):
                return action, _drop_words(text, len(p.split()))
    if parse_vnd(text) is not None:
        return "price", text.strip()
    return "none", ""


def _drop_words(text: str, n: int) -> str:
    parts = text.strip().split(maxsplit=n)
    return parts[n].strip() if len(parts) > n else ""
