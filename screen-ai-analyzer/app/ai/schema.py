"""The structured answer contract shared by every provider."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

REQUIRED_FIELDS = ("question", "answer")


class SchemaError(ValueError):
    """The model output did not contain a usable answer object."""


@dataclass
class Answer:
    question: str
    answer: str
    confidence: float = 0.0
    explanation: str = ""
    answer_text: Optional[str] = None
    provider: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Answer":
        if not isinstance(data, dict):
            raise SchemaError("model output is not a JSON object")
        missing = [f for f in REQUIRED_FIELDS if not _has_text(data.get(f))]
        if missing:
            raise SchemaError(f"missing field(s): {', '.join(missing)}")
        return cls(
            question=_text(data.get("question")),
            answer=_text(data.get("answer")),
            confidence=_confidence(data.get("confidence")),
            explanation=_text(data.get("explanation")),
            answer_text=_text(data["answer_text"]) if _has_text(data.get("answer_text")) else None,
            provider=_text(data.get("provider")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    # -- presentation -----------------------------------------------------
    def clipboard_text(self) -> str:
        """Only the answer itself - never the raw JSON envelope."""
        if self.answer_text and self.answer_text.strip() != self.answer.strip():
            return f"{self.answer}. {self.answer_text}".strip()
        return self.answer.strip()

    def is_multiple_choice(self) -> bool:
        stripped = self.answer.strip().rstrip(".)")
        return bool(self.answer_text) or (len(stripped) <= 2 and stripped.isalnum())


def _has_text(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "\n".join(str(v).strip() for v in value if str(v).strip())
    if isinstance(value, dict):
        return "\n".join(f"{k}: {v}" for k, v in value.items())
    return str(value).strip()


def _confidence(value: Any) -> float:
    try:
        number = float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        return 0.0
    if number > 1.0:  # models sometimes answer "85" meaning 85%
        number = number / 100.0
    return max(0.0, min(1.0, number))
