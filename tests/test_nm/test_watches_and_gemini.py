"""Săn tin + lọc giá (luật) và 4 hàm Gemini với lớp gọi mạng được thay (không gọi Gemini thật)."""

from pathlib import Path

import pytest

from src.config import get_settings
from src.services import ai, ai_gemini, db, posting, search, watches
from src.services.intent import detect, parse_price_range

BUYER = "zu-buyer"
SELLER = "zu-seller"


@pytest.fixture(autouse=True)
def tmp_db(tmp_path: Path) -> None:
    db.reset_for_tests(tmp_path / "nm.db")


def published(title: str, price: int | None, seller: str = SELLER) -> int:
    uid = db.upsert_user(seller)
    lid = db.create_listing(uid, title=title, description="", price_vnd=price, category="Điện tử")
    for a, b in (("draft", "awaiting_confirm"), ("awaiting_confirm", "pending_moderation"),
                 ("pending_moderation", "published")):
        assert db.set_status(lid, a, b)
    return lid


# ---------------------------------------------------------------- khoảng giá
@pytest.mark.parametrize(
    ("text", "lo", "hi"),
    [
        ("laptop dưới 5 triệu", None, 5_000_000),
        ("laptop duoi 5tr", None, 5_000_000),
        ("xe đạp từ 1 đến 2 triệu", 1_000_000, 2_000_000),
        ("tủ lạnh 2-3tr", 2_000_000, 3_000_000),
        ("bàn học trên 500k", 500_000, None),
        ("quạt không quá 300k", None, 300_000),
        ("laptop tầm 4tr đến 6tr", 4_000_000, 6_000_000),
        ("laptop", None, None),
        ("xe 13-16 inch", None, None),
        ("dưới 5", None, None),
    ],
)
def test_parse_price_range(text: str, lo: int | None, hi: int | None) -> None:
    assert parse_price_range(text)[:2] == (lo, hi)


@pytest.mark.parametrize(
    ("text", "kind", "query", "lo", "hi"),
    [
        ("tìm laptop dưới 5 triệu", "search", "laptop", None, 5_000_000),
        ("có ai bán xe đạp từ 1 đến 2 triệu không", "search", "xe đạp", 1_000_000, 2_000_000),
        ("báo mình khi có laptop dưới 5 triệu", "watch", "laptop", None, 5_000_000),
        ("có tủ lạnh thì nhắn em nhé", "watch", "tủ lạnh", None, None),
        ("săn giúp mình xe đạp trẻ em", "watch", "xe đạp trẻ em", None, None),
        ("mình đang săn những gì", "my_watches", "", None, None),
        ("đồ dưới 300k", "search", "", None, 300_000),
    ],
)
def test_detect_with_price(text: str, kind: str, query: str, lo: int | None, hi: int | None) -> None:
    it = detect(text)
    assert (it.kind, it.query, it.min_price, it.max_price) == (kind, query, lo, hi)


def test_search_price_filter() -> None:
    a = published("Laptop Dell", 4_500_000)
    published("Laptop Mac", 15_000_000)
    published("Laptop cũ chưa giá", None)
    assert [r["id"] for r in search.search("laptop", max_price=5_000_000)] == [a]
    assert len(search.search("", max_price=5_000_000)) == 1


# ---------------------------------------------------------------- săn tin
def test_watch_create_list_cancel_limit() -> None:
    uid = db.upsert_user(BUYER)
    wid, text = watches.create(uid, "laptop", None, 5_000_000)
    assert wid and "laptop" in text and "dưới 5.000.000 đ" in text
    assert "mã " + str(wid) in watches.list_text(uid)
    assert db.cancel_watch(wid, uid) is True
    assert db.cancel_watch(wid, uid) is False
    assert watches.create(uid, "", None, None)[0] is None
    for i in range(watches.MAX_ACTIVE_PER_USER):
        assert watches.create(uid, f"món {i}", None, None)[0]
    assert watches.create(uid, "thêm", None, None)[0] is None


def test_watch_mentions_existing_matches() -> None:
    lid = published("Laptop Dell", 4_500_000)
    _, text = watches.create(db.upsert_user(BUYER), "laptop", None, 5_000_000)
    assert f"Hiện đã có: #{lid} Laptop Dell" in text


def test_notify_only_matching_and_not_seller() -> None:
    buyer = db.upsert_user(BUYER)
    seller = db.upsert_user(SELLER)
    watches.create(buyer, "laptop dell", None, 5_000_000)
    watches.create(seller, "laptop", None, None)  # người bán săn chính món mình → không tự nhắn
    other = db.upsert_user("zu-other")
    watches.create(other, "xe đạp", None, None)
    match = published("Laptop Dell Latitude", 4_500_000)
    too_expensive = published("Laptop Dell XPS", 20_000_000)
    partial = published("Laptop Asus", 3_000_000)
    assert [r.chat_id for r in watches.notify_for(db.get_listing(match))] == [BUYER]
    assert watches.notify_for(db.get_listing(too_expensive)) == []
    assert watches.notify_for(db.get_listing(partial)) == []
    assert db.list_audit(match)[-1]["action"] == "watch_notify"


def test_publish_replies_include_watch_notifications() -> None:
    watches.create(db.upsert_user(BUYER), "xe đạp", None, None)
    lid = published("Xe đạp Giant", 2_000_000)
    chats = [r.chat_id for r in posting.publish_replies(db.get_listing(lid), SELLER)]
    assert chats == [SELLER, BUYER]


# ---------------------------------------------------------------- Gemini (lớp mạng được thay)
@pytest.fixture
def fake_structured(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, object, bool]] = []
    answers: dict[str, object] = {}

    def _fake(schema, content, fast=False):
        calls.append((schema.__name__, content, fast))
        return answers[schema.__name__]

    monkeypatch.setattr(ai_gemini, "_structured", _fake)
    return calls, answers


def test_gemini_draft_with_image_and_category_guard(fake_structured) -> None:
    calls, answers = fake_structured
    answers["DraftOut"] = ai_gemini.DraftOut(title="Laptop Dell Latitude 7490 " * 5, description="Máy chạy tốt.",
                                             category="Máy tính", condition="Cũ 85%")
    d = ai_gemini.draft_listing(b"\x89PNG....", "laptop dell còn tốt")
    assert len(d["title"]) <= 60 and d["category"] == "Khác" and d["condition"] == "Cũ 85%"
    content = calls[0][1]
    assert isinstance(content, list) and content[1]["image_url"].startswith("data:image/png;base64,")
    assert "laptop dell còn tốt" in content[0]["text"]


def test_gemini_price_sorted(fake_structured) -> None:
    _, answers = fake_structured
    answers["PriceOut"] = ai_gemini.PriceOut(low=6_000_000, high=4_000_000, rationale="Laptop cũ")
    assert ai_gemini.suggest_price({"title": "Laptop"}) == {"low": 4_000_000, "high": 6_000_000,
                                                            "rationale": "Laptop cũ"}


@pytest.mark.parametrize(("desc", "model", "expected"), [("Đi ít", 0.1, 0.1), ("Đặt cọc trước nhé", 0.2, 0.55),
                                                         ("Đặt cọc trước", 0.9, 0.9)])
def test_gemini_moderate_max_of_rule_and_model(fake_structured, desc: str, model: float, expected: float) -> None:
    calls, answers = fake_structured
    answers["ModerationOut"] = ai_gemini.ModerationOut(score=model, reason="ok")
    m = ai_gemini.moderate({"title": "Xe đạp", "description": desc, "price_vnd": 1_000_000})
    assert m["score"] == expected and m["layers"]["model"] == model
    assert calls[0][2] is True  # dùng model nhanh


def test_gemini_search_semantic_filters_unknown_ids(fake_structured) -> None:
    _, answers = fake_structured
    a = published("Bàn học gỗ cho bé", 600_000)
    b = published("Laptop Dell", 4_500_000)
    answers["SearchOut"] = ai_gemini.SearchOut(ids=[a, 999, a, b])
    assert ai_gemini.search_semantic("đồ cho bé đi học", k=1) == [a]


def test_ai_switches_to_gemini_by_config(monkeypatch: pytest.MonkeyPatch, fake_structured) -> None:
    _, answers = fake_structured
    monkeypatch.setenv("NM_AI_MODE", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    get_settings.cache_clear()
    answers["PriceOut"] = ai_gemini.PriceOut(low=1, high=2, rationale="r")
    assert ai.mode() == "gemini" and ai.suggest_price({}) == {"low": 1, "high": 2, "rationale": "r"}


def test_gemini_mode_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import ValidationError

    from src.config import Settings

    with pytest.raises(ValidationError):
        Settings(_env_file=None, nm_ai_mode="gemini", google_api_key="")
