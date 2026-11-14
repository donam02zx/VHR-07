"""T03 — hàm thuần: parse_vnd, mask_phone, strip_accents (test bảng)."""

import pytest

from src.services.pii import mask_phone
from src.services.text import normalize_text, strip_accents
from src.services.vnd import parse_vnd


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("800k", 800_000),
        ("800K", 800_000),
        ("800.000", 800_000),
        ("800,000", 800_000),
        ("800000đ", 800_000),
        ("800000 đ", 800_000),
        ("1.200.000 VND", 1_200_000),
        ("1tr", 1_000_000),
        ("1tr2", 1_200_000),
        ("1tr25", 1_250_000),
        ("1tr250", 1_250_000),
        ("1,5 triệu", 1_500_000),
        ("1.5tr", 1_500_000),
        ("1 triệu 5", 1_500_000),
        ("2 trieu", 2_000_000),
        ("1tr500k", 1_500_000),
        ("1 triệu 500 nghìn", 1_500_000),
        ("1,5k", 1_500),
        ("450 nghìn", 450_000),
        ("3 củ", 3_000_000),
        ("  800k  ", 800_000),
        ("1000", 1_000),
    ],
)
def test_parse_vnd_ok(text: str, expected: int) -> None:
    assert parse_vnd(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "abc",
        "800",  # số trần mơ hồ
        "0k",
        "800k 5",
        "1,5tr2",
        "1.2.3",
        "tr",
        "giá 800k",
        "-800k",
        "1,5",
        "800 usd",
    ],
)
def test_parse_vnd_none(text: str) -> None:
    assert parse_vnd(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0912345678", "09xx xxx 678"),
        ("0912 345 678", "09xx xxx 678"),
        ("0912.345.678", "09xx xxx 678"),
        ("0912-345-678", "09xx xxx 678"),
        ("+84912345678", "09xx xxx 678"),
        ("+84 912 345 678", "09xx xxx 678"),
        ("84912345678", "09xx xxx 678"),
        ("0387654321", "03xx xxx 321"),
        ("Gọi 0912345678 nhé", "Gọi 09xx xxx 678 nhé"),
        ("A: 0912345678, B: 0701112223", "A: 09xx xxx 678, B: 07xx xxx 223"),
        ("Giá 1.200.000 đ", "Giá 1.200.000 đ"),
        ("01234567890", "01234567890"),  # đầu số không phải di động
        ("091234567", "091234567"),  # thiếu số
        ("09123456789", "09123456789"),  # thừa số
        ("không có số", "không có số"),
    ],
)
def test_mask_phone(text: str, expected: str) -> None:
    assert mask_phone(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Xe đạp", "Xe dap"),
        ("ĐỒNG HỒ", "DONG HO"),
        ("Nồi cơm điện", "Noi com dien"),
        ("tủ lạnh", "tu lanh"),
        ("Bàn ghế gỗ", "Ban ghe go"),
        ("sữa", "sua"),
        ("Quạt trần", "Quat tran"),
        ("Máy giặt Toshiba", "May giat Toshiba"),
        ("ưu đãi", "uu dai"),
        ("abc 123", "abc 123"),
        ("", ""),
    ],
)
def test_strip_accents(text: str, expected: str) -> None:
    assert strip_accents(text) == expected


def test_strip_accents_decomposed_input() -> None:
    # Bàn phím/điện thoại có thể gửi dạng tổ hợp (NFD).
    import unicodedata

    assert strip_accents(unicodedata.normalize("NFD", "Xe đạp")) == "Xe dap"


def test_normalize_text() -> None:
    assert normalize_text("  Xe   ĐẠP  Thể thao ") == "xe dap the thao"
