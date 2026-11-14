"""T10 — lệnh người dùng + tìm kiếm (DB tạm, kênh sim, không mạng)."""

from pathlib import Path

import pytest

from src.channels.zalo import Inbound, ZaloClient
from src.config import Settings
from src.services import commands, db, dispatcher, posting, search
from src.services.commands import parse_command

OWNER = "zu-owner"
OTHER = "zu-other"
MOD = "zu-mod"


@pytest.fixture(autouse=True)
def tmp_db(tmp_path: Path) -> None:
    db.reset_for_tests(tmp_path / "nm.db")


@pytest.fixture(autouse=True)
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    s = Settings(_env_file=None, channel_mode="sim", zalo_group_chat_id="")
    monkeypatch.setattr(commands, "get_settings", lambda: s)
    monkeypatch.setattr(posting, "get_settings", lambda: s)
    return s


_seq = iter(range(1, 10_000))


def msg(text: str, user: str = OWNER) -> Inbound:
    return Inbound(f"e{next(_seq)}", user, user, "Tên Thật", text, None, False)


async def run(text: str, user: str = OWNER) -> list[str]:
    return [r.text for r in await commands.handle(msg(text, user))]


def make_listing(title: str, description: str = "", status: str = "published", seller: str = OWNER,
                 price: int = 1_200_000) -> int:
    uid = db.upsert_user(seller, "Tên Thật")
    lid = db.create_listing(uid, title=title, description=description, price_vnd=price)
    path = {
        "draft": [],
        "awaiting_confirm": ["awaiting_confirm"],
        "in_review": ["awaiting_confirm", "pending_moderation", "in_review"],
        "published": ["awaiting_confirm", "pending_moderation", "published"],
        "rejected": ["awaiting_confirm", "pending_moderation", "rejected"],
    }[status]
    cur = "draft"
    for nxt in path:
        assert db.set_status(lid, cur, nxt)
        cur = nxt
    return lid


# ---------------------------------------------------------------- parse
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/tim xe dap", ("/tim", "xe dap")),
        ("/TIM   Xe   đạp ", ("/tim", "Xe đạp")),
        ("/tìm xe", ("/tim", "xe")),
        ("  /help", ("/help", "")),
        ("/rut #23", ("/rut", "#23")),
        ("", ("", "")),
    ],
)
def test_parse_command(text: str, expected: tuple[str, str]) -> None:
    assert parse_command(text) == expected


# ---------------------------------------------------------------- tìm kiếm
async def test_tim_without_accents_finds_accented_listing() -> None:
    lid = make_listing("Xe đạp thể thao đã qua sử dụng")
    make_listing("Nồi cơm điện")
    out = await run("/tim xe dap")
    assert out == [f"Tìm thấy 1 tin:\n#{lid} Xe đạp thể thao đã qua sử dụng — 1.200.000 đ"]


async def test_search_only_published_and_ranked() -> None:
    old_two = make_listing("Xe đạp trẻ em", price=450_000)
    one = make_listing("Xe máy cũ")
    new_two = make_listing("Xe đạp địa hình")
    make_listing("Xe đạp nháp", status="awaiting_confirm")
    make_listing("Xe đạp chờ duyệt", status="in_review")
    ids = [r["id"] for r in search.search("xe đạp")]
    assert ids == [new_two, old_two, one]


async def test_search_matches_description_and_limit() -> None:
    for i in range(7):
        make_listing(f"Món {i}", description="còn mới, có xe đạp kèm")
    assert len(search.search("xe dap")) == search.MAX_RESULTS


async def test_search_masks_phone_in_results() -> None:
    lid = make_listing("Xe đạp gọi 0912345678")
    out = (await run("/tim xe dap"))[0]
    assert f"#{lid}" in out
    assert "0912345678" not in out and "09xx xxx 678" in out
    assert "Tên Thật" not in out and OWNER not in out


async def test_search_no_result_and_empty_query() -> None:
    make_listing("Nồi cơm")
    assert await run("/tim tủ lạnh") == [search.MSG_NO_RESULT]
    assert (await run("/tim"))[0].startswith("Gõ /tim")


# ---------------------------------------------------------------- /rut
async def test_rut_by_owner_withdraws() -> None:
    lid = make_listing("Xe đạp")
    assert await run(f"/rut {lid}") == [f"Tin #{lid} đã được gỡ."]
    assert db.get_listing(lid)["status"] == "withdrawn"
    assert search.search("xe dap") == []


async def test_rut_wrong_owner_rejected() -> None:
    lid = make_listing("Xe đạp")
    db.upsert_user(OTHER)
    out = await run(f"/rut {lid}", user=OTHER)
    assert out == [f"Không tìm thấy tin #{lid} của bạn."]
    assert db.get_listing(lid)["status"] == "published"


async def test_rut_missing_and_bad_id() -> None:
    assert await run("/rut 999") == ["Không tìm thấy tin #999 của bạn."]
    assert (await run("/rut abc"))[0].startswith("Gõ /rut")


async def test_rut_non_withdrawable_status() -> None:
    lid = make_listing("Xe đạp", status="rejected")
    assert "không rút được" in (await run(f"/rut {lid}"))[0]
    assert db.get_listing(lid)["status"] == "rejected"


async def test_rut_current_draft_resets_conversation() -> None:
    lid = make_listing("Xe đạp", status="awaiting_confirm")
    db.set_conversation(OWNER, "awaiting_confirm", lid)
    await run(f"/rut #{lid}")
    assert db.get_conversation(OWNER)["state"] == "idle"


async def test_rut_published_notifies_group(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    s = settings.model_copy(update={"zalo_group_chat_id": "group-1"})
    monkeypatch.setattr(commands, "get_settings", lambda: s)
    lid = make_listing("Xe đạp")
    replies = await commands.handle(msg(f"/rut {lid}"))
    assert [(r.chat_id, r.text) for r in replies] == [
        (OWNER, f"Tin #{lid} đã được gỡ."),
        ("group-1", f"Tin #{lid} đã được gỡ."),
    ]


# ---------------------------------------------------------------- khác
async def test_help_and_unknown() -> None:
    assert await run("/help") == [commands.HELP]
    assert await run("/xyz") == [commands.HELP_SHORT]


async def test_unknown_user_created_as_resident() -> None:
    await run("/help", user="zu-new")
    assert db.get_user_by_zalo("zu-new")["role"] == "resident"


async def test_tincuatoi() -> None:
    a = make_listing("Xe đạp")
    b = make_listing("Nồi cơm", status="in_review")
    make_listing("Của người khác", seller=OTHER)
    out = (await run("/tincuatoi"))[0]
    assert out == f"Tin của bạn:\n#{b} Nồi cơm — chờ người duyệt\n#{a} Xe đạp — đã đăng"
    assert (await run("/tincuatoi", user="zu-empty"))[0].startswith("Bạn chưa có tin")


# ---------------------------------------------------------------- moderator
def make_mod() -> None:
    db.upsert_user(MOD, "Mod")
    with db.connect() as conn:
        conn.execute("UPDATE users SET role='moderator' WHERE zalo_user_id=?", (MOD,))


async def test_duyet_requires_moderator() -> None:
    lid = make_listing("Nồi cơm", status="in_review")
    db.create_review(lid, "x", 0.5)
    assert await run(f"/duyet {lid}") == ["Lệnh này chỉ dành cho người duyệt."]
    assert db.get_listing(lid)["status"] == "in_review"


async def test_duyet_by_moderator_publishes_and_notifies_seller() -> None:
    make_mod()
    lid = make_listing("Nồi cơm", status="in_review")
    db.create_review(lid, "x", 0.5)
    replies = await commands.handle(msg(f"/duyet {lid}", user=MOD))
    assert [(r.chat_id, r.text) for r in replies] == [
        (MOD, f"Đã ghi: tin #{lid} → đã đăng."),
        (OWNER, f"Tin #{lid} đã được đăng."),
    ]
    assert db.get_listing(lid)["status"] == "published"
    assert (await run(f"/duyet {lid}", user=MOD)) == [f"Tin #{lid} không có trong hàng chờ duyệt."]


async def test_tuchoi_needs_reason() -> None:
    make_mod()
    lid = make_listing("Nồi cơm", status="in_review")
    db.create_review(lid, "x", 0.5)
    assert (await run(f"/tuchoi {lid}", user=MOD))[0].startswith("Cú pháp")
    replies = await commands.handle(msg(f"/tuchoi {lid} nghi lừa đảo", user=MOD))
    assert replies[1].text == f"Tin #{lid} không được đăng: nghi lừa đảo."
    assert db.get_listing(lid)["status"] == "rejected"


# ---------------------------------------------------------------- dispatcher
async def test_dispatcher_routes_command_and_keeps_state() -> None:
    lid = make_listing("Xe đạp")
    db.set_conversation(OWNER, "awaiting_confirm", make_listing("Nháp", status="awaiting_confirm"))
    client = ZaloClient(Settings(_env_file=None, channel_mode="sim"))
    await dispatcher.handle(msg("/tim xe dap"), client)
    assert f"#{lid} Xe đạp" in client.sent[-1].text
    assert db.get_conversation(OWNER)["state"] == "awaiting_confirm"
