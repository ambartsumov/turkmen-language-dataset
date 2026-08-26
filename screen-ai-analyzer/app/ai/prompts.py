"""Prompts sent to the providers."""

from __future__ import annotations

SYSTEM_INSTRUCTION = (
    "You analyse a screenshot of a computer screen and help the user with the "
    "task visible on it. Reply with a single JSON object and nothing else."
)

_SCHEMA = """{
  "question": "the full question or task exactly as it appears on screen",
  "answer": "the answer; for multiple choice use just the option label, e.g. \\"B\\"",
  "answer_text": "the full text of the chosen option (multiple choice only, otherwise omit)",
  "confidence": 0.0,
  "explanation": "short reasoning, 1-4 sentences"
}"""


def _language_clause(language: str) -> str:
    language = (language or "auto").strip()
    if not language or language.lower() == "auto":
        return "Answer in the same language as the content on the screen."
    return f"Answer in {language}."


def vision_prompt(language: str = "auto") -> str:
    return f"""Look at this screenshot and do the following:
1. Identify the complete question or task shown on the screen.
2. Identify the answer options if the screen shows any.
3. Solve it.
4. Give a complete, useful answer.

{_language_clause(language)}

Return ONLY this JSON object, with no markdown fences and no extra text:
{_SCHEMA}

If the screen shows an open question rather than multiple choice, omit
"answer_text" and put the full answer in "answer". "confidence" is a number
between 0.0 and 1.0. If no question is visible, describe what is on the screen
in "question" and put the most useful help you can give in "answer"."""


def text_prompt(extracted_text: str, language: str = "auto") -> str:
    return f"""The following text was extracted with OCR from a screenshot of a
screen. OCR is imperfect, so tolerate small errors.

--- BEGIN SCREEN TEXT ---
{extracted_text}
--- END SCREEN TEXT ---

1. Identify the complete question or task.
2. Identify the answer options if there are any.
3. Solve it.
4. Give a complete, useful answer.

{_language_clause(language)}

Return ONLY this JSON object, with no markdown fences and no extra text:
{_SCHEMA}"""


RETRY_SUFFIX = (
    "\n\nYour previous reply was not valid JSON. Reply again with ONLY the JSON "
    "object described above - no prose, no markdown fences."
)
