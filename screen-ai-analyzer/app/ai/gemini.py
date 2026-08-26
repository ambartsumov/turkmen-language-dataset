"""Gemini Vision provider (official ``google-genai`` SDK)."""

from __future__ import annotations

import logging
from typing import Optional

from app.ai.base import Provider, ProviderError, request_with_repair
from app.ai.prompts import SYSTEM_INSTRUCTION, text_prompt, vision_prompt
from app.ai.schema import Answer
from app.capture.preprocess import PreparedImage

log = logging.getLogger(__name__)

NAME = "gemini"


class GeminiProvider(Provider):
    name = NAME
    supports_vision = True

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        timeout: int = 60,
        client=None,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model
        self.timeout = timeout
        self._client = client  # injectable for tests

    # -- lifecycle --------------------------------------------------------
    def available(self) -> bool:
        return bool(self.api_key) or self._client is not None

    def client(self):
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise ProviderError("Gemini API key is not set")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ProviderError("google-genai package is not installed") from exc
        self._client = genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(timeout=self.timeout * 1000),
        )
        return self._client

    # -- requests ---------------------------------------------------------
    def _generate(self, prompt: str, image: Optional[PreparedImage]) -> str:
        try:
            from google.genai import types
        except ImportError as exc:  # pragma: no cover
            raise ProviderError("google-genai package is not installed") from exc

        parts = []
        if image is not None:
            parts.append(types.Part.from_bytes(data=image.data, mime_type=image.mime_type))
        parts.append(types.Part.from_text(text=prompt))

        try:
            response = self.client().models.generate_content(
                model=self.model,
                contents=[types.Content(role="user", parts=parts)],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
        except ProviderError:
            raise
        except Exception as exc:
            log.exception("Gemini request failed")
            raise ProviderError(f"Gemini request failed: {_short(exc)}") from exc

        text = extract_text(response)
        if not text.strip():
            raise ProviderError("Gemini returned an empty response")
        return text

    def analyze_image(self, image: PreparedImage, language: str = "auto") -> Answer:
        return request_with_repair(
            lambda prompt: self._generate(prompt, image), vision_prompt(language), NAME
        )

    def analyze_text(self, text: str, language: str = "auto") -> Answer:
        return request_with_repair(
            lambda prompt: self._generate(prompt, None), text_prompt(text, language), NAME
        )


def extract_text(response) -> str:
    """Pull the text out of a ``GenerateContentResponse`` defensively."""
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text
    chunks = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            part_text = getattr(part, "text", None)
            if isinstance(part_text, str):
                chunks.append(part_text)
    return "".join(chunks)


def _short(exc: Exception, limit: int = 160) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return message[:limit]
