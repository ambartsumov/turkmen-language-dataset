"""ScreenCapture -> preprocessing -> vision model -> structured answer -> overlay.

Order of attempts:

1. every configured **vision** provider, in preference order
   (Gemini Vision, OpenAI, OpenRouter, a custom OpenAI-compatible endpoint,
   a vision-capable DeepSeek model);
2. only if all of them fail, OCR the screenshot once and send the **text** to
   the remaining text-only providers (DeepSeek by default).

A screenshot is never uploaded to a model that cannot read images.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable, List, Optional, Union

from app.ai.base import Provider, ProviderError
from app.ai.deepseek import DeepSeekProvider
from app.ai.gemini import GeminiProvider
from app.ai.openai_compat import OpenAICompatibleProvider
from app.ai.schema import Answer
from app.capture.preprocess import PreparedImage, prepare_for_vision
from app.config import (
    DEFAULT_PROVIDER_ORDER,
    PROVIDER_AUTO,
    PROVIDER_CUSTOM,
    PROVIDER_DEEPSEEK,
    PROVIDER_GEMINI,
    PROVIDER_OPENAI,
    PROVIDER_OPENROUTER,
    AppConfig,
)
from app.ocr.engine import OcrError, extract_text

log = logging.getLogger(__name__)

OcrFunc = Callable[[Union[str, bytes], str], str]


class AnalysisError(RuntimeError):
    """No provider could analyse the screen. Message is user-facing and short."""


class AnalysisPipeline:
    def __init__(
        self,
        config: AppConfig,
        providers: Optional[List[Provider]] = None,
        ocr: Optional[OcrFunc] = None,
    ) -> None:
        self.config = config
        self._providers = providers
        self._ocr: OcrFunc = ocr or (lambda src, lang: extract_text(src, lang))

    # -- provider construction -------------------------------------------
    def _make(self, name: str) -> List[Provider]:
        """Build every provider instance for one vendor (may be several models)."""
        cfg = self.config
        key = cfg.resolved_key(name)
        if not key:
            return []
        if name == PROVIDER_GEMINI:
            return [
                GeminiProvider(
                    api_key=key, model=cfg.gemini_model, timeout=cfg.request_timeout
                )
            ]
        if name == PROVIDER_DEEPSEEK:
            models = [m for m in (cfg.deepseek_vision_model.strip(), cfg.deepseek_model) if m]
            return [
                DeepSeekProvider(
                    api_key=key,
                    model=model,
                    base_url=cfg.deepseek_base_url,
                    timeout=cfg.request_timeout,
                )
                for model in dict.fromkeys(models)
            ]
        if name == PROVIDER_OPENAI:
            return [
                OpenAICompatibleProvider(
                    api_key=key,
                    model=cfg.openai_model,
                    base_url=cfg.openai_base_url,
                    name=PROVIDER_OPENAI,
                    family=PROVIDER_OPENAI,
                    timeout=cfg.request_timeout,
                )
            ]
        if name == PROVIDER_OPENROUTER:
            # One key, several models: a vision model first, a text model as
            # the OCR fallback.
            return [
                OpenAICompatibleProvider(
                    api_key=key,
                    model=model,
                    base_url=cfg.openrouter_base_url,
                    name=f"{PROVIDER_OPENROUTER}:{model}",
                    family=PROVIDER_OPENROUTER,
                    timeout=cfg.request_timeout,
                    extra_headers={
                        "X-Title": "screen-ai-analyzer",
                        "HTTP-Referer": "https://localhost/screen-ai-analyzer",
                    },
                )
                for model in cfg.openrouter_model_list()
            ]
        if name == PROVIDER_CUSTOM:
            base_url = os.environ.get("CUSTOM_BASE_URL", "").strip() or cfg.custom_base_url
            model = os.environ.get("CUSTOM_MODEL", "").strip() or cfg.custom_model
            if not base_url or not model:
                return []
            return [
                OpenAICompatibleProvider(
                    api_key=key,
                    model=model,
                    base_url=base_url,
                    name=PROVIDER_CUSTOM,
                    family=PROVIDER_CUSTOM,
                    timeout=cfg.request_timeout,
                )
            ]
        return []

    def provider_names(self) -> List[str]:
        """Preference order, honouring ``preferred_provider``."""
        order = list(DEFAULT_PROVIDER_ORDER)
        preferred = self.config.preferred_provider
        if preferred != PROVIDER_AUTO and preferred in order:
            order.remove(preferred)
            order.insert(0, preferred)
        return order

    def build_providers(self) -> List[Provider]:
        if self._providers is not None:
            return list(self._providers)
        built: List[Provider] = []
        for name in self.provider_names():
            built.extend(p for p in self._make(name) if p.available())
        return built

    # -- main entry point -------------------------------------------------
    def analyze(self, image_source: Union[Path, bytes]) -> Answer:
        prepared = prepare_for_vision(image_source, max_width=self.config.max_image_width)
        return self.analyze_prepared(prepared, image_source)

    def analyze_prepared(
        self, prepared: PreparedImage, ocr_source: Union[Path, bytes, None] = None
    ) -> Answer:
        providers = self.build_providers()
        if not providers:
            raise AnalysisError(
                "No API key configured. Set OPENROUTER_API_KEY, GEMINI_API_KEY or "
                "DEEPSEEK_API_KEY in .env."
            )

        vision = [p for p in providers if p.supports_vision]
        text_only = [p for p in providers if not p.supports_vision]
        language = self.config.language
        failures: List[str] = []

        log.info(
            "Providers: vision=%s text=%s",
            [p.name for p in vision] or "-",
            [p.name for p in text_only] or "-",
        )

        # 1. vision models get the screenshot itself
        for provider in vision:
            try:
                answer = provider.analyze_image(prepared, language)
                log.info("Answer from %s (confidence %.2f)", provider.name, answer.confidence)
                return answer
            except ProviderError as exc:
                log.warning("Vision provider %s failed: %s", provider.name, exc)
                failures.append(f"{provider.name}: {exc}")
            except Exception:
                log.exception("Vision provider %s raised unexpectedly", provider.name)
                failures.append(f"{provider.name}: unexpected error")

        if not text_only:
            raise AnalysisError(_summarise(failures))

        # 2. text-only models need OCR first - the image is not sent to them
        try:
            log.info("Falling back to OCR + text providers: %s", [p.name for p in text_only])
            ocr_text = self._ocr(
                ocr_source if ocr_source is not None else prepared.data, language
            )
        except OcrError as exc:
            failures.append(f"ocr: {exc}")
            raise AnalysisError(_summarise(failures)) from exc

        for provider in text_only:
            try:
                answer = provider.analyze_text(ocr_text, language)
                log.info(
                    "Answer from %s via OCR (confidence %.2f)", provider.name, answer.confidence
                )
                return answer
            except ProviderError as exc:
                log.warning("Text provider %s failed: %s", provider.name, exc)
                failures.append(f"{provider.name}: {exc}")
            except Exception:
                log.exception("Text provider %s raised unexpectedly", provider.name)
                failures.append(f"{provider.name}: unexpected error")

        raise AnalysisError(_summarise(failures))


def _summarise(failures: List[str], limit: int = 220) -> str:
    if not failures:
        return "No AI provider was available."
    text = "; ".join(failures)
    return text if len(text) <= limit else text[: limit - 1] + "…"
