from __future__ import annotations

import json
from typing import Any


class JsonExtractionError(ValueError):
    """Raised when model text does not contain a JSON object."""


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        obj = json.loads(_extract_first_object(stripped))

    if not isinstance(obj, dict):
        raise JsonExtractionError("model response must be a JSON object")
    return obj


def _extract_first_object(text: str) -> str:
    start = text.find("{")
    if start == -1:
        raise JsonExtractionError("model response does not contain a JSON object")

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
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

    raise JsonExtractionError("model response contains an incomplete JSON object")

