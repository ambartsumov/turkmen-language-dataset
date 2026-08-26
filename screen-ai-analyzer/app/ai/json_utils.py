"""Tolerant JSON extraction/repair for model output."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
_SMART_QUOTES = {
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
}


class JsonRepairError(ValueError):
    """Nothing resembling a JSON object could be recovered."""


def extract_json(text: str) -> Dict[str, Any]:
    """Return the first JSON object found in ``text``, repairing if needed.

    Handles the usual model quirks: markdown fences, prose around the object,
    trailing commas, smart quotes and output truncated mid-object.
    """
    if not text or not text.strip():
        raise JsonRepairError("empty model response")

    for candidate in _candidates(text):
        parsed = _try_parse(candidate)
        if isinstance(parsed, dict):
            return parsed
        repaired = _try_parse(_repair(candidate))
        if isinstance(repaired, dict):
            return repaired
    raise JsonRepairError("no JSON object in model response")


def _candidates(text: str):
    stripped = text.strip()
    yield stripped
    for fenced in _FENCE_RE.findall(text):
        yield fenced.strip()
    block = _first_object(stripped)
    if block:
        yield block


def _try_parse(text: str) -> Optional[Any]:
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _first_object(text: str) -> Optional[str]:
    """Slice out the first brace-balanced object, ignoring braces in strings."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text[start:]  # truncated - _repair() will try to close it


def _repair(text: str) -> str:
    fragment = _first_object(text) or text
    for bad, good in _SMART_QUOTES.items():
        fragment = fragment.replace(bad, good)
    fragment = _TRAILING_COMMA_RE.sub(r"\1", fragment)
    fragment = _escape_raw_newlines(fragment)
    fragment = _close(fragment)
    return fragment


def _escape_raw_newlines(text: str) -> str:
    out = []
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            elif char in "\n\r":
                out.append("\\n")
                continue
        elif char == '"':
            in_string = True
        out.append(char)
    return "".join(out)


def _close(text: str) -> str:
    """Close an object that the model truncated mid-way."""
    depth = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
    if in_string:
        text += '"'
    text = _TRAILING_COMMA_RE.sub(r"\1", text.rstrip().rstrip(","))
    return text + "}" * max(0, depth)
