"""Vòng lặp getUpdates (docs/nm/05 — Poller).

Vì sao đánh dấu `processed_events` TRƯỚC khi gọi handler: Zalo đã lấy sự kiện khỏi hàng đợi khi
trả về (05, ĐÃ KIỂM CHỨNG), nên "xử lý tối đa một lần" là ngữ nghĩa duy nhất làm được; handler lỗi
thì log kèm event_key chứ không thử lại (tránh nhắn trùng cho người dùng).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from src.channels.zalo import Inbound, ZaloParseError
from src.services import db

logger = logging.getLogger("nm.poller")

Handler = Callable[[Inbound], Awaitable[Any]]
Sleep = Callable[[float], Awaitable[None]]

BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 30.0


class UpdateSource(Protocol):
    async def get_updates(self) -> list[dict[str, Any]]: ...
    def parse_update(self, raw: dict[str, Any]) -> Inbound | None: ...


def next_backoff(current: float | None) -> float:
    """1s, 2s, 4s, ... tối đa 30s."""
    return BACKOFF_START_S if current is None else min(current * 2, BACKOFF_MAX_S)


class Poller:
    def __init__(
        self,
        source: UpdateSource,
        handler: Handler,
        sleep: Sleep = asyncio.sleep,
        idle_delay_s: float = 0.0,
        capture: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self._source = source
        self._capture = capture  # lưu mẫu sự kiện chưa kiểm chứng (sample_capture), tắt mặc định
        self._handler = handler
        self._sleep = sleep
        # 0: getUpdates của Zalo đã tự chờ (408 khi hết giờ) → gọi lại ngay; sleep(0) vẫn nhường event loop.
        self._idle_delay_s = idle_delay_s
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def process(self, raw: dict[str, Any]) -> bool:
        """Xử lý một sự kiện thô. True nếu handler đã được gọi. Không bao giờ ném lỗi."""
        if self._capture is not None:
            try:
                self._capture(raw)
            except Exception:
                logger.exception("lưu mẫu lỗi (bỏ qua, vẫn xử lý update)")
        try:
            inbound = self._source.parse_update(raw)
        except ZaloParseError as exc:
            logger.error("update sai dạng, bỏ qua: %s", exc)
            return False
        if inbound is None:
            return False
        if not db.try_mark_event(inbound.event_key):
            logger.info("bỏ qua update trùng event=%s", inbound.event_key)
            return False
        try:
            await self._handler(inbound)
        except Exception:
            logger.exception("handler lỗi event=%s", inbound.event_key)
        return True

    async def run(self) -> None:
        backoff: float | None = None
        while not self._stop.is_set():
            try:
                updates = await self._source.get_updates()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                backoff = next_backoff(backoff)
                logger.warning("get_updates lỗi (%s), thử lại sau %.0fs", type(exc).__name__, backoff)
                await self._sleep(backoff)
                continue
            if backoff is not None:
                logger.info("get_updates hoạt động lại sau lỗi mạng")
            backoff = None
            for raw in updates:
                await self.process(raw)
            await self._sleep(self._idle_delay_s)

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("poller đã chạy")
        self._stop.clear()
        self._task = asyncio.create_task(self.run(), name="nm-poller")
        logger.info("poller bắt đầu")

    async def stop(self) -> None:
        """Dừng: báo cờ rồi huỷ task (getUpdates có thể đang treo chờ tin)."""
        self._stop.set()
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("poller đã dừng")
