"""Cách ly test NeighborMarket khỏi .env thật: luôn kênh sim, AI stub, agent tắt — không bao giờ gọi mạng."""

import pytest

from src.config import get_settings

SAFE_ENV = {
    "CHANNEL_MODE": "sim",
    "ZALO_GROUP_CHAT_ID": "",
    "NM_AI_MODE": "stub",
    "NM_AGENT_ENABLED": "false",
    "GOOGLE_API_KEY": "",
}


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch: pytest.MonkeyPatch):
    for key, value in SAFE_ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
