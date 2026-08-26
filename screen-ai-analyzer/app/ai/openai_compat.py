"""Provider for any OpenAI-compatible ``/chat/completions`` endpoint.

Covers DeepSeek, OpenAI, OpenRouter and self-hosted gateways (vLLM, Ollama,
LM Studio, LiteLLM).  Images are sent as a base64 ``image_url`` part, but only
when the configured model is known to accept them - otherwise the pipeline
runs OCR first and this provider gets plain text.
"""

from __future__ import annotations

import base64
import logging
from typing import Optional

import httpx

from app.ai.base import Provider, ProviderError, request_with_repair
from app.ai.prompts import SYSTEM_INSTRUCTION, text_prompt, vision_prompt
from app.ai.schema import Answer
from app.ai.vision_models import model_supports_vision
from app.capture.preprocess import PreparedImage

log = logging.getLogger(__name__)

#: Models that reject the ``response_format`` parameter.
NO_JSON_MODE = ("deepseek-reasoner", "o1-", "o3-mini")


class OpenAICompatibleProvider(Provider):
    family = "custom"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        name: Optional[str] = None,
        timeout: int = 60,
        family: Optional[str] = None,
        extra_headers: Optional[dict] = None,
        client: Optional[httpx.Client] = None,
        force_vision: Optional[bool] = None,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.name = name or (family or self.family)
        self.timeout = timeout
        if family:
            self.family = family
        self.extra_headers = extra_headers or {}
        self._client = client
        self._force_vision = force_vision

    # -- capabilities -----------------------------------------------------
    @property
    def supports_vision(self) -> bool:  # type: ignore[override]
        if self._force_vision is not None:
            return self._force_vision
        return model_supports_vision(self.model, self.family)

    def available(self) -> bool:
        return bool(self.api_key) or self._client is not None

    def endpoint(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    # -- transport --------------------------------------------------------
    def _post(self, messages: list) -> str:
        if not self.available():
            raise ProviderError(f"{self.name} API key is not set")
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "stream": False,
        }
        if not any(marker in self.model for marker in NO_JSON_MODE):
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        try:
            if self._client is not None:
                response = self._client.post(self.endpoint(), json=payload, headers=headers)
            else:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(self.endpoint(), json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            log.error("%s HTTP %s", self.name, exc.response.status_code)
            raise ProviderError(
                f"{self.name} request failed (HTTP {exc.response.status_code})"
            ) from exc
        except ProviderError:
            raise
        except Exception as exc:
            log.exception("%s request failed", self.name)
            raise ProviderError(f"{self.name} request failed: {_short(exc)}") from exc

        content = extract_content(data, self.name)
        if not content.strip():
            raise ProviderError(f"{self.name} returned an empty response")
        return content

    # -- requests ---------------------------------------------------------
    def analyze_text(self, text: str, language: str = "auto") -> Answer:
        def send(prompt: str) -> str:
            return self._post(
                [
                    {"role": "system", "content": SYSTEM_INSTRUCTION},
                    {"role": "user", "content": prompt},
                ]
            )

        return request_with_repair(send, text_prompt(text, language), self.name)

    def analyze_image(self, image: PreparedImage, language: str = "auto") -> Answer:
        if not self.supports_vision:
            raise ProviderError(
                f"{self.name} model '{self.model}' has no vision support; use OCR first"
            )
        data_url = (
            f"data:{image.mime_type};base64,"
            f"{base64.b64encode(image.data).decode('ascii')}"
        )

        def send(prompt: str) -> str:
            return self._post(
                [
                    {"role": "system", "content": SYSTEM_INSTRUCTION},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": data_url, "detail": "high"},
                            },
                            {"type": "text", "text": prompt},
                        ],
                    },
                ]
            )

        return request_with_repair(send, vision_prompt(language), self.name)


def extract_content(data: dict, provider: str = "provider") -> str:
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError(f"{provider} response had no choices") from exc
    content = message.get("content")
    if isinstance(content, list):  # some gateways return content parts
        return "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return content or ""


def _short(exc: Exception, limit: int = 160) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return message[:limit]
