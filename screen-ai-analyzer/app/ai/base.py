"""Shared provider plumbing."""

from __future__ import annotations

import logging
from typing import Callable

from app.ai.json_utils import JsonRepairError, extract_json
from app.ai.prompts import RETRY_SUFFIX
from app.ai.schema import Answer, SchemaError

log = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    """A provider could not produce a valid answer.

    ``str(exc)`` is short and safe to show to the user; details go to the log.
    """


class Provider:
    """Interface implemented by Gemini and DeepSeek."""

    name = "provider"
    supports_vision = False

    def available(self) -> bool:  # pragma: no cover - trivial
        raise NotImplementedError

    def analyze_image(self, image, language: str = "auto") -> Answer:
        raise ProviderError(f"{self.name} cannot analyse images")

    def analyze_text(self, text: str, language: str = "auto") -> Answer:
        raise ProviderError(f"{self.name} cannot analyse text")


def parse_answer(raw: str, provider: str) -> Answer:
    """Parse model output into an :class:`Answer` (raises on bad output)."""
    data = extract_json(raw)
    answer = Answer.from_dict(data)
    answer.provider = provider
    return answer


def request_with_repair(send: Callable[[str], str], prompt: str, provider: str) -> Answer:
    """Send ``prompt``; if the reply is not usable JSON, re-ask once.

    The first attempt also tries local repair (fences, trailing commas,
    truncation) before spending a second request.
    """
    raw = send(prompt)
    try:
        return parse_answer(raw, provider)
    except (JsonRepairError, SchemaError) as first_error:
        log.warning("%s returned malformed JSON (%s); re-requesting", provider, first_error)

    raw = send(prompt + RETRY_SUFFIX)
    try:
        return parse_answer(raw, provider)
    except (JsonRepairError, SchemaError) as second_error:
        log.error("%s returned malformed JSON twice: %s", provider, second_error)
        raise ProviderError(f"{provider} did not return a valid answer") from second_error
