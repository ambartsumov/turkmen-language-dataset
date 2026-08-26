"""2. Gemini response parsing, 3. DeepSeek/vision fallback chain."""

from types import SimpleNamespace

import httpx
import pytest

from app.ai.base import ProviderError
from app.ai.deepseek import DeepSeekProvider
from app.ai.gemini import GeminiProvider, extract_text
from app.ai.openai_compat import OpenAICompatibleProvider
from app.ai.pipeline import AnalysisError, AnalysisPipeline
from app.ai.schema import Answer
from app.ai.vision_models import model_supports_vision
from app.capture.preprocess import PreparedImage

PAYLOAD = (
    '{"question": "2+2?", "answer": "B", "answer_text": "4", '
    '"confidence": 0.9, "explanation": "arithmetic"}'
)

IMAGE = PreparedImage(data=b"\xff\xd8fake", mime_type="image/jpeg", width=10, height=10)


# --------------------------------------------------------------------------
# Gemini
# --------------------------------------------------------------------------
class FakeGeminiModels:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(text=reply)


class FakeGeminiClient:
    def __init__(self, replies):
        self.models = FakeGeminiModels(replies)


def gemini_with(replies):
    return GeminiProvider(api_key="", model="gemini-2.5-flash", client=FakeGeminiClient(replies))


def test_gemini_parses_answer():
    provider = gemini_with([PAYLOAD])
    answer = provider.analyze_image(IMAGE)
    assert isinstance(answer, Answer)
    assert (answer.answer, answer.answer_text, answer.provider) == ("B", "4", "gemini")
    assert answer.confidence == pytest.approx(0.9)


def test_gemini_parses_fenced_answer():
    assert gemini_with([f"```json\n{PAYLOAD}\n```"]).analyze_image(IMAGE).answer == "B"


def test_gemini_rerequests_on_broken_json():
    provider = gemini_with(["sorry, I cannot do that", PAYLOAD])
    answer = provider.analyze_image(IMAGE)
    assert answer.answer == "B"
    assert len(provider._client.models.calls) == 2  # one retry


def test_gemini_gives_up_after_second_bad_reply():
    provider = gemini_with(["nope", "still nope"])
    with pytest.raises(ProviderError):
        provider.analyze_image(IMAGE)


def test_gemini_api_error_becomes_provider_error():
    provider = gemini_with([RuntimeError("429 quota exceeded")])
    with pytest.raises(ProviderError) as excinfo:
        provider.analyze_image(IMAGE)
    assert "Gemini request failed" in str(excinfo.value)


def test_gemini_extract_text_from_candidates():
    response = SimpleNamespace(
        text=None,
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(text=PAYLOAD)]))],
    )
    assert extract_text(response) == PAYLOAD


def test_gemini_image_is_actually_attached():
    provider = gemini_with([PAYLOAD])
    provider.analyze_image(IMAGE)
    contents = provider._client.models.calls[0]["contents"]
    assert contents  # image part + prompt part
    assert len(contents[0].parts) == 2


# --------------------------------------------------------------------------
# OpenAI-compatible providers (DeepSeek / OpenRouter / custom)
# --------------------------------------------------------------------------
def chat_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test")


def json_reply(content):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_deepseek_text_request():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return json_reply(PAYLOAD)

    provider = DeepSeekProvider(api_key="k", client=chat_client(handler))
    answer = provider.analyze_text("What is 2+2? A) 3 B) 4")
    assert answer.answer == "B"
    assert answer.provider == "deepseek"
    assert seen["url"].endswith("/chat/completions")
    assert "image_url" not in seen["body"]  # text-only model gets no image


def test_deepseek_chat_is_not_vision_capable():
    provider = DeepSeekProvider(api_key="k", model="deepseek-chat")
    assert provider.supports_vision is False
    with pytest.raises(ProviderError):
        provider.analyze_image(IMAGE)


def test_http_error_becomes_provider_error():
    provider = DeepSeekProvider(
        api_key="k", client=chat_client(lambda request: httpx.Response(401, json={}))
    )
    with pytest.raises(ProviderError) as excinfo:
        provider.analyze_text("hi")
    assert "401" in str(excinfo.value)


def test_openrouter_vision_model_sends_the_image():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        return json_reply(PAYLOAD)

    provider = OpenAICompatibleProvider(
        api_key="k",
        model="google/gemini-2.5-flash",
        base_url="https://openrouter.ai/api/v1",
        family="openrouter",
        name="openrouter",
        client=chat_client(handler),
    )
    assert provider.supports_vision
    assert provider.analyze_image(IMAGE).answer == "B"
    assert "image_url" in seen["body"]
    assert "data:image/jpeg;base64," in seen["body"]


@pytest.mark.parametrize(
    "model,family,expected",
    [
        ("google/gemini-2.5-flash", "openrouter", True),
        ("deepseek/deepseek-chat", "openrouter", False),
        ("openai/gpt-4o-mini", "openrouter", True),
        ("qwen/qwen2.5-vl-72b-instruct", "openrouter", True),
        ("deepseek-chat", "deepseek", False),
        ("deepseek-reasoner", "deepseek", False),
        ("gemini-2.5-flash", "gemini", True),
        ("gpt-4o-mini", "openai", True),
    ],
)
def test_vision_capability_table(model, family, expected):
    assert model_supports_vision(model, family) is expected


def test_vision_capability_env_override(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_VISION_MODELS", "deepseek-vision-preview")
    assert model_supports_vision("deepseek-vision-preview", "deepseek") is True


# --------------------------------------------------------------------------
# pipeline fallback
# --------------------------------------------------------------------------
class StubProvider:
    def __init__(self, name, supports_vision, result=None, error=None):
        self.name = name
        self.supports_vision = supports_vision
        self.result = result
        self.error = error
        self.image_calls = 0
        self.text_calls = 0

    def available(self):
        return True

    def _answer(self):
        if self.error:
            raise self.error
        return Answer(question="q", answer=self.result, provider=self.name)

    def analyze_image(self, image, language="auto"):
        self.image_calls += 1
        return self._answer()

    def analyze_text(self, text, language="auto"):
        self.text_calls += 1
        self.last_text = text
        return self._answer()


def test_pipeline_uses_first_working_vision_provider(config):
    primary = StubProvider("gemini", True, result="A")
    secondary = StubProvider("openrouter", True, result="B")
    pipeline = AnalysisPipeline(config, providers=[primary, secondary])
    answer = pipeline.analyze_prepared(IMAGE)
    assert (answer.answer, answer.provider) == ("A", "gemini")
    assert secondary.image_calls == 0


def test_pipeline_falls_back_to_next_vision_provider(config):
    primary = StubProvider("gemini", True, error=ProviderError("quota exceeded"))
    secondary = StubProvider("openrouter", True, result="B")
    pipeline = AnalysisPipeline(config, providers=[primary, secondary])
    assert pipeline.analyze_prepared(IMAGE).provider == "openrouter"


def test_pipeline_falls_back_to_ocr_and_deepseek(config):
    vision = StubProvider("gemini", True, error=ProviderError("503 unavailable"))
    text = StubProvider("deepseek", False, result="C")
    calls = []

    def fake_ocr(source, language):
        calls.append(language)
        return "What is 2+2? A) 3 B) 4 C) 5"

    pipeline = AnalysisPipeline(config, providers=[vision, text], ocr=fake_ocr)
    answer = pipeline.analyze_prepared(IMAGE)
    assert (answer.answer, answer.provider) == ("C", "deepseek")
    assert text.text_calls == 1 and text.image_calls == 0
    assert calls == ["auto"]  # OCR ran exactly once
    assert "2+2" in text.last_text


def test_pipeline_reports_all_failures(config):
    vision = StubProvider("gemini", True, error=ProviderError("bad key"))
    text = StubProvider("deepseek", False, error=ProviderError("timeout"))
    pipeline = AnalysisPipeline(config, providers=[vision, text], ocr=lambda s, l: "text")
    with pytest.raises(AnalysisError) as excinfo:
        pipeline.analyze_prepared(IMAGE)
    assert "gemini" in str(excinfo.value) and "deepseek" in str(excinfo.value)


def test_pipeline_without_keys_raises(config):
    with pytest.raises(AnalysisError) as excinfo:
        AnalysisPipeline(config).analyze_prepared(IMAGE)
    assert "API key" in str(excinfo.value)


def test_provider_chain_from_config(config, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    config.openrouter_models = "google/gemini-2.5-flash,deepseek/deepseek-chat"
    providers = AnalysisPipeline(config).build_providers()
    assert [p.model for p in providers] == [
        "google/gemini-2.5-flash",
        "deepseek/deepseek-chat",
    ]
    assert [p.supports_vision for p in providers] == [True, False]


def test_preferred_provider_moves_to_front(config, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k1")
    monkeypatch.setenv("GEMINI_API_KEY", "k2")
    config.preferred_provider = "openrouter"
    names = [p.name for p in AnalysisPipeline(config).build_providers()]
    assert names[0].startswith("openrouter")
