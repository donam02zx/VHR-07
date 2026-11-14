"""Client Zalo Bot API + chế độ sim (docs/nm/05, mục "ĐÃ KIỂM CHỨNG").

Vì sao `get_updates` trả list dù API trả MỘT object: poller xử lý đồng nhất, và
"chưa có tin" (error_code 408) chỉ là list rỗng, không phải lỗi.
Token nằm trong URL nên: tắt log INFO của httpx và không bao giờ log chuỗi lỗi chưa che.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from src.config import Settings, get_settings

logger = logging.getLogger("nm.zalo")
# httpx log "HTTP Request: POST <url>" ở INFO — URL chứa token.
logging.getLogger("httpx").setLevel(logging.WARNING)

API_BASE = "https://bot-api.zaloplatforms.com"
MAX_TEXT = 2000
MAX_RETRIES = 2
EVENT_TEXT = "message.text.received"
EVENT_IMAGE = "message.image.received"
CHAT_PRIVATE = "PRIVATE"
NO_UPDATE_CODE = 408


class ZaloParseError(ValueError):
    """Sự kiện loại đã hỗ trợ nhưng thiếu/sai trường — không đoán, báo lỗi tường minh."""


class ZaloApiError(RuntimeError):
    """API trả ok=false (khác 408 của getUpdates) hoặc HTTP lỗi sau khi đã thử lại."""

    def __init__(self, method: str, code: int | None, description: str) -> None:
        super().__init__(f"{method}: [{code}] {description}")
        self.method, self.code, self.description = method, code, description


@dataclass
class Inbound:
    """Tin đến đã chuẩn hoá."""

    event_key: str
    chat_id: str
    user_id: str
    display_name: str | None
    text: str
    image_ref: str | None
    is_group: bool


@dataclass
class Sent:
    """Tin bot gửi đi, ghi lại ở chế độ sim."""

    kind: str  # "text" | "photo"
    chat_id: str
    text: str
    photo: str | None = None


def split_text(text: str, limit: int = MAX_TEXT) -> list[str]:
    """Cắt thành đoạn ≤ limit ký tự; ưu tiên cắt ở xuống dòng, rồi dấu cách, cuối cùng cắt cứng."""
    if not text:
        raise ValueError("Không gửi tin rỗng")
    chunks: list[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[:limit]
        cut = window.rfind("\n")
        if cut <= 0:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip("\n ")
    if rest:
        chunks.append(rest)
    return chunks


def _require(obj: dict[str, Any], key: str, where: str) -> Any:
    value = obj.get(key)
    if value is None or value == "":
        raise ZaloParseError(f"thiếu {where}.{key}")
    return value


def parse_update(raw: dict[str, Any]) -> Inbound | None:
    """Chuẩn hoá MỘT sự kiện (`result` của getUpdates).

    None: loại tin chưa hỗ trợ, chat không phải PRIVATE (nhóm chưa kiểm chứng), hoặc tin từ bot.
    ZaloParseError: loại tin hỗ trợ nhưng thiếu trường bắt buộc.
    """
    event = raw.get("event_name")
    if event not in (EVENT_TEXT, EVENT_IMAGE):
        logger.info("bỏ qua sự kiện chưa hỗ trợ: %s", event)
        return None
    msg = raw.get("message")
    if not isinstance(msg, dict):
        raise ZaloParseError("thiếu message")
    chat = msg.get("chat")
    sender = msg.get("from")
    if not isinstance(chat, dict) or not isinstance(sender, dict):
        raise ZaloParseError("thiếu message.chat hoặc message.from")
    message_id = str(_require(msg, "message_id", "message"))
    chat_type = _require(chat, "chat_type", "message.chat")
    if chat_type != CHAT_PRIVATE:
        logger.warning("bỏ qua chat_type=%s (chưa kiểm chứng) msg=%s", chat_type, message_id)
        return None
    if sender.get("is_bot") is True:
        return None
    if event == EVENT_TEXT:
        text = str(_require(msg, "text", "message"))
        image_ref = None
    else:
        image_ref = str(_require(msg, "photo_url", "message"))
        text = str(msg.get("caption") or "")
    return Inbound(
        event_key=f"zalo:{message_id}",
        chat_id=str(_require(chat, "id", "message.chat")),
        user_id=str(_require(sender, "id", "message.from")),
        display_name=sender.get("display_name"),
        text=text,
        image_ref=image_ref,
        is_group=False,
    )


class ZaloClient:
    """Gọi Zalo Bot API (mode "zalo") hoặc giả lập trong bộ nhớ (mode "sim")."""

    def __init__(
        self,
        settings: Settings | None = None,
        http: httpx.AsyncClient | None = None,
        retry_delay_s: float = 0.5,
    ) -> None:
        self._settings = settings or get_settings()
        self.mode = self._settings.channel_mode
        self._token = self._settings.zalo_bot_token
        self._http = http
        self._retry_delay_s = retry_delay_s
        self.sent: list[Sent] = []  # sim: tin đã gửi
        self.inbox: deque[dict[str, Any]] = deque()  # sim: sự kiện chờ get_updates

    # ------------------------------------------------------------ hạ tầng
    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(15.0, read=65.0))
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()

    async def _call(self, method: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST tới API; thử lại tối đa MAX_RETRIES khi lỗi mạng/5xx. Trả JSON (kể cả ok=false)."""
        url = f"{API_BASE}/bot{self._token}/{method}"
        client = await self._client()
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = await client.post(url, json=body)
            except httpx.TransportError as exc:
                logger.warning("%s lỗi mạng (%s) lần %d", method, type(exc).__name__, attempt + 1)
                if attempt == MAX_RETRIES:
                    raise ZaloApiError(method, None, f"lỗi mạng: {type(exc).__name__}") from None
            else:
                if resp.status_code < 500:
                    try:
                        data = resp.json()
                    except ValueError:
                        raise ZaloApiError(method, resp.status_code, "phản hồi không phải JSON") from None
                    if not isinstance(data, dict):
                        raise ZaloApiError(method, resp.status_code, "phản hồi JSON không phải object")
                    return data
                logger.warning("%s HTTP %d lần %d", method, resp.status_code, attempt + 1)
                if attempt == MAX_RETRIES:
                    raise ZaloApiError(method, resp.status_code, "lỗi máy chủ")
            await asyncio.sleep(self._retry_delay_s * (2**attempt))
        raise AssertionError("unreachable")

    @staticmethod
    def _check_ok(method: str, data: dict[str, Any]) -> Any:
        if data.get("ok") is not True:
            raise ZaloApiError(method, data.get("error_code"), str(data.get("description", "")))
        return data.get("result")

    # ------------------------------------------------------------ giao diện 05
    async def get_me(self) -> dict[str, Any]:
        if self.mode == "sim":
            return {"id": "sim-bot", "display_name": "NeighborMarket (sim)", "can_join_groups": False}
        return self._check_ok("getMe", await self._call("getMe", {}))

    async def get_updates(self) -> list[dict[str, Any]]:
        """0 hoặc 1 sự kiện. 408 "Request timeout" = chưa có tin → [] (bình thường)."""
        if self.mode == "sim":
            return [self.inbox.popleft()] if self.inbox else []
        data = await self._call("getUpdates", {})
        if data.get("ok") is not True and data.get("error_code") == NO_UPDATE_CODE:
            return []
        result = self._check_ok("getUpdates", data)
        if not isinstance(result, dict):
            raise ZaloApiError("getUpdates", None, f"result không phải object: {type(result).__name__}")
        return [result]

    def parse_update(self, raw: dict[str, Any]) -> Inbound | None:
        return parse_update(raw)

    def push_update(self, raw: dict[str, Any]) -> None:
        """Sim: xếp một sự kiện (dạng `result`) cho get_updates trả về."""
        if self.mode != "sim":
            raise RuntimeError("push_update chỉ dùng ở chế độ sim")
        self.inbox.append(raw)

    async def send_text(self, chat_id: str, text: str) -> None:
        """Gửi chữ, tự cắt đoạn ≤ 2000 ký tự (giới hạn Zalo)."""
        for chunk in split_text(text):
            if self.mode == "sim":
                self.sent.append(Sent("text", chat_id, chunk))
                logger.info("[sim] -> %s: %d ký tự", chat_id, len(chunk))
                continue
            self._check_ok("sendMessage", await self._call("sendMessage", {"chat_id": chat_id, "text": chunk}))

    async def send_photo(self, chat_id: str, photo: str, caption: str = "") -> None:
        if self.mode == "sim":
            self.sent.append(Sent("photo", chat_id, caption, photo))
            return
        # Chưa có mẫu sendPhoto thật (05) — không đoán tên trường.
        raise NotImplementedError("sendPhoto chưa kiểm chứng với Zalo thật")

    async def download_image(self, image_ref: str) -> bytes:
        """Ảnh đến: photo_url tải thẳng bằng GET. Sim: chỉ đọc file cục bộ, không gọi mạng."""
        if self.mode == "sim":
            path = Path(image_ref)
            if not path.is_file():
                raise FileNotFoundError(f"[sim] không có file ảnh cục bộ: {image_ref}")
            return path.read_bytes()
        client = await self._client()
        resp = await client.get(image_ref)
        if resp.status_code != 200:
            raise ZaloApiError("download_image", resp.status_code, "tải ảnh thất bại")
        return resp.content
