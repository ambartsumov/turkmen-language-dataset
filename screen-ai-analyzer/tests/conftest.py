import os
import sys
from pathlib import Path

import pytest

# Qt must run headless in CI / on a machine without a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Never pick up the developer's real keys during tests.
for _var in (
    "GEMINI_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "CUSTOM_API_KEY",
):
    os.environ.pop(_var, None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def clean_provider_keys(monkeypatch):
    """No test may see (or leak) a provider key from the environment."""
    for var in (
        "GEMINI_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "CUSTOM_API_KEY",
        "OPENROUTER_MODELS",
        "CUSTOM_BASE_URL",
        "CUSTOM_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def config(tmp_path):
    from app.config import AppConfig

    cfg = AppConfig()
    cfg._source_path = tmp_path / "config.json"
    return cfg


@pytest.fixture
def sample_answer():
    from app.ai.schema import Answer

    return Answer(
        question="What is the capital of France?",
        answer="B",
        answer_text="Paris",
        confidence=0.97,
        explanation="Paris has been the capital since 987.",
        provider="gemini",
    )


@pytest.fixture
def screenshot_png(tmp_path):
    """A small PNG standing in for a screenshot."""
    from PIL import Image, ImageDraw

    path = tmp_path / "screen.png"
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.text((40, 40), "What is 2 + 2?", fill="black")
    draw.text((40, 80), "A) 3   B) 4   C) 5", fill="black")
    image.save(path)
    return path
