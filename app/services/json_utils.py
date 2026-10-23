"""Разбор ответа модели: JSON приходит грязным.

Модель может вернуть чистый JSON, JSON в markdown-заборе, JSON с
вступительной фразой до и пояснением после — или мусор. Первые три случая
разбираем, четвёртый превращаем в понятную ошибку, а не в трейсбек.
"""
import json
from typing import Any


class JsonParseError(ValueError):
    """Ответ модели не удалось разобрать как JSON."""


def extract_json(raw: Any) -> str:
    """Вырезать JSON-объект из ответа модели.

    Понимает чистый JSON, ```json ... ```, текст до и после. Бросает
    JsonParseError на пустом ответе, мусоре и незакрытом JSON.
    """
    text = "" if raw is None else str(raw).strip()
    if not text:
        raise JsonParseError("пустой ответ модели")

    start = text.find("{")
    if start == -1:
        start = text.find("[")
    if start == -1:
        raise JsonParseError("в ответе модели нет JSON-объекта")

    end = _matching_bracket(text, start)
    if end is None:
        raise JsonParseError("JSON в ответе модели не закрыт")

    snippet = text[start : end + 1]
    try:
        json.loads(snippet)
    except json.JSONDecodeError as exc:
        raise JsonParseError(
            f"невалидный JSON: {exc.msg} (позиция {exc.pos})"
        ) from exc
    return snippet


def parse_json(raw: Any) -> Any:
    """Разобрать ответ модели в Python-объект (см. extract_json)."""
    return json.loads(extract_json(raw))


def _matching_bracket(text: str, start: int) -> int | None:
    """Индекс закрывающей скобки с учётом строк и экранирования."""
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
