"""Lưu nguyên JSON các sự kiện Zalo CHƯA kiểm chứng (nhóm, loại sự kiện lạ) để viết parser đúng mẫu thật.

Ngoại lệ có chủ đích với quy ước "không log nội dung tin" — người dùng đồng ý 2026-11-14 để kiểm chứng
hành vi trong nhóm (05). Tắt mặc định (`NM_CAPTURE_SAMPLES=0`), tự dừng sau N mẫu, ghi vào thư mục
bị .gitignore; ID/tên phải được che bằng tay trước khi chép mẫu sang `docs/nm/samples/`.
Log chỉ ghi tên file + loại sự kiện, không ghi nội dung.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.channels.zalo import CHAT_PRIVATE, EVENT_IMAGE, EVENT_TEXT

logger = logging.getLogger("nm.capture")

CAPTURE_DIR = Path("docs/nm/samples/captured")


def is_unverified(raw: dict[str, Any]) -> bool:
    """True nếu sự kiện nằm ngoài các mẫu đã kiểm chứng (tin text/ảnh trong chat PRIVATE)."""
    msg = raw.get("message")
    chat = msg.get("chat") if isinstance(msg, dict) else None
    chat_type = chat.get("chat_type") if isinstance(chat, dict) else None
    return raw.get("event_name") not in (EVENT_TEXT, EVENT_IMAGE) or chat_type != CHAT_PRIVATE


class SampleCapture:
    def __init__(self, limit: int, directory: Path = CAPTURE_DIR) -> None:
        self.remaining = limit
        self.directory = directory
        self._count = 0

    def __call__(self, raw: dict[str, Any]) -> Path | None:
        """Lưu `raw` nếu chưa kiểm chứng và còn hạn mức. Trả đường dẫn file đã ghi hoặc None."""
        if self.remaining <= 0 or not is_unverified(raw):
            return None
        msg = raw.get("message") if isinstance(raw.get("message"), dict) else {}
        chat = msg.get("chat") if isinstance(msg.get("chat"), dict) else {}
        event = str(raw.get("event_name") or "unknown").replace(".", "_")
        chat_type = str(chat.get("chat_type") or "nochat")
        self._count += 1
        self.remaining -= 1
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{self._count:02d}_{event}_{chat_type}.json"
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.warning("đã lưu mẫu chưa kiểm chứng: %s (còn %d)", path.name, self.remaining)
        if self.remaining == 0:
            logger.warning("đủ mẫu — ngừng lưu (đặt NM_CAPTURE_SAMPLES=0 để tắt hẳn)")
        return path
