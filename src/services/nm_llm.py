"""Model Gemini cho NeighborMarket — một chỗ duy nhất tạo LLM (agent + 4 hàm AI).

Tách khỏi `src/services/llm.py` (cascade OpenAI của template) để không đổi hành vi agent mẫu.
Đổi model = đổi NM_MODEL / NM_MODEL_FAST trong .env.
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

from src.config import get_settings

LLM_TIMEOUT_S = 18  # dưới mức 20s của safe_ai để lỗi về đúng chỗ


def get_nm_llm(fast: bool = False, temperature: float = 0.2) -> BaseChatModel:
    """fast=True: model rẻ/nhanh (kiểm duyệt, tìm ngữ nghĩa). Thiếu key → lỗi tường minh."""
    s = get_settings()
    if not s.google_api_key:
        raise RuntimeError("Thiếu GOOGLE_API_KEY")
    return ChatGoogleGenerativeAI(
        model=s.nm_model_fast if fast else s.nm_model,
        google_api_key=s.google_api_key,
        temperature=temperature,
        timeout=LLM_TIMEOUT_S,
        max_retries=1,
    )
