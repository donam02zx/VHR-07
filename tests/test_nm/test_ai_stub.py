"""T04 — AI stub: hành vi xác định, đúng hợp đồng 04, gọi qua src.services.ai."""

import pytest

from src.services import ai, ai_stub

CAPTIONS = {
    "bicycle": "Bán xe đạp thể thao, đi ít, còn mới",
    "scam": "Bán nồi cơm điện, chuyển khoản trước mới giao",
    "prohibited": "Thanh lý thuốc lá điện tử còn nguyên hộp",
}


def _check_draft_shape(d: dict) -> None:
    assert set(d) == {"title", "description", "category", "condition"}
    assert all(isinstance(v, str) for v in d.values())


def _check_moderation_shape(m: dict) -> None:
    assert set(m) == {"score", "layers", "reason"}
    assert 0.0 <= m["score"] <= 1.0
    assert {"rule", "model"} <= set(m["layers"])
    assert isinstance(m["reason"], str) and m["reason"]


def test_ai_module_reexports_stub() -> None:
    assert ai.draft_listing is ai_stub.draft_listing
    assert ai.suggest_price is ai_stub.suggest_price
    assert ai.moderate is ai_stub.moderate
    assert ai.search_semantic is ai_stub.search_semantic


def test_bicycle_caption() -> None:
    d = ai.draft_listing(None, CAPTIONS["bicycle"])
    _check_draft_shape(d)
    assert d == {
        "title": "Xe đạp thể thao đã qua sử dụng",
        "description": CAPTIONS["bicycle"],
        "category": "Thể thao",
        "condition": "Cũ 80%",
    }
    p = ai.suggest_price(d)
    assert (p["low"], p["high"]) == (800_000, 1_500_000)
    assert isinstance(p["rationale"], str)
    m = ai.moderate({**d, "caption": CAPTIONS["bicycle"]})
    _check_moderation_shape(m)
    assert m["score"] == 0.1


def test_scam_caption() -> None:
    d = ai.draft_listing(b"img", CAPTIONS["scam"])
    _check_draft_shape(d)
    assert d["title"] == CAPTIONS["scam"][:60]
    m = ai.moderate({**d, "caption": CAPTIONS["scam"]})
    _check_moderation_shape(m)
    assert m["score"] == 0.55
    assert "chuyển khoản trước" in m["reason"]


def test_prohibited_caption() -> None:
    d = ai.draft_listing(None, CAPTIONS["prohibited"])
    m = ai.moderate({**d, "caption": CAPTIONS["prohibited"]})
    _check_moderation_shape(m)
    assert m["score"] == 0.9
    assert "thuốc lá điện tử" in m["reason"]


def test_prohibited_wins_over_scam() -> None:
    m = ai.moderate({"caption": "Bán pháo, đặt cọc trước"})
    assert m["score"] == 0.9


@pytest.mark.parametrize("caption", ["Ban xe dap cu", "XE ĐẠP trẻ em"])
def test_bicycle_accent_and_case_insensitive(caption: str) -> None:
    assert ai.draft_listing(None, caption)["category"] == "Thể thao"


def test_deterministic() -> None:
    for c in CAPTIONS.values():
        assert ai.draft_listing(None, c) == ai.draft_listing(None, c)
        assert ai.moderate({"caption": c}) == ai.moderate({"caption": c})


def test_long_caption_title_truncated() -> None:
    caption = "Bàn học gỗ " * 20
    assert len(ai.draft_listing(None, caption)["title"]) <= 60


def test_suggest_price_unknown_category_uses_default() -> None:
    p = ai.suggest_price({"category": "Đồ cổ"})
    assert (p["low"], p["high"]) == ai_stub.PRICE_TABLE[ai_stub.DEFAULT_CATEGORY]
    assert "Đồ cổ" in p["rationale"]


def test_search_semantic_empty() -> None:
    assert ai.search_semantic("xe dap") == []
