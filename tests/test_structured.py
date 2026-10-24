"""Валидация с лечением и точечная переделка одного поля."""
import asyncio
import json

import pytest

from app.schemas import CardDraft
from app.services import structured


class FakeAgent:
    name = "Generator"


def _card(**overrides) -> dict:
    data = {
        "title": "Блендер 800 Вт",
        "description": "Погружной блендер с металлической ножкой.",
        "characteristics": {"Мощность": "800 Вт"},
        "benefits": ["Металлическая ножка"],
        "missing_fields": ["Гарантия"],
        "confidence": 0.8,
        "seo": {"title": "Блендер 800 Вт", "description": "Блендер 800 Вт", "keywords": []},
    }
    data.update(overrides)
    return data


def _json(**overrides) -> str:
    return json.dumps(_card(**overrides), ensure_ascii=False)


@pytest.fixture
def fake_llm(monkeypatch):
    prompts: list[str] = []
    scenario: list = []

    async def fake_run(agent, prompt, **kwargs):
        prompts.append(prompt)
        item = scenario.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(structured, "run_agent", fake_run)
    return prompts, scenario


def test_invalid_json_asks_model_again_with_error(fake_llm):
    prompts, scenario = fake_llm
    scenario += ["это совсем не JSON", _json()]

    card = asyncio.run(structured.call_structured(FakeAgent(), "сделай карточку", CardDraft))

    assert isinstance(card, CardDraft)
    assert len(prompts) == 2
    assert "ответ не является JSON" in prompts[1]
    assert "сделай карточку" in prompts[1]


def test_empty_response_gives_clear_error(fake_llm):
    prompts, scenario = fake_llm
    scenario += [""]

    with pytest.raises(structured.StructuredOutputError, match="не удалось получить"):
        asyncio.run(
            structured.call_structured(FakeAgent(), "сделай карточку", CardDraft, max_attempts=1)
        )
    assert len(prompts) == 1


def test_long_title_repaired_targeted(fake_llm):
    """Заголовок починили точечно: описание из первого ответа не переделывали."""
    prompts, scenario = fake_llm
    long_title = "Очень длинный заголовок блендера, который точно не влезет в лимит"
    first_description = "Описание, которое трогать нельзя."
    scenario += [
        _json(title=long_title, description=first_description),
        _json(title="Блендер 800 Вт"),
    ]

    card = asyncio.run(structured.call_structured(FakeAgent(), "сделай карточку", CardDraft))

    assert card.title == "Блендер 800 Вт"
    assert card.description == first_description
    assert len(prompts) == 2
    assert "Исправь ТОЛЬКО поле 'title'" in prompts[1]
    assert "Текущий черновик" in prompts[1]
    assert long_title in prompts[1]


def test_invalid_after_attempts_raises(fake_llm):
    _, scenario = fake_llm
    scenario += ["мусор", "ещё мусор", "и снова мусор"]

    with pytest.raises(structured.StructuredOutputError):
        asyncio.run(
            structured.call_structured(
                FakeAgent(), "сделай карточку", CardDraft, max_attempts=2
            )
        )


def test_validation_error_message_mentions_field(fake_llm):
    prompts, scenario = fake_llm
    scenario += [_json(title="Б" * 90), _json()]

    asyncio.run(structured.call_structured(FakeAgent(), "сделай карточку", CardDraft))

    assert "title" in prompts[1]
    assert "60" in prompts[1] or "at most" in prompts[1]
