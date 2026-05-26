"""String-aware JSONC tokenizer.

Strips ``//`` line comments, ``/* ... */`` block comments, and trailing
commas before ``}`` / ``]`` from JSONC text, leaving the result safe to
feed to stdlib ``json.loads``.

The implementation is a character-by-character state machine rather
than a regex because correct JSONC requires distinguishing comment
syntax from the same byte sequences appearing inside string literals
(e.g. ``"url": "https://example.com"`` must keep its ``//``). A regex
that handles backslash escapes, line endings inside strings, and the
trailing-comma-inside-string case correctly is harder to read and
audit than the state machine.

Edge cases covered by tests:
- ``//`` inside a string literal is preserved
- ``/*`` inside a string literal is preserved
- ``\\"`` does not terminate the string
- ``","`` (comma inside a string) is not treated as trailing
"""
from __future__ import annotations


def strip_utf8_bom(text: str) -> str:
    """Remove a leading UTF-8 BOM if present."""
    return text.removeprefix("﻿")


def normalize_jsonc(text: str) -> str:
    """Strip JSONC comments and trailing commas; returns valid JSON text."""
    without_comments = strip_jsonc_comments(strip_utf8_bom(text))
    return strip_trailing_commas(without_comments)


def strip_jsonc_comments(text: str) -> str:
    """Remove ``//`` and ``/* */`` comments outside of string literals."""
    result: list[str] = []
    in_string = False
    escaped = False
    in_line_comment = False
    in_block_comment = False
    index = 0

    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""

        if in_line_comment:
            if char in "\r\n":
                in_line_comment = False
                result.append(char)
            index += 1
            continue

        if in_block_comment:
            if char == "*" and next_char == "/":
                in_block_comment = False
                index += 2
            else:
                index += 1
            continue

        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "\"":
                in_string = False
            index += 1
            continue

        if char == "\"":
            in_string = True
            result.append(char)
            index += 1
            continue

        if char == "/" and next_char == "/":
            in_line_comment = True
            index += 2
            continue

        if char == "/" and next_char == "*":
            in_block_comment = True
            index += 2
            continue

        result.append(char)
        index += 1

    return "".join(result)


def strip_trailing_commas(text: str) -> str:
    """Remove commas that immediately precede ``}`` or ``]`` (whitespace allowed)."""
    result: list[str] = []
    in_string = False
    escaped = False
    index = 0

    while index < len(text):
        char = text[index]
        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "\"":
                in_string = False
            index += 1
            continue

        if char == "\"":
            in_string = True
            result.append(char)
            index += 1
            continue

        if char == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead < len(text) and text[lookahead] in "}]":
                index += 1
                continue

        result.append(char)
        index += 1

    return "".join(result)
