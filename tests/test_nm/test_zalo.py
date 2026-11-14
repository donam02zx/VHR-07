"""T05 — channels/zalo.py: parse_update bằng mẫu thật, cắt 2000 ký tự, sim, HTTP giả (MockTransport)."""

import copy
import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.channels import zalo
from src.channels.zalo import Inbound, ZaloApiError, ZaloClient, ZaloParseError, parse_update, split_text
from src.config import Settings

SAMPLES = Path(__file__).resolve().parents[2] / "docs" / "nm" / "samples"
TOKEN = "123456:secret-token"


def sample(name: str) -> dict[str, Any]:
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


def event(name: str) -> dict[str, Any]:
    return copy.deepcopy(sample(name)["result"])


def sim_settings() -> Settings:
    return Settings(_env_file=None, channel_mode="sim", zalo_bot_token="")


def zalo_client(handler: Any) -> ZaloClient:
    settings = Settings(_env_file=None, channel_mode="zalo", zalo_bot_token=TOKEN)
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ZaloClient(settings, http=http, retry_delay_s=0)


# ------------------------------------------------------------ parse_update (mẫu thật)
def test_parse_text_sample() -> None:
    assert parse_update(event("update_text.json")) == Inbound(
        event_key="zalo:e9f34d27b47be522bc6d",
        chat_id="c0db7966bd32546c0d23",
        user_id="c0db7966bd32546c0d23",
        display_name="Nguoi Dung Mau",
        text="Xin chào",
        image_ref=None,
        is_group=False,
    )


def test_parse_photo_sample() -> None:
    inbound = parse_update(event("update_photo.json"))
    assert inbound is not None
    assert inbound.event_key == "zalo:6058be145576042f5d60"
    assert inbound.text == "Xe đạp còn mới"
    assert inbound.image_ref.startswith("https://") and inbound.image_ref.endswith(".jpg")
    assert inbound.chat_id == inbound.user_id


def test_parse_photo_without_caption() -> None:
    raw = event("update_photo.json")
    del raw["message"]["caption"]
    inbound = parse_update(raw)
    assert inbound.text == ""
    assert inbound.image_ref is not None


@pytest.mark.parametrize("event_name", ["message.sticker.received", "message.file.received", None])
def test_unsupported_event_returns_none(event_name: str | None) -> None:
    raw = event("update_text.json")
    raw["event_name"] = event_name
    assert parse_update(raw) is None


def test_unknown_chat_type_ignored() -> None:
    raw = event("update_text.json")
    raw["message"]["chat"]["chat_type"] = "CHANNEL"
    assert parse_update(raw) is None


# Mẫu nhóm thật (đã che): ảnh có @nhắc bot — Zalo chỉ gửi tin nhóm có @nhắc (05)
def test_group_photo_mention_sample() -> None:
    inbound = parse_update(event("update_group_photo_mention.json"), "Bot CHỢ CƯ DÂN AI")
    assert inbound is not None
    assert inbound.is_group is True
    assert inbound.chat_id.startswith("zgr-")
    assert inbound.user_id == "aaaabbbbccccdddd0000"
    assert inbound.text == "tao muốn bán điện thoại"
    assert inbound.image_ref is not None


def test_group_text_mention_stripped_anywhere_case_insensitive() -> None:
    raw = event("update_text.json")
    raw["message"]["chat"] = {"id": "zgr-abc", "chat_type": "GROUP"}
    raw["message"]["text"] = "tìm laptop @bot chợ cư dân ai  dưới 5tr"
    inbound = parse_update(raw, "Bot CHỢ CƯ DÂN AI")
    assert inbound is not None and inbound.text == "tìm laptop dưới 5tr"
    assert inbound.chat_id == "zgr-abc" and inbound.user_id != "zgr-abc"


def test_strip_mention_without_bot_name_keeps_text() -> None:
    assert zalo.strip_mention("  @Bot X tìm laptop ", None) == "@Bot X tìm laptop"


def test_client_parse_update_uses_bot_name() -> None:
    c = ZaloClient(Settings(_env_file=None, channel_mode="sim"))
    c.bot_name = "Bot CHỢ CƯ DÂN AI"
    inbound = c.parse_update(event("update_group_photo_mention.json"))
    assert inbound is not None and inbound.text == "tao muốn bán điện thoại"


def test_bot_sender_ignored() -> None:
    raw = event("update_text.json")
    raw["message"]["from"]["is_bot"] = True
    assert parse_update(raw) is None


@pytest.mark.parametrize(
    ("sample_name", "path"),
    [
        ("update_text.json", ("message", "text")),
        ("update_text.json", ("message", "message_id")),
        ("update_text.json", ("message", "chat")),
        ("update_text.json", ("message", "from")),
        ("update_photo.json", ("message", "photo_url")),
        ("update_photo.json", ("message",)),
    ],
)
def test_missing_required_field_raises(sample_name: str, path: tuple[str, ...]) -> None:
    raw = event(sample_name)
    target = raw
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    with pytest.raises(ZaloParseError):
        parse_update(raw)


# ------------------------------------------------------------ split_text
def test_split_short_text_single_chunk() -> None:
    assert split_text("xin chào") == ["xin chào"]


def test_split_exact_limit() -> None:
    assert split_text("a" * 2000) == ["a" * 2000]


def test_split_hard_cut() -> None:
    chunks = split_text("a" * 4500)
    assert [len(c) for c in chunks] == [2000, 2000, 500]
    assert "".join(chunks) == "a" * 4500


def test_split_prefers_newline() -> None:
    text = "x" * 1500 + "\n" + "y" * 1000
    assert split_text(text) == ["x" * 1500, "y" * 1000]


def test_split_all_chunks_within_limit() -> None:
    text = " ".join(["từ"] * 3000)
    chunks = split_text(text)
    assert all(len(c) <= 2000 for c in chunks)
    assert " ".join(chunks).split() == text.split()


def test_split_empty_raises() -> None:
    with pytest.raises(ValueError):
        split_text("")


# ------------------------------------------------------------ chế độ sim
async def test_sim_records_sent_and_splits() -> None:
    client = ZaloClient(sim_settings())
    await client.send_text("c1", "a" * 2500)
    assert [(s.kind, s.chat_id, len(s.text)) for s in client.sent] == [("text", "c1", 2000), ("text", "c1", 500)]


async def test_sim_send_photo_recorded() -> None:
    client = ZaloClient(sim_settings())
    await client.send_photo("c1", "img.jpg", "cap")
    assert client.sent[0].kind == "photo" and client.sent[0].photo == "img.jpg"


async def test_sim_get_updates_from_inbox() -> None:
    client = ZaloClient(sim_settings())
    assert await client.get_updates() == []
    client.push_update(event("update_text.json"))
    updates = await client.get_updates()
    assert len(updates) == 1
    assert client.parse_update(updates[0]).text == "Xin chào"
    assert await client.get_updates() == []


async def test_sim_download_local_file(tmp_path: Path) -> None:
    img = tmp_path / "a.jpg"
    img.write_bytes(b"\xff\xd8data")
    client = ZaloClient(sim_settings())
    assert await client.download_image(str(img)) == b"\xff\xd8data"
    with pytest.raises(FileNotFoundError):
        await client.download_image("https://example.com/x.jpg")


# ------------------------------------------------------------ chế độ zalo (HTTP giả)
async def test_get_updates_returns_single_event_as_list() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert req.url.path == f"/bot{TOKEN}/getUpdates"
        return httpx.Response(200, json=sample("update_text.json"))

    updates = await zalo_client(handler).get_updates()
    assert len(updates) == 1 and updates[0]["event_name"] == "message.text.received"


@pytest.mark.parametrize("status", [200, 408])
async def test_get_updates_408_is_empty(status: int) -> None:
    body = {"ok": False, "description": "Request timeout", "error_code": 408}
    client = zalo_client(lambda req: httpx.Response(status, json=body))
    assert await client.get_updates() == []


async def test_get_updates_other_error_raises() -> None:
    body = {"ok": False, "description": "Unauthorized", "error_code": 401}
    client = zalo_client(lambda req: httpx.Response(401, json=body))
    with pytest.raises(ZaloApiError) as exc:
        await client.get_updates()
    assert exc.value.code == 401


async def test_send_text_body_and_split() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == f"/bot{TOKEN}/sendMessage"
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": "m", "date": 1, "message_type": "x"}})

    await zalo_client(handler).send_text("c1", "b" * 2001)
    assert [set(b) for b in bodies] == [{"chat_id", "text"}] * 2
    assert [len(b["text"]) for b in bodies] == [2000, 1]


async def test_send_text_api_error_raises() -> None:
    body = {"ok": False, "description": "The chat_id must not be empty", "error_code": 400}
    client = zalo_client(lambda req: httpx.Response(400, json=body))
    with pytest.raises(ZaloApiError, match="chat_id"):
        await client.send_text("", "hi")


async def test_retry_5xx_then_success() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(502)
        return httpx.Response(200, json={"ok": True, "result": {"id": "b"}})

    assert (await zalo_client(handler).get_me())["id"] == "b"
    assert calls["n"] == 3


async def test_retry_network_error_gives_up_after_two_retries(caplog: pytest.LogCaptureFixture) -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("boom", request=req)

    caplog.set_level(logging.DEBUG)
    with pytest.raises(ZaloApiError) as exc:
        await zalo_client(handler).get_updates()
    assert calls["n"] == 1 + zalo.MAX_RETRIES
    assert "secret-token" not in caplog.text
    assert "secret-token" not in str(exc.value)


async def test_send_photo_body_matches_verified_sample() -> None:
    sample_body = sample("sendPhoto.json")
    bodies: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == f"/bot{TOKEN}/sendPhoto"
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json={k: v for k, v in sample_body.items() if not k.startswith("_")})

    client = zalo_client(handler)
    await client.send_photo("c1", "https://photo/x.jpg", "Tin #13")
    await client.send_photo("c1", "https://photo/y.jpg")
    assert set(bodies[0]) == set(sample_body["_request_body"]) == {"chat_id", "photo", "caption"}
    assert bodies[0] == {"chat_id": "c1", "photo": "https://photo/x.jpg", "caption": "Tin #13"}
    assert bodies[1] == {"chat_id": "c1", "photo": "https://photo/y.jpg"}
    with pytest.raises(ValueError):
        await client.send_photo("c1", "")


async def test_download_image_get() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "GET"
        return httpx.Response(200, content=b"jpgbytes")

    assert await zalo_client(handler).download_image("https://photo.example/x.jpg") == b"jpgbytes"
