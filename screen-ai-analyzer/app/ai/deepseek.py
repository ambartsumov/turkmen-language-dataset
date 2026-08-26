"""DeepSeek provider (fallback).

``deepseek-chat`` / ``deepseek-reasoner`` on the public API are text-only, so
the pipeline runs OCR first and sends text.  If a vision-capable DeepSeek model
is configured (``deepseek_vision_model`` / ``DEEPSEEK_VISION_MODELS``), the
screenshot is sent directly instead.
"""

from __future__ import annotations

from typing import Optional

import httpx

from app.ai.openai_compat import OpenAICompatibleProvider, extract_content  # noqa: F401
from app.ai.vision_models import model_supports_vision

NAME = "deepseek"
API_URL = "https://api.deepseek.com"


def deepseek_supports_vision(model: str) -> bool:
    return model_supports_vision(model, "deepseek")


class DeepSeekProvider(OpenAICompatibleProvider):
    family = "deepseek"

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        timeout: int = 60,
        base_url: str = API_URL,
        client: Optional[httpx.Client] = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            name=NAME,
            timeout=timeout,
            family="deepseek",
            client=client,
        )
