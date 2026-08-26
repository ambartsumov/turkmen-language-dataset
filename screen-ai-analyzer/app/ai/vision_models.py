"""Which chat models can actually read an image.

A screenshot is only ever uploaded to a model that is known to accept image
input; everything else goes through OCR first.  The table is heuristic (model
names change fast), so every entry can be overridden with an environment
variable listing extra model ids, comma separated:

    GEMINI_VISION_MODELS, DEEPSEEK_VISION_MODELS, OPENAI_VISION_MODELS,
    OPENROUTER_VISION_MODELS, CUSTOM_VISION_MODELS
"""

from __future__ import annotations

import os
from typing import Iterable

#: Substrings of model ids that accept images, per provider family.
VISION_MARKERS: dict[str, tuple[str, ...]] = {
    "gemini": ("gemini-", "gemma-3"),
    "openai": ("gpt-4o", "gpt-4.1", "gpt-4-turbo", "gpt-5", "o3", "o4", "chatgpt-4o"),
    "openrouter": (
        "gpt-4o",
        "gpt-4.1",
        "gpt-5",
        "claude-3",
        "claude-4",
        "claude-sonnet",
        "claude-opus",
        "gemini",
        "pixtral",
        "llava",
        "qwen-vl",
        "qwen2-vl",
        "qwen2.5-vl",
        "internvl",
        "llama-3.2-11b-vision",
        "llama-3.2-90b-vision",
        "llama-4",
        "molmo",
        "-vl",
        "vision",
    ),
    "deepseek": ("deepseek-vl", "-vl2"),
    "custom": ("vision", "-vl", "gpt-4o", "gemini", "claude-3", "claude-4", "llava", "pixtral"),
}

#: Models that are known NOT to be multimodal even though a marker matches.
TEXT_ONLY: tuple[str, ...] = ("deepseek-chat", "deepseek-reasoner")


def _env_models(env_var: str) -> set[str]:
    raw = os.environ.get(env_var, "")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def extra_vision_models(family: str) -> set[str]:
    return _env_models(f"{family.upper()}_VISION_MODELS")


def model_supports_vision(model: str, family: str = "custom") -> bool:
    """True if ``model`` from ``family`` accepts image input."""
    name = (model or "").strip().lower()
    if not name:
        return False
    extras = extra_vision_models(family)
    if name in extras or any(name.startswith(e) for e in extras):
        return True
    if any(name == t or name.endswith("/" + t) or t in name for t in TEXT_ONLY):
        return False
    markers: Iterable[str] = VISION_MARKERS.get(family, VISION_MARKERS["custom"])
    return any(marker in name for marker in markers)
