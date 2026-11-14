"""Hiểu câu tự nhiên: bảng ví dụ cho detect/draft_action + luồng qua dispatcher (sim, DB tạm)."""

from pathlib import Path

import pytest

from src.channels.zalo import Inbound, ZaloClient
from src.config import Settings
from src.services import commands, db, dispatcher, posting
from src.services.intent import detect, draft_action, keywords

CHAT = "zu-a"


# ---------------------------------------------------------------- detect (hàm thuần)
@pytest.mark.parametrize(
    ("text", "kind", "query"),
    [
        ("tôi muốn tìm laptop", "search", "laptop"),
        ("toi muon tim laptop", "search", "laptop"),
        ("Có ai bán xe đạp không ạ?", "search", "xe đạp"),
        ("co ai ban xe dap khong", "search", "xe dap"),
        ("cần mua tủ lạnh cũ", "search", "tủ lạnh"),
        ("mình tìm bàn học cho bé", "search", "bàn học bé"),  # "bàn" không bị nhầm thành "bán"/"bạn"
        ("còn nồi chiên không dầu không", "search", "nồi chiên dầu"),
        ("laptop", "search", "laptop"),
        ("tôi muốn bán laptop dell", "sell", "laptop dell"),
        ("cần thanh lý tủ lạnh", "sell", "tủ lạnh"),
        ("Bán xe đạp trẻ em", "sell", "xe đạp trẻ em"),
        ("pass lại máy giặt", "sell", "máy giặt"),
        ("xin chào", "greet", ""),
        ("Hello!", "greet", ""),
        ("cảm ơn nha", "thanks", ""),
        ("hướng dẫn cách đăng tin", "help", ""),
        ("tin của tôi", "my_listings", ""),
        ("các tin mình đã đăng", "my_listings", ""),
    ],
)
def test_detect_kind_and_query(text: str, kind: str, query: str) -> None:
    it = detect(text)
    assert (it.kind, it.query) == (kind, query)


@pytest.mark.parametrize(("text", "lid"), [("xem tin 13", 13), ("tin 13", 13), ("#13", 13), ("xem 7", 7),
                                          ("Xem tin số 5", 5)])
def test_detect_view(text: str, lid: int) -> None:
    it = detect(text)
    assert (it.kind, it.listing_id) == ("view", lid)


@pytest.mark.parametrize(
    ("text", "lid", "question"),
    [("hỏi 13 còn không bạn?", 13, "còn không bạn?"), ("hoi tin 5: giá có bớt không", 5, "giá có bớt không"),
     ("Hỏi #2 xe còn không", 2, "xe còn không")],
)
def test_detect_ask(text: str, lid: int, question: str) -> None:
    it = detect(text)
    assert (it.kind, it.listing_id, it.query) == ("ask", lid, question)


def test_detect_explicit_flag() -> None:
    assert detect("tìm laptop").explicit is True
    assert detect("laptop").explicit is False
    assert detect("").kind == "unknown"
    assert detect("ạ ơi").kind == "unknown"


def test_keywords_keeps_accents_drops_fillers() -> None:
    assert keywords("Tôi muốn tìm cái LAPTOP cũ giá rẻ ạ") == "laptop"


@pytest.mark.parametrize(
    ("text", "action", "rest"),
    [
        ("ok", "confirm", ""), ("OK", "confirm", ""), ("oke", "confirm", ""), ("đăng đi", "confirm", ""),
        ("ừ", "confirm", ""), ("đồng ý", "confirm", ""), ("Ok.", "confirm", ""),
        ("huy", "cancel", ""), ("hủy", "cancel", ""), ("thôi", "cancel", ""), ("không đăng nữa", "cancel", ""),
        ("sửa giá 1tr2", "price", "1tr2"), ("giá 800k", "price", "800k"), ("đổi giá 1.500.000đ", "price", "1.500.000đ"),
        ("1tr2", "price", "1tr2"), ("950k", "price", "950k"),
        ("sửa tiêu đề Xe đạp Giant", "title", "Xe đạp Giant"), ("đổi tên Nồi cơm Sharp", "title", "Nồi cơm Sharp"),
        ("bao nhiêu vậy", "none", ""), ("tìm laptop", "none", ""), ("800", "none", ""),
    ],
)
def test_draft_action(text: str, action: str, rest: str) -> None:
    assert draft_action(text) == (action, rest)


# ---------------------------------------------------------------- qua dispatcher
@pytest.fixture(autouse=True)
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db.reset_for_tests(tmp_path / "nm.db")
    s = Settings(_env_file=None, channel_mode="sim", zalo_group_chat_id="")
    monkeypatch.setattr(commands, "get_settings", lambda: s)
    monkeypatch.setattr(posting, "get_settings", lambda: s)


@pytest.fixture
def client() -> ZaloClient:
    return ZaloClient(Settings(_env_file=None, channel_mode="sim"))


_seq = iter(range(1, 10_000))


def msg(text: str = "", image: str | None = None, user: str = CHAT) -> Inbound:
    return Inbound(f"e{next(_seq)}", user, user, "A", text, image, False)


async def say(client: ZaloClient, text: str = "", image: str | None = None, user: str = CHAT) -> list[str]:
    before = len(client.sent)
    await dispatcher.handle(msg(text, image, user), client)
    return [s.text for s in client.sent[before:]]


def published(title: str, seller: str = "zu-seller") -> int:
    uid = db.upsert_user(seller)
    lid = db.create_listing(uid, title=title, description="", price_vnd=5_000_000, condition="Cũ")
    for a, b in (("draft", "awaiting_confirm"), ("awaiting_confirm", "pending_moderation"),
                 ("pending_moderation", "published")):
        assert db.set_status(lid, a, b)
    return lid


async def test_natural_search_finds_listing(client: ZaloClient) -> None:
    lid = published("Laptop Dell Latitude")
    out = await say(client, "tôi muốn tìm laptop")
    assert out[0].startswith("Tìm thấy 1 tin:") and f"#{lid} Laptop Dell Latitude" in out[0]
    assert (await say(client, "có ai bán laptop không"))[0].startswith("Tìm thấy 1 tin:")


async def test_natural_search_no_result(client: ZaloClient) -> None:
    assert (await say(client, "tìm máy ảnh"))[0].startswith('Chưa có tin nào khớp "máy ảnh"')


async def test_natural_sell_guides_to_photo(client: ZaloClient) -> None:
    out = await say(client, "tôi muốn bán laptop dell")
    assert out[0].startswith("Để đăng bán laptop dell, bạn gửi ẢNH")


async def test_greeting_and_ok_without_draft(client: ZaloClient) -> None:
    assert await say(client, "chào bot") == [commands.WELCOME]
    assert await say(client, "ok") == [posting.MSG_NO_DRAFT]


async def test_natural_view_and_ask(client: ZaloClient) -> None:
    lid = published("Laptop Dell")
    assert (await say(client, f"xem tin {lid}"))[0].startswith(f"Tin #{lid}: Laptop Dell")
    await say(client, f"hỏi {lid} còn không bạn?", user="zu-buyer")
    to_seller = [s.text for s in client.sent if s.chat_id == "zu-seller"]
    to_buyer = [s.text for s in client.sent if s.chat_id == "zu-buyer"]
    assert to_seller[-1].startswith(f"Có người hỏi tin #{lid}") and "còn không bạn?" in to_seller[-1]
    assert to_buyer == [f"Đã chuyển câu hỏi tới người bán tin #{lid}. Bot sẽ báo khi có trả lời."]


async def test_draft_natural_price_confirm(client: ZaloClient, tmp_path: Path) -> None:
    img = tmp_path / "a.jpg"
    img.write_bytes(b"x")
    await say(client, "Xe đạp thể thao", str(img))
    assert "Giá đăng: 1.200.000 đ" in (await say(client, "1tr2"))[0]
    assert "Giá đăng: 900.000 đ" in (await say(client, "giá 900k"))[0]
    out = await say(client, "đăng đi")
    assert out[0].endswith("đã được đăng.")


async def test_draft_explicit_search_keeps_draft_and_reminds(client: ZaloClient, tmp_path: Path) -> None:
    published("Laptop Dell")
    img = tmp_path / "a.jpg"
    img.write_bytes(b"x")
    await say(client, "Xe đạp", str(img))
    lid = db.get_conversation(CHAT)["listing_id"]
    out = await say(client, "tìm laptop")
    assert out[0].startswith("Tìm thấy 1 tin:")
    assert out[1] == commands.DRAFT_REMINDER.format(lid=lid)
    assert db.get_conversation(CHAT)["state"] == "awaiting_confirm"
    # Câu mơ hồ khi đang nháp → hướng dẫn, KHÔNG tìm kiếm.
    assert await say(client, "laptop") == [posting.MSG_CONFIRM_HELP]
    assert await say(client, "thôi") == [f"Đã huỷ bản nháp tin #{lid}."]
