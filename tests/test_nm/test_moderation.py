"""T07 — kiểm duyệt: route biên, luật cứng, 3 nhánh process, AI lỗi/timeout/sai dạng."""

import time
from pathlib import Path
from typing import Any

import pytest

from src.config import Settings
from src.services import ai, db, moderation, safe_ai
from src.services.moderation import REASON_AI_UNAVAILABLE, check_rules, route


@pytest.fixture(autouse=True)
def tmp_db(tmp_path: Path) -> None:
    db.reset_for_tests(tmp_path / "nm.db")


@pytest.fixture(autouse=True)
def default_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None, mod_publish_below=0.3, mod_reject_from=0.8)
    monkeypatch.setattr(moderation, "get_settings", lambda: settings)


def pending_listing(title: str = "Xe đạp", description: str = "Đi ít", price: int | None = 1_000_000) -> int:
    seller = db.upsert_user("zu_1", "Lan")
    lid = db.create_listing(seller, title=title, description=description, price_vnd=price, category="Thể thao")
    for frm, to in (("draft", "awaiting_confirm"), ("awaiting_confirm", "pending_moderation")):
        assert db.set_status(lid, frm, to)
    return lid


def fake_moderate(monkeypatch: pytest.MonkeyPatch, result: Any) -> list[dict]:
    calls: list[dict] = []

    def _fn(listing: dict) -> Any:
        calls.append(listing)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(ai, "moderate", _fn)
    return calls


def ai_score(score: float, reason: str = "ai") -> dict:
    return {"score": score, "layers": {"rule": 0.0, "model": score}, "reason": reason}


# ---------------------------------------------------------------- route
@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.0, "publish"),
        (0.29, "publish"),
        (0.3, "review"),
        (0.5, "review"),
        (0.79, "review"),
        (0.8, "reject"),
        (1.0, "reject"),
    ],
)
def test_route_boundaries(score: float, expected: str) -> None:
    assert route(score) == expected


def test_route_reads_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings(_env_file=None, mod_publish_below=0.5, mod_reject_from=0.9)
    monkeypatch.setattr(moderation, "get_settings", lambda: s)
    assert route(0.4) == "publish"
    assert route(0.85) == "review"
    assert route(0.9) == "reject"


def test_route_explicit_thresholds() -> None:
    assert route(0.2, publish_below=0.1, reject_from=0.5) == "review"


@pytest.mark.parametrize("score", [-0.1, 1.01])
def test_route_out_of_range(score: float) -> None:
    with pytest.raises(ValueError):
        route(score)


# ---------------------------------------------------------------- luật cứng
@pytest.mark.parametrize(
    ("title", "description", "price", "prohibited", "flags"),
    [
        ("Xe đạp", "Đi ít", 1_000_000, [], []),
        ("Pháo hoa Tết", "", 100_000, ["pháo"], []),
        ("Thuoc la dien tu", "", 300_000, ["thuốc lá điện tử"], []),
        ("Phao bơi trẻ em", "", 100_000, [], []),  # không nhầm với "pháo"
        ("Đàn guitar", "Cây sung cảnh", 900_000, [], []),  # không nhầm "đạn", "súng"
        ("Súng đồ chơi", "", 50_000, ["súng"], []),
        ("Nồi cơm", "Gọi 0912 345 678", 300_000, [], ["lộ SĐT trong tin"]),
        ("Nồi cơm", "Xem thêm https://abc.xyz/sale", 300_000, [], ["có đường link"]),
        ("Nồi cơm", "shopgiare.vn", 300_000, [], ["có đường link"]),
        ("Nồi cơm", "", 0, [], ["giá bất thường"]),
        ("Nồi cơm", "", 2_000_000_000, [], ["giá bất thường"]),
        ("Nồi cơm", "", None, [], ["giá bất thường"]),
        ("Nồi cơm", "", 1_000_000_000, [], []),
    ],
)
def test_check_rules(title: str, description: str, price: int | None, prohibited: list, flags: list) -> None:
    r = check_rules({"title": title, "description": description, "price_vnd": price})
    assert r.prohibited == prohibited
    assert r.flags == flags


# ---------------------------------------------------------------- process: 3 nhánh
async def test_process_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_moderate(monkeypatch, ai_score(0.1))
    lid = pending_listing()
    res = await moderation.process(lid)
    assert res.decision == "publish"
    row = db.get_listing(lid)
    assert row["status"] == "published"
    assert row["moderation_score"] == 0.1
    assert db.list_reviews() == []
    assert db.list_audit(lid)[-1]["action"] == "moderation_publish"


async def test_process_review(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_moderate(monkeypatch, ai_score(0.55, "Dấu hiệu lừa đảo: đặt cọc"))
    lid = pending_listing()
    res = await moderation.process(lid)
    assert res.decision == "review"
    assert db.get_listing(lid)["status"] == "in_review"
    reviews = db.list_reviews()
    assert [r["listing_id"] for r in reviews] == [lid]
    assert reviews[0]["score"] == 0.55
    assert "đặt cọc" in reviews[0]["reason"]


async def test_process_reject_by_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_moderate(monkeypatch, ai_score(0.9, "Hàng cấm: vũ khí"))
    lid = pending_listing()
    res = await moderation.process(lid)
    assert res.decision == "reject"
    assert res.reason == "Hàng cấm: vũ khí"
    assert db.get_listing(lid)["status"] == "rejected"
    assert db.get_listing(lid)["moderation_reason"]


async def test_rule_prohibited_rejects_without_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_moderate(monkeypatch, ai_score(0.0))
    lid = pending_listing(title="Bán pháo hoa")
    res = await moderation.process(lid)
    assert res.decision == "reject"
    assert "pháo" in res.reason
    assert calls == []
    assert db.get_listing(lid)["status"] == "rejected"


async def test_phone_flag_raises_to_review(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_moderate(monkeypatch, ai_score(0.1))
    lid = pending_listing(description="Liên hệ 0912345678")
    res = await moderation.process(lid)
    assert res.decision == "review"
    assert res.score == 0.3
    assert "lộ SĐT" in db.list_reviews()[0]["reason"]


async def test_final_score_is_max_of_rule_and_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_moderate(monkeypatch, ai_score(0.85))
    lid = pending_listing(description="Liên hệ 0912345678")
    res = await moderation.process(lid)
    assert res.score == 0.85 and res.decision == "reject"


# ---------------------------------------------------------------- AI lỗi
@pytest.mark.parametrize(
    "bad",
    [
        RuntimeError("model down"),
        {"score": 1.5, "layers": {}, "reason": "x"},
        {"score": -0.1, "layers": {}, "reason": "x"},
        {"layers": {}, "reason": "x"},
        {"score": 0.1, "reason": "x"},
        {"score": "0.1", "layers": {}, "reason": "x"},
        {"score": True, "layers": {}, "reason": "x"},
        None,
    ],
)
async def test_ai_failure_goes_to_review(monkeypatch: pytest.MonkeyPatch, bad: Any) -> None:
    fake_moderate(monkeypatch, bad)
    lid = pending_listing()
    res = await moderation.process(lid)
    assert res.decision == "review"
    assert res.reason == REASON_AI_UNAVAILABLE
    row = db.get_listing(lid)
    assert row["status"] == "in_review"
    assert row["moderation_reason"] == REASON_AI_UNAVAILABLE
    assert db.list_reviews()[0]["reason"] == REASON_AI_UNAVAILABLE
    assert db.list_audit(lid)[-1]["action"] == "moderation_review"


async def test_ai_timeout_goes_to_review(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(safe_ai, "AI_TIMEOUT_S", 0.05)

    def slow(listing: dict) -> dict:
        time.sleep(0.3)
        return ai_score(0.1)

    monkeypatch.setattr(ai, "moderate", slow)
    lid = pending_listing()
    res = await moderation.process(lid)
    assert res.decision == "review" and res.reason == REASON_AI_UNAVAILABLE
    assert db.get_listing(lid)["status"] == "in_review"


async def test_process_wrong_status_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_moderate(monkeypatch, ai_score(0.1))
    seller = db.upsert_user("zu_2")
    lid = db.create_listing(seller, title="x", price_vnd=1000)
    with pytest.raises(RuntimeError):
        await moderation.process(lid)
    with pytest.raises(RuntimeError):
        await moderation.process(9999)


async def test_stub_end_to_end_three_captions() -> None:
    """Với AI stub thật: xe đạp → đăng, lừa đảo → chờ duyệt, hàng cấm → từ chối."""
    clean = pending_listing(title="Xe đạp thể thao", description="Đi ít")
    scam = pending_listing(title="Nồi cơm", description="Chuyển khoản trước mới giao")
    banned = pending_listing(title="Thuốc lá điện tử", description="")
    assert (await moderation.process(clean)).decision == "publish"
    assert (await moderation.process(scam)).decision == "review"
    assert (await moderation.process(banned)).decision == "reject"
