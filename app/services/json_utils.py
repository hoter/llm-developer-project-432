"""Разбор ответа модели: JSON приходит грязным.

Чистый JSON, markdown-забор, текст до и после — разбираем; мусор и пустой
ответ превращаем в LLMJsonError.
"""
import json
from typing import Any


class LLMJsonError(ValueError):
    """Ответ модели не удалось разобрать как JSON."""


# Прежнее имя, оставлено для совместимости.
JsonParseError = LLMJsonError


def extract_json(raw: Any) -> str:
    """Вырезать JSON-объект из ответа модели."""
    text = "" if raw is None else str(raw).strip()
    if not text:
        raise LLMJsonError("пустой ответ модели")

    start = text.find("{")
    if start == -1:
        start = text.find("[")
    if start == -1:
        raise LLMJsonError("в ответе модели нет JSON-объекта")

    end = _matching_bracket(text, start)
    if end is None:
        raise LLMJsonError("JSON в ответе модели не закрыт")

    snippet = text[start : end + 1]
    try:
        json.loads(snippet)
    except json.JSONDecodeError as exc:
        raise LLMJsonError(f"невалидный JSON: {exc.msg} (позиция {exc.pos})") from exc
    return snippet


def parse_llm_json(raw: Any) -> Any:
    """Разобрать сырой ответ модели в Python-объект."""
    return json.loads(extract_json(raw))


def parse_json(raw: Any) -> Any:
    return parse_llm_json(raw)


def _matching_bracket(text: str, start: int) -> int | None:
    pairs = {"{": "}", "[": "]"}
    stack: list[str] = []
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        char = text[i]
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
        elif char in pairs:
            stack.append(pairs[char])
        elif char in "}]":
            if not stack or stack.pop() != char:
                return None
            if not stack:
                return i
    return None
