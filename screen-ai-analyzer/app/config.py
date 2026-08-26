"""Application configuration.

Precedence for API keys:  environment (including ``.env``)  >  settings file.
The settings file is written with mode 0600 and keys are never logged.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, Optional

APP_NAME = "screen-ai-analyzer"

PROVIDER_GEMINI = "gemini"
PROVIDER_DEEPSEEK = "deepseek"
PROVIDER_OPENAI = "openai"
PROVIDER_OPENROUTER = "openrouter"
PROVIDER_CUSTOM = "custom"
PROVIDER_AUTO = "auto"
PROVIDERS = (
    PROVIDER_AUTO,
    PROVIDER_GEMINI,
    PROVIDER_DEEPSEEK,
    PROVIDER_OPENAI,
    PROVIDER_OPENROUTER,
    PROVIDER_CUSTOM,
)

#: Order the pipeline uses when ``preferred_provider`` is ``auto``.
DEFAULT_PROVIDER_ORDER = (
    PROVIDER_GEMINI,
    PROVIDER_OPENROUTER,
    PROVIDER_OPENAI,
    PROVIDER_CUSTOM,
    PROVIDER_DEEPSEEK,
)

#: Environment variable that holds each provider's key.
KEY_ENV_VARS = {
    PROVIDER_GEMINI: "GEMINI_API_KEY",
    PROVIDER_DEEPSEEK: "DEEPSEEK_API_KEY",
    PROVIDER_OPENAI: "OPENAI_API_KEY",
    PROVIDER_OPENROUTER: "OPENROUTER_API_KEY",
    PROVIDER_CUSTOM: "CUSTOM_API_KEY",
}

OUTPUT_NOTIFICATION = "notification"
OUTPUT_OVERLAY = "overlay"
OUTPUT_MODES = (OUTPUT_NOTIFICATION, OUTPUT_OVERLAY)

POSITION_TOP = "top"
POSITION_BOTTOM = "bottom"
POSITIONS = (POSITION_TOP, POSITION_BOTTOM)

_SECRET_FIELDS = (
    "gemini_api_key",
    "deepseek_api_key",
    "openai_api_key",
    "openrouter_api_key",
    "custom_api_key",
)


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.json"


def project_root() -> Path:
    """Directory that contains ``run.sh`` / ``.env`` (repository checkout)."""
    return Path(__file__).resolve().parent.parent


def load_dotenv(path: Optional[Path] = None) -> Dict[str, str]:
    """Minimal ``.env`` loader.

    Values already present in ``os.environ`` win, so an exported variable
    always beats the file.  Returns the mapping that was applied.
    """
    path = path or (project_root() / ".env")
    applied: Dict[str, str] = {}
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return applied
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key or key in os.environ:
            continue
        os.environ[key] = value
        applied[key] = value
    return applied


@dataclass
class AppConfig:
    # --- providers -------------------------------------------------------
    preferred_provider: str = PROVIDER_AUTO

    # Gemini Vision - primary
    gemini_model: str = "gemini-2.5-flash"
    # DeepSeek - text-only on the public API, so OCR runs first
    deepseek_model: str = "deepseek-chat"
    #: optional vision-capable DeepSeek model; used instead of OCR when set
    deepseek_vision_model: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    # Extra vision providers (OpenAI-compatible), used when their key is set
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    #: comma separated, tried in order; a single OpenRouter key can serve both
    #: a vision model (Gemini) and a text model (DeepSeek)
    openrouter_models: str = "google/gemini-2.5-flash,deepseek/deepseek-chat"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    #: any other OpenAI-compatible endpoint (vLLM, Ollama, LiteLLM, LM Studio…)
    custom_model: str = ""
    custom_base_url: str = ""

    # Fallback storage only; ``.env`` is the recommended place for keys.
    gemini_api_key: str = ""
    deepseek_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    custom_api_key: str = ""

    # --- output ----------------------------------------------------------
    #: "notification" = clipboard + desktop notification, nothing drawn on screen
    #: "overlay"      = the small always-on-top answer window
    output_mode: str = OUTPUT_NOTIFICATION
    notify_on_start: bool = False

    # --- overlay (used when output_mode == "overlay") ---------------------
    overlay_position: str = POSITION_TOP
    overlay_width_ratio: float = 0.32  # 25%-40% of the screen width
    overlay_max_height_ratio: float = 0.45
    font_size: int = 11
    opacity: float = 0.92

    # --- behaviour -------------------------------------------------------
    hotkey: str = "F8"
    language: str = "auto"
    request_timeout: int = 60
    max_image_width: int = 1600
    log_level: str = "INFO"

    _source_path: Optional[Path] = field(default=None, repr=False, compare=False)

    # -- persistence ------------------------------------------------------
    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AppConfig":
        path = Path(path) if path else config_path()
        data: Dict[str, Any] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
        known = {f.name for f in fields(cls) if not f.name.startswith("_")}
        clean = {k: v for k, v in data.items() if k in known}
        cfg = cls(**clean)
        cfg._source_path = path
        cfg.normalise()
        return cfg

    def save(self, path: Optional[Path] = None) -> Path:
        path = Path(path) if path else (self._source_path or config_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(path)
        self._source_path = path
        return path

    # -- validation -------------------------------------------------------
    def normalise(self) -> "AppConfig":
        if self.preferred_provider not in PROVIDERS:
            self.preferred_provider = PROVIDER_AUTO
        if self.output_mode not in OUTPUT_MODES:
            self.output_mode = OUTPUT_NOTIFICATION
        if self.overlay_position not in POSITIONS:
            self.overlay_position = POSITION_TOP
        self.overlay_width_ratio = _clamp(float(self.overlay_width_ratio), 0.20, 0.60)
        self.overlay_max_height_ratio = _clamp(float(self.overlay_max_height_ratio), 0.15, 0.90)
        self.font_size = int(_clamp(int(self.font_size), 7, 32))
        self.opacity = _clamp(float(self.opacity), 0.30, 1.0)
        self.request_timeout = int(_clamp(int(self.request_timeout), 5, 300))
        self.max_image_width = int(_clamp(int(self.max_image_width), 640, 4096))
        self.hotkey = (self.hotkey or "F8").strip() or "F8"
        if not self.model_list(self.openrouter_models):
            self.openrouter_models = "google/gemini-2.5-flash,deepseek/deepseek-chat"
        self.language = (self.language or "auto").strip() or "auto"
        return self

    @staticmethod
    def model_list(value: str) -> list[str]:
        """Parse a comma separated model list, preserving order."""
        seen: list[str] = []
        for item in str(value or "").split(","):
            item = item.strip()
            if item and item not in seen:
                seen.append(item)
        return seen

    def openrouter_model_list(self) -> list[str]:
        env = os.environ.get("OPENROUTER_MODELS", "")
        return self.model_list(env) or self.model_list(self.openrouter_models)

    # -- secrets ----------------------------------------------------------
    def resolved_key(self, provider: str) -> str:
        """Key for ``provider``: environment (incl. ``.env``) beats settings."""
        env_var = KEY_ENV_VARS.get(provider)
        from_env = os.environ.get(env_var, "").strip() if env_var else ""
        from_file = str(getattr(self, f"{provider}_api_key", "") or "").strip()
        return from_env or from_file

    def resolved_gemini_key(self) -> str:
        return self.resolved_key(PROVIDER_GEMINI)

    def resolved_deepseek_key(self) -> str:
        return self.resolved_key(PROVIDER_DEEPSEEK)

    def secret_values(self) -> list[str]:
        """Every secret currently known, for log redaction."""
        values = [self.resolved_key(name) for name in KEY_ENV_VARS]
        return [v for v in values if v]

    def redacted_dict(self) -> Dict[str, Any]:
        """Config snapshot that is safe to write to the log file."""
        out = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
        for name in _SECRET_FIELDS:
            out[name] = "<set>" if out.get(name) else "<unset>"
        return out


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
