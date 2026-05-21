"""JSON/JSONC handler for SharedKeyedMapLayout shared files."""
from __future__ import annotations

import json
from collections.abc import Mapping, MutableMapping
from typing import Any

from agents_sync.formats.jsonc_tokenizer import normalize_jsonc, strip_utf8_bom


def deserialize(text: str) -> MutableMapping[str, Any]:
    text = strip_utf8_bom(text)
    if not text or not text.strip():
        return {}
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        result = json.loads(normalize_jsonc(text))
    if not isinstance(result, dict):
        raise ValueError("shared keyed-map root must be a JSON object")
    return result


def serialize(obj: Mapping[str, Any]) -> str:
    return json.dumps(obj, indent=2, sort_keys=False) + "\n"
