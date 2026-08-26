"""6. Configuration (+ log redaction)."""

import json
import logging
import stat

import pytest

from app.config import (
    PROVIDER_AUTO,
    PROVIDER_OPENROUTER,
    AppConfig,
    load_dotenv,
)
from app.utils.logging_setup import register_secrets, setup_logging


def test_defaults_are_sane():
    cfg = AppConfig()
    assert cfg.preferred_provider == PROVIDER_AUTO
    assert 0.25 <= cfg.overlay_width_ratio <= 0.40
    assert cfg.hotkey == "F8"
    assert cfg.overlay_position == "top"


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    cfg = AppConfig(font_size=15, opacity=0.5, overlay_position="bottom", hotkey="F9")
    cfg.save(path)

    loaded = AppConfig.load(path)
    assert (loaded.font_size, loaded.opacity, loaded.overlay_position, loaded.hotkey) == (
        15,
        0.5,
        "bottom",
        "F9",
    )


def test_config_file_is_not_world_readable(tmp_path):
    path = AppConfig().save(tmp_path / "config.json")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_invalid_values_are_clamped(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "preferred_provider": "nonsense",
                "overlay_position": "left",
                "font_size": 900,
                "opacity": 4.2,
                "overlay_width_ratio": 0.99,
                "hotkey": "  ",
                "openrouter_models": "  ,  ",
            }
        )
    )
    cfg = AppConfig.load(path)
    assert cfg.preferred_provider == PROVIDER_AUTO
    assert cfg.overlay_position == "top"
    assert cfg.font_size == 32
    assert cfg.opacity == 1.0
    assert cfg.overlay_width_ratio == 0.60
    assert cfg.hotkey == "F8"
    assert cfg.openrouter_model_list()  # restored to the default chain


def test_corrupt_config_falls_back_to_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json at all")
    assert AppConfig.load(path).font_size == AppConfig().font_size


def test_env_key_beats_settings_file(monkeypatch):
    cfg = AppConfig(gemini_api_key="from-file")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert cfg.resolved_gemini_key() == "from-file"
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert cfg.resolved_gemini_key() == "from-env"


def test_openrouter_models_env_override(monkeypatch):
    cfg = AppConfig()
    monkeypatch.setenv("OPENROUTER_MODELS", "a/model-1, b/model-2 ,a/model-1")
    assert cfg.openrouter_model_list() == ["a/model-1", "b/model-2"]


def test_dotenv_is_loaded_without_overriding_exports(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        'GEMINI_API_KEY="dotenv-key"\n'
        "# comment\n"
        "export DEEPSEEK_API_KEY=other-key\n"
        "OPENAI_API_KEY=already-exported\n"
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "from-shell")

    applied = load_dotenv(env_file)
    assert applied["GEMINI_API_KEY"] == "dotenv-key"
    assert applied["DEEPSEEK_API_KEY"] == "other-key"
    assert "OPENAI_API_KEY" not in applied  # exported value wins
    assert AppConfig().resolved_deepseek_key() == "other-key"


def test_redacted_dict_hides_keys():
    cfg = AppConfig(gemini_api_key="AIzaSECRETVALUE123456")
    dumped = cfg.redacted_dict()
    assert dumped["gemini_api_key"] == "<set>"
    assert dumped["deepseek_api_key"] == "<unset>"
    assert "AIzaSECRETVALUE123456" not in json.dumps(dumped)


def test_api_keys_never_reach_the_log_file(tmp_path, monkeypatch):
    secret = "AIzaSyTESTKEY0123456789abcdef"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    cfg = AppConfig()
    register_secrets(cfg.secret_values())
    log_file = tmp_path / "app.log"
    setup_logging("DEBUG", log_file)

    logging.getLogger("test").info("calling with key %s", secret)
    logging.getLogger("test").info("config: %s", cfg.redacted_dict())
    logging.getLogger("test").info('{"api_key": "sk-anotherplainsecret999"}')
    logging.shutdown()

    contents = log_file.read_text()
    assert secret not in contents
    assert "sk-anotherplainsecret999" not in contents
    assert "REDACTED" in contents


def test_preferred_provider_accepts_every_known_provider():
    for provider in ("gemini", "deepseek", PROVIDER_OPENROUTER, "openai", "custom", "auto"):
        cfg = AppConfig(preferred_provider=provider)
        cfg.normalise()
        assert cfg.preferred_provider == provider


@pytest.mark.parametrize("value,expected", [("English", "English"), ("", "auto"), ("  ", "auto")])
def test_language_normalisation(value, expected):
    cfg = AppConfig(language=value)
    cfg.normalise()
    assert cfg.language == expected
