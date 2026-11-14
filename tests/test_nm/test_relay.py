"""Chuyển tin ẩn danh /hoi – /tl, /xem kèm ảnh, dispatcher.deliver (notify ok/fail), log tin đến."""

import logging
from pathlib import Path

import pytest

from src.channels.zalo import Inbound, ZaloClient
from src.config import Settings
from src.services import commands, db, dispatcher, posting
from src.services.posting import Reply

SELLER = "zu-seller"
BUYER = "zu-buyer"
OTHER = "zu-other"
PHOTO = "https://photo-stal.zdn.vn/x.jpg"


@pytest.fixture(autouse=True)
def tmp_db(tmp_path: Path) -> None:
    db.reset_for_tests(tmp_path / "nm.db")


@pytest.fixture(autouse=True)
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    s = Settings(_env_file=None, channel_mode="sim", zalo_group_chat_id="")
    monkeypatch.setattr(commands, "get_settings", lambda: s)
    monkeypatch.setattr(posting, "get_settings", lambda: s)
    return s


@pytest.fixture
def client(settings: Settings) -> ZaloClient:
    return ZaloClient(settings)


_seq = iter(range(1, 10_000))


def msg(text: str, user: str) -> Inbound:
    return Inbound(f"e{next(_seq)}", user, user, f"Tên thật {user}", text, None, False)


def listing(status: str = "published", image: str | None = PHOTO, description: str = "Đi ít") -> int:
    uid = db.upsert_user(SELLER, "Chị Bán")
    lid = db.create_listing(uid, title="Xe đạp", description=description, price_vnd=1_200_000,
                            condition="Cũ 80%", image_ref=image)
    path = ["awaiting_confirm", "pending_moderation", "published"] if status == "published" else ["awaiting_confirm"]
    cur = "draft"
    for nxt in path:
        assert db.set_status(lid, cur, nxt)
        cur = nxt
    return lid


async def send(client: ZaloClient, text: str, user: str) -> list[tuple[str, str]]:
    before = len(client.sent)
    await dispatcher.handle(msg(text, user), client)
    return [(s.chat_id, s.text) for s in client.sent[before:]]


# ---------------------------------------------------------------- /xem
async def test_xem_sends_photo_then_text(client: ZaloClient) -> None:
    lid = listing()
    await send(client, f"/xem {lid}", BUYER)
    photo, text = client.sent[-2], client.sent[-1]
    assert (photo.kind, photo.photo, photo.text) == ("photo", PHOTO, f"Tin #{lid}")
    assert text.kind == "text" and text.text.startswith(f"Tin #{lid}: Xe đạp")
    assert f"/hoi {lid}" in text.text
    assert "Liên hệ qua bot" not in text.text


@pytest.mark.parametrize("image", [None, "C:/tmp/local.jpg"])
async def test_xem_without_url_image_text_only(client: ZaloClient, image: str | None) -> None:
    lid = listing(image=image)
    await send(client, f"/xem {lid}", BUYER)
    assert [s.kind for s in client.sent] == ["text"]


# ---------------------------------------------------------------- /hoi → /tl
async def test_full_relay_round_trip_is_anonymous(client: ZaloClient) -> None:
    lid = listing()
    out = await send(client, f"/hoi {lid} còn không bạn? gọi mình 0987654321", BUYER)
    assert [c for c, _ in out] == [SELLER, BUYER]
    to_seller = out[0][1]
    tid = db.get_or_create_thread(lid, db.get_user_by_zalo(BUYER)["id"])["id"]
    assert to_seller.startswith(f"Có người hỏi tin #{lid} (Xe đạp) — mã hỏi {tid}:")
    assert "còn không bạn?" in to_seller and f"/tl {tid}" in to_seller
    assert "0987654321" not in to_seller and "09xx xxx 321" in to_seller
    assert BUYER not in to_seller and "Tên thật" not in to_seller
    assert out[1][1].startswith(f"Đã chuyển câu hỏi tới người bán tin #{lid}")

    out = await send(client, f"/tl {tid} còn bạn ơi, qua lấy lúc 7h", SELLER)
    assert [c for c, _ in out] == [BUYER, SELLER]
    to_buyer = out[0][1]
    assert to_buyer.startswith(f"Người bán tin #{lid} (Xe đạp) trả lời:")
    assert "còn bạn ơi, qua lấy lúc 7h" in to_buyer
    assert SELLER not in to_buyer and "Chị Bán" not in to_buyer
    assert out[1][1] == f"Đã chuyển trả lời (mã hỏi {tid})."
    actions = [a["action"] for a in db.list_audit(lid)]
    assert actions[-2:] == ["relay_ask", "relay_answer"]
    assert all("còn" not in a["detail"] for a in db.list_audit(lid))  # không lưu nội dung


async def test_same_buyer_reuses_thread_other_buyer_new(client: ZaloClient) -> None:
    lid = listing()
    await send(client, f"/hoi {lid} a", BUYER)
    await send(client, f"/hoi {lid} b", BUYER)
    await send(client, f"/hoi {lid} c", OTHER)
    t_buyer = db.get_or_create_thread(lid, db.get_user_by_zalo(BUYER)["id"])["id"]
    t_other = db.get_or_create_thread(lid, db.get_user_by_zalo(OTHER)["id"])["id"]
    assert t_buyer != t_other
    seller_msgs = [s.text for s in client.sent if s.chat_id == SELLER]
    assert [f"mã hỏi {t}" in m for m, t in zip(seller_msgs, [t_buyer, t_buyer, t_other], strict=True)] == [True] * 3


async def test_answer_goes_only_to_right_buyer(client: ZaloClient) -> None:
    lid = listing()
    await send(client, f"/hoi {lid} a", BUYER)
    await send(client, f"/hoi {lid} b", OTHER)
    t_other = db.get_or_create_thread(lid, db.get_user_by_zalo(OTHER)["id"])["id"]
    out = await send(client, f"/tl {t_other} trả lời cho other", SELLER)
    assert out[0][0] == OTHER


@pytest.mark.parametrize(
    ("text", "expected_start"),
    [
        ("/hoi", "Gõ /hoi"),
        ("/hoi 5", "Gõ /hoi"),
        ("/hoi abc còn không", "Gõ /hoi"),
        ("/hoi 999 còn không", "Không tìm thấy tin #999 đang đăng."),
        ("/tl", "Gõ /tl"),
        ("/tl 999 ok", "Không tìm thấy mã hỏi 999"),
    ],
)
async def test_relay_bad_input(client: ZaloClient, text: str, expected_start: str) -> None:
    out = await send(client, text, BUYER)
    assert len(out) == 1 and out[0][1].startswith(expected_start)


async def test_cannot_ask_own_or_unpublished_listing(client: ZaloClient) -> None:
    lid = listing()
    assert (await send(client, f"/hoi {lid} x", SELLER)) == [(SELLER, f"Tin #{lid} là tin của bạn.")]
    draft = listing(status="awaiting_confirm")
    assert (await send(client, f"/hoi {draft} x", BUYER))[0][1] == f"Không tìm thấy tin #{draft} đang đăng."


async def test_only_seller_can_answer(client: ZaloClient) -> None:
    lid = listing()
    await send(client, f"/hoi {lid} a", BUYER)
    tid = db.get_or_create_thread(lid, db.get_user_by_zalo(BUYER)["id"])["id"]
    for intruder in (BUYER, OTHER):
        out = await send(client, f"/tl {tid} giả mạo", intruder)
        assert out == [(intruder, f"Không tìm thấy mã hỏi {tid} cho tin của bạn.")]


async def test_too_long_rejected(client: ZaloClient) -> None:
    lid = listing()
    out = await send(client, f"/hoi {lid} " + "a" * (commands.RELAY_MAX + 1), BUYER)
    assert out[0][1].startswith("Câu hỏi tối đa")


async def test_seller_unreachable_buyer_told_failure(client: ZaloClient, monkeypatch: pytest.MonkeyPatch) -> None:
    lid = listing()
    real_send = client.send_text

    async def send_text(chat_id: str, text: str) -> None:
        if chat_id == SELLER:
            raise RuntimeError("seller never chatted with bot")
        await real_send(chat_id, text)

    monkeypatch.setattr(client, "send_text", send_text)
    out = await send(client, f"/hoi {lid} còn không", BUYER)
    assert out == [(BUYER, f"Chưa gửi được câu hỏi tới người bán tin #{lid}. Bạn thử lại sau nhé.")]


# ---------------------------------------------------------------- deliver + log
async def test_deliver_reports_failure(client: ZaloClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(chat_id: str, text: str) -> None:
        raise RuntimeError("x")

    monkeypatch.setattr(client, "send_text", boom)
    assert await dispatcher.deliver(client, [Reply("c", "t")], None, "ref") is False


async def test_inbound_logged_without_content(client: ZaloClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="nm.dispatcher")
    await send(client, "/tim bí mật 0912345678", BUYER)
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("in event="))
    assert "kind=command cmd=/tim has_image=False" in line
    assert "bí mật" not in caplog.text and "0912345678" not in caplog.text
