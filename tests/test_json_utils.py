"""Разбор ответа модели: четыре вида ответа из задания."""
import pytest

from app.services.json_utils import JsonParseError, extract_json, parse_json


def test_clean_json():
    assert parse_json('{"title": "Блендер"}') == {"title": "Блендер"}


def test_json_in_markdown_fence():
    raw = '```json\n{"title": "Блендер", "confidence": 0.8}\n```'
    assert parse_json(raw) == {"title": "Блендер", "confidence": 0.8}


def test_json_with_text_before_and_after():
    raw = (
        "Вот черновик карточки, как просили:\n"
        '{"title": "Блендер"}\n'
        "Если нужно, сокращу описание."
    )
    assert parse_json(raw) == {"title": "Блендер"}


def test_json_with_nested_brackets_and_strings():
    raw = 'Ответ: {"a": {"b": [1, 2]}, "c": "скобка } внутри строки"} конец'
    assert parse_json(raw) == {"a": {"b": [1, 2]}, "c": "скобка } внутри строки"}


def test_garbage_raises():
    with pytest.raises(JsonParseError, match="нет JSON"):
        extract_json("Извините, не могу помочь с этим запросом.")


def test_empty_answer_raises():
    with pytest.raises(JsonParseError, match="пустой ответ"):
        extract_json("   \n  ")


def test_none_answer_raises():
    with pytest.raises(JsonParseError, match="пустой ответ"):
        extract_json(None)


def test_unclosed_json_raises():
    with pytest.raises(JsonParseError, match="не закрыт"):
        extract_json('{"title": "Блендер"')
