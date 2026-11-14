"""T09 — poller với client giả: gọi handler, bỏ trùng, handler lỗi không dừng vòng lặp, backoff."""

import asyncio
import copy
import json
from pathlib import Path
from typing import Any

import pytest

from src.channels.poller import Poller, next_backoff
from src.channels.zalo import Inbound, ZaloApiError, parse_update
from src.services import db

SAMPLE = Path(__file__).resolve().parents[2] / "docs" / "nm" / "samples" / "update_text.json"


@pytest.fixture(autouse=True)
def tmp_db(tmp_path: Path) -> None:
    db.reset_for_tests(tmp_path / "nm.db")


def update(message_id: str, text: str = "hi") -> dict[str, Any]:
    raw = copy.deepcopy(json.loads(SAMPLE.read_text(encoding="utf-8"))["result"])
    raw["message"]["message_id"] = message_id
    raw["message"]["text"] = text
    return raw


class FakeSource:
    """Phát lần lượt từng "lượt" get_updates (list hoặc Exception); hết kịch bản → dừng poller."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls = 0
        self.poller: Poller | None = None

    async def get_updates(self) -> list[dict[str, Any]]:
        self.calls += 1
        if not self.script:
            assert self.poller is not None
            self.poller._stop.set()
            return []
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def parse_update(self, raw: dict[str, Any]) -> Inbound | None:
        return parse_update(raw)


class Recorder:
    def __init__(self, fail_on: set[str] | None = None) -> None:
        self.seen: list[str] = []
        self.fail_on = fail_on or set()

    async def __call__(self, inbound: Inbound) -> None:
        self.seen.append(inbound.event_key)
        if inbound.text in self.fail_on:
            raise RuntimeError("handler boom")


class SleepLog:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, s: float) -> None:
        self.delays.append(s)


async def run(script: list[Any], handler: Recorder) -> tuple[FakeSource, SleepLog]:
    source = FakeSource(script)
    sleep = SleepLog()
    p = Poller(source, handler, sleep=sleep)
    source.poller = p
    await asyncio.wait_for(p.run(), timeout=5)
    return source, sleep


async def test_three_updates_three_handler_calls() -> None:
    h = Recorder()
    await run([[update("m1")], [update("m2")], [update("m3")]], h)
    assert h.seen == ["zalo:m1", "zalo:m2", "zalo:m3"]


async def test_duplicate_update_skipped() -> None:
    h = Recorder()
    await run([[update("m1")], [update("m1")], [update("m2")], [update("m1")]], h)
    assert h.seen == ["zalo:m1", "zalo:m2"]


async def test_handler_error_does_not_stop_loop(caplog: pytest.LogCaptureFixture) -> None:
    h = Recorder(fail_on={"boom"})
    await run([[update("m1", "boom")], [update("m2")], [update("m3", "boom")], [update("m4")]], h)
    assert h.seen == ["zalo:m1", "zalo:m2", "zalo:m3", "zalo:m4"]
    assert "zalo:m1" in caplog.text and "handler lỗi" in caplog.text


async def test_empty_and_unsupported_updates_ignored() -> None:
    sticker = update("m9")
    sticker["event_name"] = "message.sticker.received"
    broken = update("m8")
    del broken["message"]["text"]
    h = Recorder()
    await run([[], [sticker], [broken], [update("m1")]], h)
    assert h.seen == ["zalo:m1"]


async def test_network_error_backoff_then_resets() -> None:
    err = ZaloApiError("getUpdates", None, "lỗi mạng")
    h = Recorder()
    _, sleep = await run([err, err, err, [update("m1")], err], h)
    assert h.seen == ["zalo:m1"]
    backoffs = [d for d in sleep.delays if d > 0]
    assert backoffs == [1.0, 2.0, 4.0, 1.0]


@pytest.mark.parametrize(
    ("current", "expected"),
    [(None, 1.0), (1.0, 2.0), (2.0, 4.0), (16.0, 30.0), (30.0, 30.0)],
)
def test_next_backoff(current: float | None, expected: float) -> None:
    assert next_backoff(current) == expected


async def test_start_stop_cancels_hanging_get_updates() -> None:
    class Hanging(FakeSource):
        async def get_updates(self) -> list[dict[str, Any]]:
            await asyncio.sleep(3600)
            return []

    p = Poller(Hanging([]), Recorder())
    p.start()
    await asyncio.sleep(0)
    with pytest.raises(RuntimeError):
        p.start()
    await asyncio.wait_for(p.stop(), timeout=2)
    await p.stop()  # gọi lại vô hại


async def test_lifespan_starts_poller_only_in_zalo_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from src import main
    from src.config import Settings

    started: list[str] = []

    class SpyPoller:
        def __init__(self, *a: Any, **k: Any) -> None: ...
        def start(self) -> None:
            started.append("start")

        async def stop(self) -> None:
            started.append("stop")

    monkeypatch.setattr(main, "Poller", SpyPoller)
    monkeypatch.setattr(db, "init_db", lambda: None)
    for mode, expected in (("sim", []), ("zalo", ["start", "stop"])):
        started.clear()
        s = Settings(_env_file=None, channel_mode=mode, zalo_bot_token="1:x")
        monkeypatch.setattr(main, "get_settings", lambda s=s: s)
        async with main.lifespan(main.app):
            pass
        assert started == expected, mode


# ---------------------------------------------------------------- lưu mẫu chưa kiểm chứng
def group_update(message_id: str) -> dict[str, Any]:
    raw = update(message_id)
    raw["message"]["chat"]["chat_type"] = "GROUP"
    return raw


def test_capture_saves_only_unverified_and_stops_at_limit(tmp_path: Path) -> None:
    from src.channels.sample_capture import SampleCapture

    cap = SampleCapture(2, tmp_path / "cap")
    assert cap(update("p1")) is None  # PRIVATE text đã kiểm chứng → không lưu
    first = cap(group_update("g1"))
    assert first is not None and first.name == "01_message_text_received_GROUP.json"
    assert json.loads(first.read_text(encoding="utf-8"))["message"]["message_id"] == "g1"
    assert cap({"event_name": "group.member.joined"}) is not None  # loại lạ cũng lưu
    assert cap(group_update("g2")) is None  # hết hạn mức
    assert len(list((tmp_path / "cap").iterdir())) == 2


async def test_poller_calls_capture_and_capture_error_does_not_block() -> None:
    seen: list[str] = []

    def boom(raw: dict[str, Any]) -> None:
        seen.append(raw["message"]["message_id"])
        raise RuntimeError("disk full")

    handled: list[str] = []

    async def handler(inbound: Inbound) -> None:
        handled.append(inbound.event_key)

    p = Poller(FakeSource([]), handler, capture=boom)
    assert await p.process(update("m1")) is True
    assert seen == ["m1"] and handled == ["zalo:m1"]
