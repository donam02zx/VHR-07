"""T02 — services/db.py trên SQLite tạm."""

from pathlib import Path

import pytest

from src.services import db


@pytest.fixture(autouse=True)
def tmp_db(tmp_path: Path) -> Path:
    path = tmp_path / "nm.db"
    db.reset_for_tests(path)
    return path


@pytest.fixture
def seller() -> int:
    return db.upsert_user("zu_1", "Chị Lan")


def _to_status(listing_id: int, *path: str) -> None:
    cur = db.get_listing(listing_id)["status"]
    for nxt in path:
        assert db.set_status(listing_id, cur, nxt)
        cur = nxt


def test_init_db_idempotent(tmp_db: Path) -> None:
    db.init_db()
    db.init_db()
    assert tmp_db.exists()


def test_upsert_user_same_id_and_keeps_name() -> None:
    a = db.upsert_user("zu_x", "An")
    b = db.upsert_user("zu_x", None)
    assert a == b
    assert db.get_user(a)["display_name"] == "An"
    assert db.get_user(a)["role"] == "resident"


def test_create_and_get_listing(seller: int) -> None:
    lid = db.create_listing(seller, title="Xe đạp", price_vnd=1_200_000, image_ref="img/1.jpg")
    row = db.get_listing(lid)
    assert row["status"] == "draft"
    assert row["title"] == "Xe đạp"
    assert row["price_vnd"] == 1_200_000
    assert row["resubmit_count"] == 0
    assert row["created_at"].endswith("+00:00")
    assert db.get_listing(9999) is None


def test_create_listing_rejects_unknown_column(seller: int) -> None:
    with pytest.raises(ValueError):
        db.create_listing(seller, status="published")


def test_create_listing_requires_existing_seller() -> None:
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        db.create_listing(424242, title="x")


def test_update_listing_fields(seller: int) -> None:
    lid = db.create_listing(seller)
    assert db.update_listing_fields(lid, price_vnd=500_000, title="Nồi cơm")
    assert db.get_listing(lid)["price_vnd"] == 500_000
    assert not db.update_listing_fields(9999, title="x")
    with pytest.raises(ValueError):
        db.update_listing_fields(lid, status="published")
    with pytest.raises(ValueError):
        db.update_listing_fields(lid)


@pytest.mark.parametrize(
    "path",
    [
        ["awaiting_confirm", "pending_moderation", "published", "withdrawn"],
        ["awaiting_confirm", "pending_moderation", "in_review", "rejected"],
        ["awaiting_confirm", "pending_moderation", "in_review", "needs_fix", "awaiting_confirm"],
        ["awaiting_confirm", "pending_moderation", "rejected"],
        ["awaiting_confirm", "withdrawn"],
        ["withdrawn"],
    ],
)
def test_valid_transitions(seller: int, path: list[str]) -> None:
    lid = db.create_listing(seller)
    _to_status(lid, *path)
    assert db.get_listing(lid)["status"] == path[-1]


@pytest.mark.parametrize(
    ("frm", "to"),
    [
        ("draft", "published"),
        ("awaiting_confirm", "published"),
        ("published", "draft"),
        ("rejected", "published"),
        ("withdrawn", "awaiting_confirm"),
        ("needs_fix", "published"),
        ("draft", "nonsense"),
    ],
)
def test_invalid_transition_raises(seller: int, frm: str, to: str) -> None:
    lid = db.create_listing(seller)
    with pytest.raises(db.InvalidTransitionError):
        db.set_status(lid, frm, to)
    assert db.get_listing(lid)["status"] == "draft"


def test_set_status_mismatch_returns_false(seller: int) -> None:
    lid = db.create_listing(seller)
    # Cạnh hợp lệ nhưng tin đang draft, không phải awaiting_confirm.
    assert db.set_status(lid, "awaiting_confirm", "pending_moderation") is False
    assert db.set_status(lid, "draft", "awaiting_confirm") is True
    # Lặp lại cùng chuyển (trùng) → False.
    assert db.set_status(lid, "draft", "awaiting_confirm") is False
    assert db.set_status(9999, "draft", "awaiting_confirm") is False


def test_published_sets_published_at(seller: int) -> None:
    lid = db.create_listing(seller)
    assert db.get_listing(lid)["published_at"] is None
    _to_status(lid, "awaiting_confirm", "pending_moderation", "published")
    assert db.get_listing(lid)["published_at"] is not None


def test_conversation_default_and_set(seller: int) -> None:
    assert db.get_conversation("c1")["state"] == "idle"
    lid = db.create_listing(seller)
    db.set_conversation("c1", "awaiting_confirm", lid)
    conv = db.get_conversation("c1")
    assert conv["state"] == "awaiting_confirm"
    assert conv["listing_id"] == lid
    db.set_conversation("c1", "idle")
    assert db.get_conversation("c1")["listing_id"] is None
    with pytest.raises(ValueError):
        db.set_conversation("c1", "bogus")


def test_try_mark_event_second_time_false() -> None:
    assert db.try_mark_event("upd:1") is True
    assert db.try_mark_event("upd:1") is False
    assert db.try_mark_event("upd:2") is True


def test_add_audit(seller: int) -> None:
    lid = db.create_listing(seller)
    db.add_audit(lid, "created", "by test")
    rows = db.list_audit(lid)
    assert [r["action"] for r in rows] == ["created"]


def _in_review_listing(seller: int) -> int:
    lid = db.create_listing(seller, title="Xe đạp")
    _to_status(lid, "awaiting_confirm", "pending_moderation", "in_review")
    return lid


def test_review_queue_approve(seller: int) -> None:
    lid = _in_review_listing(seller)
    rid = db.create_review(lid, "borderline", 0.5)
    pending = db.list_reviews()
    assert [r["id"] for r in pending] == [rid]
    assert pending[0]["title"] == "Xe đạp"
    assert db.decide_review(rid, "approved", "mod1", "ok") == "published"
    assert db.get_listing(lid)["status"] == "published"
    assert db.get_review(rid)["status"] == "approved"
    assert db.list_reviews() == []
    assert [r["id"] for r in db.list_reviews("approved")] == [rid]
    assert db.list_audit(lid)[-1]["action"] == "review_approved"


def test_review_decided_twice_raises(seller: int) -> None:
    lid = _in_review_listing(seller)
    rid = db.create_review(lid, "x", 0.5)
    db.decide_review(rid, "rejected", "mod1")
    with pytest.raises(db.ReviewAlreadyDecidedError):
        db.decide_review(rid, "approved", "mod2")
    assert db.get_listing(lid)["status"] == "rejected"


def test_review_bad_decision_and_missing(seller: int) -> None:
    lid = _in_review_listing(seller)
    rid = db.create_review(lid, "x", 0.5)
    with pytest.raises(ValueError):
        db.decide_review(rid, "maybe", "mod1")
    with pytest.raises(LookupError):
        db.decide_review(9999, "approved", "mod1")


def test_review_listing_not_in_review_rolls_back(seller: int) -> None:
    lid = _in_review_listing(seller)
    rid = db.create_review(lid, "x", 0.5)
    db.set_status(lid, "in_review", "rejected")  # bị chuyển bởi luồng khác
    with pytest.raises(db.InvalidTransitionError):
        db.decide_review(rid, "approved", "mod1")
    assert db.get_review(rid)["status"] == "pending"


def test_needs_fix_increments_then_auto_reject(seller: int) -> None:
    lid = _in_review_listing(seller)
    for i in range(1, db.MAX_RESUBMIT + 1):
        rid = db.create_review(lid, "x", 0.5)
        assert db.decide_review(rid, "needs_fix", "mod1") == "needs_fix"
        assert db.get_listing(lid)["resubmit_count"] == i
        _to_status(lid, "awaiting_confirm", "pending_moderation", "in_review")
    rid = db.create_review(lid, "x", 0.5)
    assert db.decide_review(rid, "needs_fix", "mod1") == "rejected"
    assert db.get_listing(lid)["status"] == "rejected"
    assert db.get_review(rid)["status"] == "rejected"


def test_search_candidates_only_published(seller: int) -> None:
    pub = db.create_listing(seller, title="Xe đạp")
    _to_status(pub, "awaiting_confirm", "pending_moderation", "published")
    db.create_listing(seller, title="Nháp")
    rows = db.search_candidates()
    assert [r["id"] for r in rows] == [pub]
    assert rows[0]["seller_name"] == "Chị Lan"
