"""Agent LLM (LLM giả theo kịch bản — không gọi Gemini), HITL gửi câu hỏi, quay về luật khi agent lỗi."""

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.channels.zalo import Inbound, ZaloClient
from src.config import Settings, get_settings
from src.services import agent, commands, db, dispatcher, posting

BUYER = "zu-buyer"
SELLER = "zu-seller"
PHOTO = "https://photo.zdn.vn/laptop.jpg"


class FakeLLM:
    """Trả lần lượt các AIMessage cho sẵn; ghi lại messages mỗi lượt gọi."""

    def __init__(self, script: list[AIMessage | Exception]) -> None:
        self.script = list(script)
        self.calls: list[list[Any]] = []
        self.tool_names: list[str] = []

    def bind_tools(self, tools: list[Any]) -> "FakeLLM":
        self.tool_names = [t.name for t in tools]
        return self

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        self.calls.append(list(messages))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def call(name: str, args: dict, cid: str = "c1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": cid}])


@pytest.fixture(autouse=True)
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db.reset_for_tests(tmp_path / "nm.db")
    monkeypatch.setenv("NM_AGENT_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-not-used")
    get_settings.cache_clear()
    agent._history.clear()
    agent._pending.clear()


@pytest.fixture
def client() -> ZaloClient:
    return ZaloClient(Settings(_env_file=None, channel_mode="sim"))


def use_llm(monkeypatch: pytest.MonkeyPatch, script: list[AIMessage | Exception]) -> FakeLLM:
    fake = FakeLLM(script)
    monkeypatch.setattr(agent, "llm_factory", lambda: fake)
    return fake


def published(title: str, price: int, description: str = "", image: str | None = None) -> int:
    uid = db.upsert_user(SELLER, "Tên Thật Người Bán")
    lid = db.create_listing(uid, title=title, description=description, price_vnd=price, condition="Cũ 90%",
                            image_ref=image)
    for a, b in (("draft", "awaiting_confirm"), ("awaiting_confirm", "pending_moderation"),
                 ("pending_moderation", "published")):
        assert db.set_status(lid, a, b)
    return lid


_seq = iter(range(1, 10_000))


async def say(client: ZaloClient, text: str, user: str = BUYER) -> list[tuple[str, str, str | None]]:
    before = len(client.sent)
    await dispatcher.handle(Inbound(f"e{next(_seq)}", user, user, "Tên Người Mua", text, None, False), client)
    return [(s.chat_id, s.text, s.photo) for s in client.sent[before:]]


def tool_results(fake: FakeLLM) -> list[dict]:
    return [json.loads(m.content) for m in fake.calls[-1] if isinstance(m, ToolMessage)]


# ---------------------------------------------------------------- tìm qua công cụ
async def test_agent_searches_with_price_filter(client: ZaloClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cheap = published("Laptop Dell Latitude", 4_500_000, "gọi 0912345678")
    published("Laptop Macbook Pro", 15_000_000)
    fake = use_llm(monkeypatch, [
        call("search_listings", {"query": "laptop", "max_price": 5_000_000}),
        AIMessage(content=f"**Có 1 tin** dưới 5 triệu:\n* #{cheap} Laptop Dell Latitude — 4.500.000 đ"),
    ])
    out = await say(client, "có laptop nào dưới 5 triệu không")
    assert out == [(BUYER, f"Có 1 tin dưới 5 triệu:\n- #{cheap} Laptop Dell Latitude — 4.500.000 đ", None)]
    result = tool_results(fake)[0]
    assert [r["id"] for r in result["results"]] == [cheap]
    dumped = json.dumps(result, ensure_ascii=False)
    assert "Tên Thật" not in dumped and SELLER not in dumped and "0912345678" not in dumped
    assert set(fake.tool_names) >= {"search_listings", "get_listing", "ask_seller", "watch_listings"}


async def test_get_listing_sends_photo_first(client: ZaloClient, monkeypatch: pytest.MonkeyPatch) -> None:
    lid = published("Laptop Dell", 4_500_000, "Pin tốt, gọi 0912 345 678", image=PHOTO)
    fake = use_llm(monkeypatch, [call("get_listing", {"listing_id": lid}), AIMessage(content="Tin này pin tốt.")])
    out = await say(client, "laptop dell đó pin sao")
    assert out[0] == (BUYER, f"Tin #{lid}", PHOTO)
    assert out[1][1] == "Tin này pin tốt."
    detail = tool_results(fake)[0]
    assert "09xx xxx 678" in detail["description"] and "0912 345 678" not in detail["description"]


async def test_reply_phone_masked_even_if_llm_leaks(client: ZaloClient, monkeypatch: pytest.MonkeyPatch) -> None:
    use_llm(monkeypatch, [AIMessage(content="Gọi 0987654321 nhé")])
    assert (await say(client, "số người bán là gì"))[0][1] == "Gọi 09xx xxx 321 nhé"


# ---------------------------------------------------------------- HITL: hỏi người bán
async def test_ask_seller_waits_for_confirmation_then_sends(client: ZaloClient,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    lid = published("Laptop Dell", 4_500_000)
    use_llm(monkeypatch, [
        call("ask_seller", {"listing_id": lid, "question": "còn bảo hành không bạn?"}),
        AIMessage(content=f'Mình sẽ hỏi người bán tin #{lid}: "còn bảo hành không bạn?". Gõ "gửi" để gửi.'),
    ])
    out = await say(client, f"hỏi giúp người bán tin {lid} còn bảo hành không")
    assert [c for c, _, _ in out] == [BUYER]  # CHƯA gửi người bán
    assert agent._pending[BUYER].listing_id == lid

    out = await say(client, "gửi")
    assert out[0][0] == SELLER and "còn bảo hành không bạn?" in out[0][1]
    assert out[1] == (BUYER, f"Đã chuyển câu hỏi tới người bán tin #{lid}. Bot sẽ báo khi có trả lời.", None)
    assert BUYER not in agent._pending


async def test_ask_seller_cancel_and_other_text_drops(client: ZaloClient, monkeypatch: pytest.MonkeyPatch) -> None:
    lid = published("Laptop Dell", 4_500_000)
    script = [call("ask_seller", {"listing_id": lid, "question": "còn không?"}), AIMessage(content="Gõ gửi nhé")]
    use_llm(monkeypatch, script * 2 + [AIMessage(content="Bạn cần gì nữa?")])
    await say(client, "hỏi người bán còn không")
    assert await say(client, "thôi") == [(BUYER, "Ok, mình không gửi câu hỏi đó.", None)]
    await say(client, "hỏi người bán còn không")
    await say(client, "à mà thôi để mai")  # câu khác → huỷ chờ, không gửi
    assert all(s.chat_id != SELLER for s in client.sent)


async def test_ask_own_listing_rejected_by_tool(client: ZaloClient, monkeypatch: pytest.MonkeyPatch) -> None:
    lid = published("Laptop Dell", 4_500_000)
    fake = use_llm(monkeypatch, [call("ask_seller", {"listing_id": lid, "question": "x"}),
                                 AIMessage(content="Đây là tin của bạn.")])
    await say(client, "hỏi tin của tôi", user=SELLER)
    assert tool_results(fake)[0] == {"error": "Đây là tin của chính người dùng."}
    assert SELLER not in agent._pending


# ---------------------------------------------------------------- săn tin qua agent → tự nhắn khi có tin
async def test_watch_tool_then_auto_notify_on_publish(client: ZaloClient, monkeypatch: pytest.MonkeyPatch) -> None:
    use_llm(monkeypatch, [call("watch_listings", {"query": "laptop", "max_price": 5_000_000}),
                          AIMessage(content="Đã bật săn laptop dưới 5 triệu.")])
    await say(client, "có laptop dưới 5 triệu thì báo mình")
    assert len(db.list_watches(db.get_user_by_zalo(BUYER)["id"])) == 1
    lid = published("Laptop Asus Vivobook", 4_000_000)
    replies = posting.publish_replies(db.get_listing(lid), SELLER)
    notes = [r for r in replies if r.chat_id == BUYER]
    assert len(notes) == 1 and f"#{lid} Laptop Asus Vivobook" in notes[0].text


# ---------------------------------------------------------------- an toàn: lỗi → luật từ khoá
@pytest.mark.parametrize("failure", ["exception", "too_many_steps", "empty"])
async def test_agent_failure_falls_back_to_rules(client: ZaloClient, monkeypatch: pytest.MonkeyPatch,
                                                 failure: str) -> None:
    lid = published("Laptop Dell", 4_500_000)
    script: list[AIMessage | Exception] = {
        "exception": [RuntimeError("Gemini 503")],
        "too_many_steps": [call("search_listings", {"query": "laptop"}, f"c{i}") for i in range(10)],
        "empty": [AIMessage(content="   ")],
    }[failure]
    use_llm(monkeypatch, script)
    out = await say(client, "tìm laptop")
    assert out[0][1].startswith("Tìm thấy 1 tin:") and f"#{lid}" in out[0][1]


async def test_bad_tool_args_reported_back_to_llm(client: ZaloClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = use_llm(monkeypatch, [call("get_listing", {"listing_id": "không phải số"}),
                                 call("nonexistent_tool", {}, "c2"),
                                 AIMessage(content="Mình chưa tìm được tin đó.")])
    out = await say(client, "xem cái đó")
    assert out == [(BUYER, "Mình chưa tìm được tin đó.", None)]
    results = tool_results(fake)
    assert "error" in results[0] and "error" in results[1]


async def test_history_kept_between_turns(client: ZaloClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = use_llm(monkeypatch, [AIMessage(content="Bạn cần laptop tầm giá nào?"), AIMessage(content="Ok.")])
    await say(client, "mình cần laptop")
    await say(client, "tầm 5 triệu")
    texts = [m.content for m in fake.calls[1]]
    assert "mình cần laptop" in texts and "Bạn cần laptop tầm giá nào?" in texts


async def test_agent_disabled_uses_rules(client: ZaloClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NM_AGENT_ENABLED", "false")
    get_settings.cache_clear()
    fake = use_llm(monkeypatch, [])
    assert await say(client, "xin chào") == [(BUYER, commands.WELCOME, None)]
    assert fake.calls == []


async def test_draft_flow_not_routed_to_agent(client: ZaloClient, monkeypatch: pytest.MonkeyPatch,
                                              tmp_path: Path) -> None:
    fake = use_llm(monkeypatch, [])
    img = tmp_path / "a.jpg"
    img.write_bytes(b"x")
    before = len(client.sent)
    await dispatcher.handle(Inbound("img1", BUYER, BUYER, "A", "Xe đạp", str(img), False), client)
    assert client.sent[before].text.startswith("Bản nháp tin #")
    out = await say(client, "giá 1tr2")
    assert "Giá đăng: 1.200.000 đ" in out[0][1]
    assert fake.calls == []


def test_clean_strips_foreign_script_glitch():
    # Gặp khi thử Gemini thật: "#1 هەر Xe đạp trẻ em"
    out = agent._clean("- #1 هەر Xe đạp trẻ em — 450.000 đ, gọi 0912345678")
    assert "هەر" not in out
    assert "#1 Xe đạp trẻ em — 450.000 đ" in out
    assert "0912345678" not in out
