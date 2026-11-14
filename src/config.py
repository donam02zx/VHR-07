from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "AI20K Agent"
    app_env: Literal["development", "production", "test"] = "development"
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_host: str = "0.0.0.0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: str = "http://localhost:3000"

    # LLM — cascade router: mỗi task type một model (bài học cost-management:
    # không đốt model mạnh cho việc classify). Judge PHẢI khác model generator
    # để tránh self-preference bias (bài học team 002 — eval judge riêng).
    openai_api_key: str = ""
    model_name: str = "gpt-4o"  # legacy alias cho model_generate
    model_classify: str = "gpt-4o-mini"  # cheap: classify / route / quyết định tool
    model_generate: str = "gpt-4o"  # strong: sinh câu trả lời cuối
    model_judge: str = "gpt-4o-mini"  # judge: khác model_generate mặc định
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)

    # Agent loop — escape hatch chống loop vô hạn (bài học team 011:
    # luôn phải có một đường tới END dù LLM cứ đòi gọi tool mãi)
    agent_max_iterations: int = Field(default=8, ge=1, le=50)

    # Database
    database_url: str = "sqlite:///./data/app.db"

    # Vector Store
    chroma_persist_dir: str = "./data/chroma"

    # NeighborMarket (docs/nm/) — kênh Zalo, ngưỡng kiểm duyệt, trang duyệt.
    # "sim" mặc định để chạy/test không cần token Zalo thật.
    zalo_bot_token: str = ""
    channel_mode: Literal["sim", "zalo"] = "sim"
    zalo_group_chat_id: str = ""
    # Điểm rủi ro < mod_publish_below → đăng; >= mod_reject_from → từ chối; giữa → người duyệt.
    mod_publish_below: float = Field(default=0.3, ge=0.0, le=1.0)
    mod_reject_from: float = Field(default=0.8, ge=0.0, le=1.0)
    console_token: str = ""
    nm_db_path: str = "data/app.db"

    # NeighborMarket AI (Gemini). "stub" = bản giả xác định (mặc định, chạy không cần key).
    google_api_key: str = ""
    nm_ai_mode: Literal["stub", "gemini"] = "stub"  # 4 hàm AI (04): soạn tin từ ảnh, giá, kiểm duyệt, tìm ngữ nghĩa
    nm_agent_enabled: bool = False  # agent LLM gọi công cụ cho câu tự nhiên; lỗi → luật từ khoá
    nm_model: str = "gemini-3.5-flash-lite"  # đọc ảnh + gọi công cụ (đo 2026-11-14: 1–10s; bản flash 16s+ hoặc quá giờ)
    nm_model_fast: str = "gemini-3.5-flash-lite"  # kiểm duyệt, tìm ngữ nghĩa (rẻ, nhanh)
    nm_agent_max_steps: int = Field(default=5, ge=1, le=10)

    @model_validator(mode="after")
    def _check_nm(self) -> "Settings":
        """Lỗi tường minh khi cấu hình sai, thay vì chạy với ngưỡng/kênh vô nghĩa."""
        if self.mod_publish_below > self.mod_reject_from:
            raise ValueError("mod_publish_below phải <= mod_reject_from")
        if self.channel_mode == "zalo" and not self.zalo_bot_token:
            raise ValueError("channel_mode='zalo' cần ZALO_BOT_TOKEN")
        if (self.nm_ai_mode == "gemini" or self.nm_agent_enabled) and not self.google_api_key:
            raise ValueError("NM_AI_MODE=gemini / NM_AGENT_ENABLED=true cần GOOGLE_API_KEY")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
