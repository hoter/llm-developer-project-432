"""Контракт карточки: валидация с лечением и точечная переделка."""
import asyncio
import json

import pytest

from app.schemas import CardDraft, Seo, SourceRef
from app.services import structured


def _card(**overrides) -> dict:
    data = {
        "title": "МиксерПро 800 — блендер",
        "description": "Погружной блендер.",
        "characteristics": {"Мощность": "800 Вт"},
        "benefits": ["Металлическая ножка"],
        "seo": {"title": "Блендер", "description": "Мощный", "keywords": ["блендер"]},
        "sources": [{"chunk_id": "c1", "doc_id": "d1", "page": 3, "score": 0.9}],
        "missing_fields": [],
        "confidence": 0.8,
    }
    data.update(overrides)
    return data


def test_schema_defaults_and_limits():
    assert Seo().title == "" and Seo().keywords == []
    ref = SourceRef(chunk_id="c1")
    assert ref.doc_id == "" and ref.page is None and ref.score is None

    with pytest.raises(Exception):
        CardDraft.model_validate(_card(title="A" * 61))
    with pytest.raises(Exception):
        CardDraft.model_validate(_card(confidence=1.5))

    card = CardDraft.model_validate(_card(characteristics={"Мощность": "800 Вт", "Цвет": " "}))
    assert "Цвет" not in card.characteristics


def _patch(monkeypatch, scenario):
    calls = []

    async def fake_run(agent, prompt):
        calls.append(prompt)
        item = scenario[len(calls) - 1]
        return json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else item

    monkeypatch.setattr(structured, "run_agent", fake_run)
    return calls


def test_validate_or_retry_success(monkeypatch):
    calls = _patch(monkeypatch, [_card()])
    card = asyncio.run(structured.validate_or_retry("промпт"))
    assert card.title.startswith("МиксерПро")
    assert len(calls) == 1


def test_validate_or_retry_sends_error_back(monkeypatch):
    calls = _patch(monkeypatch, [_card(title="A" * 80), _card()])
    card = asyncio.run(structured.validate_or_retry("промпт"))
    assert len(calls) == 2
    assert "60" in calls[1]
    assert card.title == _card()["title"]


def test_validate_or_retry_gives_up(monkeypatch):
    _patch(monkeypatch, [_card(title="A" * 80)] * 3)
    with pytest.raises(structured.CardValidationError):
        asyncio.run(structured.validate_or_retry("промпт"))


def test_regenerate_only_one_field(monkeypatch):
    original = CardDraft.model_validate(_card())
    fixed = CardDraft.model_validate(_card(title="Короткий заголовок"))

    async def fake_run(agent, prompt):
        assert "title" in prompt
        return fixed.model_dump_json()

    monkeypatch.setattr(structured, "run_agent", fake_run)
    result = asyncio.run(structured.regenerate_field(original, "title", "длинно"))
    assert result.title == "Короткий заголовок"
    assert result.description == original.description


def test_confidence_gate():
    assert structured.confidence_gate(CardDraft.model_validate(_card(confidence=0.3))) == "needs_review"
    assert structured.confidence_gate(CardDraft.model_validate(_card(confidence=0.87))) == "done"
