"""1. JSON parsing / repair and schema validation."""

import pytest

from app.ai.json_utils import JsonRepairError, extract_json
from app.ai.schema import Answer, SchemaError

VALID = '{"question": "2+2?", "answer": "4", "confidence": 0.9, "explanation": "math"}'


def test_plain_json():
    assert extract_json(VALID)["answer"] == "4"


def test_markdown_fence():
    assert extract_json(f"```json\n{VALID}\n```")["answer"] == "4"


def test_prose_around_object():
    text = f"Sure! Here is the result:\n{VALID}\nHope that helps."
    assert extract_json(text)["question"] == "2+2?"


def test_trailing_comma_is_repaired():
    broken = '{"question": "q", "answer": "a", "confidence": 0.5,}'
    assert extract_json(broken)["answer"] == "a"


def test_smart_quotes_are_repaired():
    broken = '{“question”: “q”, “answer”: “a”}'
    assert extract_json(broken)["answer"] == "a"


def test_truncated_object_is_closed():
    broken = '{"question": "q", "answer": "a long unfinished answer'
    recovered = extract_json(broken)
    assert recovered["question"] == "q"
    assert recovered["answer"].startswith("a long unfinished")


def test_raw_newline_inside_string():
    broken = '{"question": "q", "answer": "line one\nline two"}'
    assert "line two" in extract_json(broken)["answer"]


def test_nested_braces_and_strings():
    text = '{"question": "what does {a: 1} mean?", "answer": "a dict"}'
    assert extract_json(text)["question"].endswith("mean?")


@pytest.mark.parametrize("bad", ["", "   ", "no json at all", "[1, 2, 3]"])
def test_unrecoverable_input_raises(bad):
    with pytest.raises(JsonRepairError):
        extract_json(bad)


# -- schema ---------------------------------------------------------------
def test_answer_from_dict_full():
    answer = Answer.from_dict(
        {
            "question": "Capital of France?",
            "answer": "B",
            "answer_text": "Paris",
            "confidence": 0.8,
            "explanation": "why",
        }
    )
    assert answer.is_multiple_choice()
    assert answer.clipboard_text() == "B. Paris"


def test_answer_open_question():
    answer = Answer.from_dict({"question": "Explain TCP", "answer": "A protocol …"})
    assert not answer.is_multiple_choice()
    assert answer.clipboard_text() == "A protocol …"
    assert answer.confidence == 0.0


def test_confidence_normalisation():
    assert Answer.from_dict({"question": "q", "answer": "a", "confidence": "85"}).confidence == 0.85
    assert Answer.from_dict({"question": "q", "answer": "a", "confidence": "0.4"}).confidence == 0.4
    assert Answer.from_dict({"question": "q", "answer": "a", "confidence": "n/a"}).confidence == 0.0
    # a bare number above 1 is read as a percentage
    assert Answer.from_dict({"question": "q", "answer": "a", "confidence": 5}).confidence == 0.05
    assert Answer.from_dict({"question": "q", "answer": "a", "confidence": 150}).confidence == 1.0


def test_list_answer_is_flattened():
    answer = Answer.from_dict({"question": "q", "answer": ["one", "two"]})
    assert answer.answer == "one\ntwo"


@pytest.mark.parametrize(
    "payload",
    [{}, {"question": "q"}, {"answer": "a"}, {"question": "", "answer": ""}, ["not", "a", "dict"]],
)
def test_missing_fields_raise(payload):
    with pytest.raises(SchemaError):
        Answer.from_dict(payload)
