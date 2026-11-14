"""T08 — API duyệt tay + trang /console (kênh sim, DB tạm, không mạng)."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.api import reviews
from src.channels.zalo import ZaloClient
from src.config import Settings
from src.main import app
from src.services import db, posting

TOKEN = "console-secret"
SELLER = "zalo-seller-1"


@pytest.fixture(autouse=True)
def tmp_db(tmp_path: Path) -> None:
    db.reset_for_tests(tmp_path / "nm.db")


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    s = Settings(_env_file=None, channel_mode="sim", console_token=TOKEN, zalo_group_chat_id="")
    monkeypatch.setattr(reviews, "get_settings", lambda: s)
    monkeypatch.setattr(posting, "get_settings", lambda: s)
    return s


@pytest.fixture
def channel(settings: Settings) -> ZaloClient:
    return ZaloClient(settings)


@pytest_asyncio.fixture
async def api(channel: ZaloClient) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[reviews.get_channel] = lambda: channel
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


H = {"X-Console-Token": TOKEN}


def in_review(title: str = "Nồi cơm", resubmits: int = 0) -> tuple[int, int]:
    seller = db.upsert_user(SELLER, "Lan")
    lid = db.create_listing(seller, title=title, description="Đặt cọc trước", price_vnd=300_000,
                            condition="Cũ", image_ref="https://img/x.jpg")
    for frm, to in (("draft", "awaiting_confirm"), ("awaiting_confirm", "pending_moderation"),
                    ("pending_moderation", "in_review")):
        assert db.set_status(lid, frm, to)
    for _ in range(resubmits):
        rid = db.create_review(lid, "x", 0.5)
        db.decide_review(rid, "needs_fix", "t")
        for frm, to in (("needs_fix", "awaiting_confirm"), ("awaiting_confirm", "pending_moderation"),
                        ("pending_moderation", "in_review")):
            assert db.set_status(lid, frm, to)
    return lid, db.create_review(lid, "Dấu hiệu lừa đảo: đặt cọc", 0.55)


def texts(channel: ZaloClient, chat: str = SELLER) -> list[str]:
    return [s.text for s in channel.sent if s.chat_id == chat]


# ---------------------------------------------------------------- token
@pytest.mark.parametrize("headers", [{}, {"X-Console-Token": "sai"}, {"X-Console-Token": ""}])
async def test_wrong_token_401(api: AsyncClient, headers: dict) -> None:
    lid, rid = in_review()
    assert (await api.get("/api/v1/reviews", headers=headers)).status_code == 401
    r = await api.post(f"/api/v1/reviews/{rid}/decide", json={"decision": "approve"}, headers=headers)
    assert r.status_code == 401
    assert db.get_listing(lid)["status"] == "in_review"


async def test_token_not_configured_503(api: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reviews, "get_settings", lambda: Settings(_env_file=None, console_token=""))
    assert (await api.get("/api/v1/reviews", headers={"X-Console-Token": ""})).status_code == 503


# ---------------------------------------------------------------- list
async def test_list_pending(api: AsyncClient) -> None:
    lid, rid = in_review()
    r = await api.get("/api/v1/reviews?status=pending", headers=H)
    assert r.status_code == 200
    assert r.json() == [
        {
            "id": rid,
            "listing_id": lid,
            "title": "Nồi cơm",
            "description": "Đặt cọc trước",
            "price_vnd": 300_000,
            "image_ref": "https://img/x.jpg",
            "score": 0.55,
            "reason": "Dấu hiệu lừa đảo: đặt cọc",
            "created_at": db.get_review(rid)["created_at"],
        }
    ]


async def test_list_bad_status_422(api: AsyncClient) -> None:
    assert (await api.get("/api/v1/reviews?status=xyz", headers=H)).status_code == 422


# ---------------------------------------------------------------- decide
async def test_approve_publishes_and_notifies(api: AsyncClient, channel: ZaloClient) -> None:
    lid, rid = in_review()
    r = await api.post(f"/api/v1/reviews/{rid}/decide", json={"decision": "approve"}, headers=H)
    assert r.status_code == 200
    assert r.json() == {"review_id": rid, "listing_id": lid, "listing_status": "published", "notified": True}
    assert db.get_listing(lid)["status"] == "published"
    assert texts(channel) == [f"Tin #{lid} đã được đăng."]
    assert db.list_audit(lid)[-1]["action"] == "review_approved"


async def test_approve_posts_to_group(api: AsyncClient, channel: ZaloClient, settings: Settings,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    s = settings.model_copy(update={"zalo_group_chat_id": "group-1"})
    monkeypatch.setattr(posting, "get_settings", lambda: s)
    lid, rid = in_review()
    await api.post(f"/api/v1/reviews/{rid}/decide", json={"decision": "approve"}, headers=H)
    group = texts(channel, "group-1")
    assert len(group) == 1 and f"Tin #{lid}" in group[0] and "Lan" not in group[0]


async def test_reject_notifies_reason(api: AsyncClient, channel: ZaloClient) -> None:
    lid, rid = in_review()
    r = await api.post(f"/api/v1/reviews/{rid}/decide", json={"decision": "reject", "note": "nghi lừa đảo"},
                       headers=H)
    assert r.json()["listing_status"] == "rejected"
    assert texts(channel) == [f"Tin #{lid} không được đăng: nghi lừa đảo."]


async def test_decide_twice_409(api: AsyncClient, channel: ZaloClient) -> None:
    lid, rid = in_review()
    url = f"/api/v1/reviews/{rid}/decide"
    assert (await api.post(url, json={"decision": "reject"}, headers=H)).status_code == 200
    r = await api.post(url, json={"decision": "approve"}, headers=H)
    assert r.status_code == 409
    assert db.get_listing(lid)["status"] == "rejected"
    assert len(texts(channel)) == 1


async def test_decide_missing_404(api: AsyncClient) -> None:
    r = await api.post("/api/v1/reviews/999/decide", json={"decision": "approve"}, headers=H)
    assert r.status_code == 404


async def test_decide_bad_body_422(api: AsyncClient) -> None:
    lid, rid = in_review()
    r = await api.post(f"/api/v1/reviews/{rid}/decide", json={"decision": "maybe"}, headers=H)
    assert r.status_code == 422


async def test_needs_fix_reopens_draft_then_ok(api: AsyncClient, channel: ZaloClient) -> None:
    lid, rid = in_review(title="Xe đạp")
    r = await api.post(f"/api/v1/reviews/{rid}/decide", json={"decision": "needs_fix", "note": "bỏ chữ đặt cọc"},
                       headers=H)
    assert r.json()["listing_status"] == "awaiting_confirm"
    row = db.get_listing(lid)
    assert row["status"] == "awaiting_confirm"
    assert row["resubmit_count"] == 1
    conv = db.get_conversation(SELLER)
    assert conv == {**conv, "state": "awaiting_confirm", "listing_id": lid}
    msg = texts(channel)[0]
    assert "cần sửa" in msg and "bỏ chữ đặt cọc" in msg and f"Bản nháp tin #{lid}" in msg


async def test_needs_fix_over_limit_rejects(api: AsyncClient, channel: ZaloClient) -> None:
    lid, rid = in_review(resubmits=db.MAX_RESUBMIT)
    r = await api.post(f"/api/v1/reviews/{rid}/decide", json={"decision": "needs_fix"}, headers=H)
    assert r.json()["listing_status"] == "rejected"
    assert db.get_listing(lid)["status"] == "rejected"
    assert texts(channel)[0].startswith(f"Tin #{lid} không được đăng")


async def test_notify_failure_keeps_decision(api: AsyncClient, channel: ZaloClient,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(chat_id: str, text: str) -> None:
        raise RuntimeError("zalo down")

    monkeypatch.setattr(channel, "send_text", fail)
    lid, rid = in_review()
    r = await api.post(f"/api/v1/reviews/{rid}/decide", json={"decision": "approve"}, headers=H)
    assert r.status_code == 200 and r.json()["notified"] is False
    assert db.get_listing(lid)["status"] == "published"


# ---------------------------------------------------------------- console
async def test_console_page_served(api: AsyncClient) -> None:
    r = await api.get("/console")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Hàng chờ duyệt" in r.text and "/api/v1/reviews" in r.text and "X-Console-Token" in r.text
