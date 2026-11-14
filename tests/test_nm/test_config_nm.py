"""T01 — cấu hình NeighborMarket: mặc định an toàn và lỗi tường minh khi sai."""

import pytest
from pydantic import ValidationError

from src.config import Settings, get_settings

NM_ENV = (
    "ZALO_BOT_TOKEN",
    "CHANNEL_MODE",
    "ZALO_GROUP_CHAT_ID",
    "MOD_PUBLISH_BELOW",
    "MOD_REJECT_FROM",
    "CONSOLE_TOKEN",
    "NM_DB_PATH",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for k in NM_ENV:
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_defaults(clean_env: pytest.MonkeyPatch) -> None:
    s = Settings(_env_file=None)
    assert s.channel_mode == "sim"
    assert s.zalo_bot_token == ""
    assert s.zalo_group_chat_id == ""
    assert s.mod_publish_below == 0.3
    assert s.mod_reject_from == 0.8
    assert s.console_token == ""
    assert s.nm_db_path == "data/app.db"


def test_get_settings_exposes_new_fields() -> None:
    s = get_settings()
    for name in ("zalo_bot_token", "channel_mode", "zalo_group_chat_id", "mod_publish_below",
                 "mod_reject_from", "console_token", "nm_db_path"):
        assert hasattr(s, name)


def test_env_override(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CHANNEL_MODE", "zalo")
    clean_env.setenv("ZALO_BOT_TOKEN", "x")
    clean_env.setenv("MOD_PUBLISH_BELOW", "0.2")
    s = Settings(_env_file=None)
    assert s.channel_mode == "zalo"
    assert s.mod_publish_below == 0.2


@pytest.mark.parametrize(
    "env",
    [
        {"CHANNEL_MODE": "telegram"},
        {"CHANNEL_MODE": "zalo"},  # thiếu token
        {"MOD_PUBLISH_BELOW": "0.9", "MOD_REJECT_FROM": "0.5"},
        {"MOD_REJECT_FROM": "1.5"},
        {"MOD_PUBLISH_BELOW": "-0.1"},
    ],
)
def test_invalid_config_rejected(clean_env: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for k, v in env.items():
        clean_env.setenv(k, v)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
