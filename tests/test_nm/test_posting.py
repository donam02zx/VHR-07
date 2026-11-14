"""T06 — luồng đăng tin + dispatcher, kênh sim + AI stub + DB tạm."""

from pathlib import Path
from typing import Any

import pytest

from src.channels.zalo import Inbound, ZaloClient
from src.config import Settings
from src.services import ai, db, dispatcher, posting
from src.services.posting import format_vnd, price_from_caption

CHAT = "chat-1"


@pytest.fixture(autouse=True)
def tmp_db(tmp_path: Path) -> None:
    db.reset_for_tests(tmp_path / "nm.db")


@pytest.fixture(autouse=True)
def no_group(monkeypatch: pytest.MonkeyPatch) -> None:
    set_group(monkeypatch, "")


def set_group(monkeypatch: pytest.MonkeyPatch, group: str) -> None:
    settings = Settings(_env_file=None, channel_mode="sim", zalo_group_chat_id=group)
    monkeypatch.setattr(posting, "get_settings", lambda: settings)


@pytest.fixture
def client(tmp_path: Path) -> ZaloClient:
    return ZaloClient(Settings(_env_file=None, channel_mode="sim"))


@pytest.fixture
def image(tmp_path: Path) -> str:
    p = tmp_path / "bike.jpg"
    p.write_bytes(b"\xff\xd8fake")
    return str(p)


_seq = iter(range(1, 10_000))


def msg(text: str = "", image_ref: str | None = None, chat: str = CHAT) -> Inbound:
    return Inbound(
        event_key=f"e{next(_seq)}",
        chat_id=chat,
        user_id=chat,
        display_name="Chị Lan",
        text=text,
        image_ref=image_ref,
        is_group=False,
    )


async def send(client: ZaloClient, inbound: Inbound) -> list[str]:
    before = len(client.sent)
    await dispatcher.handle(inbound, client)
    return [s.text for s in client.sent[before:]]


def current_listing() -> dict[str, Any]:
    conv = db.get_conversation(CHAT)
    assert conv["listing_id"] is not None
    return db.get_listing(conv["listing_id"])


# ---------------------------------------------------------------- hàm thuần
@pytest.mark.parametrize(
    ("caption", "expected"),
    [
        ("Xe đạp còn mới 1tr2", 1_200_000),
        ("Bán nồi cơm 300k, liên hệ", 300_000),
        ("Giá 1.500.000đ", 1_500_000),
        ("Xe đạp còn mới", None),
        ("Mua năm 2020", None),
        ("", None),
    ],
)
def test_price_from_caption(caption: str, expected: int | None) -> None:
    assert price_from_caption(caption) == expected


def test_format_vnd() -> None:
    assert format_vnd(1_200_000) == "1.200.000 đ"


@pytest.mark.parametrize(
    ("inbound", "kind"),
    [
        (msg("hello"), "text"),
        (msg("/tim xe dap"), "command"),
        (msg("  /help"), "command"),
        (msg("", "img.jpg"), "image"),
        (msg("/tim", "img.jpg"), "image"),
    ],
)
def test_classify(inbound: Inbound, kind: str) -> None:
    assert dispatcher.classify(inbound) == kind


# ---------------------------------------------------------------- kịch bản chính
async def test_photo_draft_edit_price_ok_publishes(client: ZaloClient, image: str) -> None:
    out = await send(client, msg("Xe đạp còn mới", image))
    assert len(out) == 1
    draft = out[0]
    assert draft.startswith("Bản nháp tin #")
    assert "Tiêu đề: Xe đạp thể thao đã qua sử dụng" in draft
    assert "Giá gợi ý: 800.000 đ – 1.500.000 đ" in draft
    assert "Giá đăng: 1.150.000 đ (chưa nêu giá" in draft
    assert len(draft) < 2000
    listing = current_listing()
    assert listing["status"] == "awaiting_confirm"
    assert listing["image_ref"] == image
    assert db.get_conversation(CHAT)["state"] == "awaiting_confirm"

    out = await send(client, msg("sửa giá 1tr2"))
    assert "Giá đăng: 1.200.000 đ" in out[0]
    assert current_listing()["price_vnd"] == 1_200_000

    lid = current_listing()["id"]
    out = await send(client, msg("OK"))
    assert out == [f"Tin #{lid} đã được đăng."]
    assert db.get_listing(lid)["status"] == "published"
    assert db.get_listing(lid)["published_at"] is not None
    assert db.get_conversation(CHAT)["state"] == "idle"
    actions = [a["action"] for a in db.list_audit(lid)]
    assert actions[:3] == ["draft_created", "edit_price", "confirmed"]


async def test_caption_price_used(client: ZaloClient, image: str) -> None:
    out = await send(client, msg("Xe đạp 900k", image))
    assert "Giá đăng: 900.000 đ\n" in out[0]
    assert current_listing()["price_vnd"] == 900_000


async def test_huy_withdraws(client: ZaloClient, image: str) -> None:
    await send(client, msg("Xe đạp", image))
    lid = current_listing()["id"]
    out = await send(client, msg("hủy"))
    assert out == [f"Đã huỷ bản nháp tin #{lid}."]
    assert db.get_listing(lid)["status"] == "withdrawn"
    assert db.get_conversation(CHAT)["state"] == "idle"
    # Sau khi huỷ, "ok" không đăng gì.
    assert await send(client, msg("ok")) == [posting.MSG_HINT]


async def test_new_photo_replaces_old_draft(client: ZaloClient, image: str) -> None:
    await send(client, msg("Xe đạp", image))
    old = current_listing()["id"]
    out = await send(client, msg("Nồi cơm điện", image))
    new = current_listing()["id"]
    assert new != old
    assert db.get_listing(old)["status"] == "withdrawn"
    assert db.get_listing(new)["status"] == "awaiting_confirm"
    assert f"Bản nháp tin #{new}" in out[0]
    assert "Tiêu đề: Nồi cơm điện" in out[0]


async def test_edit_title_keeps_accents(client: ZaloClient, image: str) -> None:
    await send(client, msg("Xe đạp", image))
    out = await send(client, msg("Sửa tiêu đề Xe đạp địa hình Giant"))
    assert "Tiêu đề: Xe đạp địa hình Giant" in out[0]


@pytest.mark.parametrize("text", ["sửa giá abc", "sửa giá", "sửa giá 800"])
async def test_bad_price_asks_again(client: ZaloClient, image: str, text: str) -> None:
    await send(client, msg("Xe đạp", image))
    before = current_listing()["price_vnd"]
    out = await send(client, msg(text))
    assert out[0].startswith("Mình chưa hiểu giá")
    assert current_listing()["price_vnd"] == before
    assert current_listing()["status"] == "awaiting_confirm"


async def test_empty_title_rejected(client: ZaloClient, image: str) -> None:
    await send(client, msg("Xe đạp", image))
    assert await send(client, msg("sửa tiêu đề")) == [posting.MSG_BAD_TITLE]


async def test_unknown_text_while_confirming(client: ZaloClient, image: str) -> None:
    await send(client, msg("Xe đạp", image))
    assert await send(client, msg("bao nhiêu vậy")) == [posting.MSG_CONFIRM_HELP]
    assert db.get_conversation(CHAT)["state"] == "awaiting_confirm"


async def test_idle_text_hint(client: ZaloClient) -> None:
    assert await send(client, msg("xin chào")) == [posting.MSG_HINT]
    assert db.get_conversation(CHAT)["state"] == "idle"


async def test_command_does_not_change_state(client: ZaloClient, image: str) -> None:
    await send(client, msg("Xe đạp", image))
    out = await send(client, msg("/tim xe"))
    assert out == ["Chưa có tin phù hợp."]
    assert db.get_conversation(CHAT)["state"] == "awaiting_confirm"


async def test_publish_to_group_masks_phone_and_hides_seller(
    client: ZaloClient, image: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_group(monkeypatch, "group-9")
    await send(client, msg("Xe đạp 1tr", image))
    await send(client, msg("ok"))
    group_msgs = [s.text for s in client.sent if s.chat_id == "group-9"]
    assert len(group_msgs) == 1
    public = group_msgs[0]
    assert "Chị Lan" not in public and CHAT not in public
    assert "1.000.000 đ" in public
    # Tin có SĐT bị kiểm duyệt giữ lại (07), nên kiểm tra che SĐT trực tiếp trên public_text
    # (đường người duyệt approve ở T08 cũng dùng hàm này).
    lid = db.search_candidates()[0]["id"]
    masked = posting.public_text({**db.get_listing(lid), "description": "gọi 0912345678"})
    assert "09xx xxx 678" in masked and "0912345678" not in masked


# ---------------------------------------------------------------- lỗi
async def test_image_download_failure(client: ZaloClient) -> None:
    out = await send(client, msg("Xe đạp", "/khong/co/file.jpg"))
    assert out == [posting.MSG_IMAGE_FAIL]
    assert db.get_conversation(CHAT)["state"] == "idle"


async def test_ai_error_no_listing(client: ZaloClient, image: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(image: bytes | None, caption: str) -> dict:
        raise RuntimeError("model down")

    monkeypatch.setattr(ai, "draft_listing", boom)
    assert await send(client, msg("Xe đạp", image)) == [posting.MSG_AI_BUSY]
    assert db.get_conversation(CHAT)["state"] == "idle"


async def test_ai_bad_shape_no_listing(client: ZaloClient, image: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai, "suggest_price", lambda listing: {"low": "rẻ"})
    assert await send(client, msg("Xe đạp", image)) == [posting.MSG_AI_BUSY]


async def test_ai_error_keeps_existing_draft(client: ZaloClient, image: str, monkeypatch: pytest.MonkeyPatch) -> None:
    await send(client, msg("Xe đạp", image))
    old = current_listing()["id"]
    monkeypatch.setattr(ai, "draft_listing", lambda image, caption: None)
    assert await send(client, msg("Nồi", image)) == [posting.MSG_AI_BUSY]
    assert current_listing()["id"] == old
    assert db.get_listing(old)["status"] == "awaiting_confirm"


async def test_send_failure_does_not_raise(client: ZaloClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(chat_id: str, text: str) -> None:
        raise RuntimeError("network")

    monkeypatch.setattr(client, "send_text", fail)
    replies = await dispatcher.handle(msg("xin chào"), client)
    assert [r.text for r in replies] == [posting.MSG_HINT]
