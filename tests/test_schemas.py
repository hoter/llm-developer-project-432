"""Модели карточки: ограничения, которые нельзя обойти промптом."""
import pytest
from pydantic import ValidationError

from app.schemas import TITLE_MAX_LENGTH, CardDraft


def _card(**overrides) -> dict:
    data = {
        "title": "Блендер 800 Вт",
        "description": "Погружной блендер с металлической ножкой.",
        "characteristics": {"Мощность": "800 Вт"},
        "benefits": ["Металлическая ножка"],
        "missing_fields": ["Гарантия"],
        "confidence": 0.8,
        "seo": {"title": "Блендер 800 Вт", "description": "Блендер 800 Вт", "keywords": ["блендер"]},
    }
    data.update(overrides)
    return data


def test_valid_card():
    card = CardDraft.model_validate(_card())
    assert card.confidence == 0.8
    assert card.seo.keywords == ["блендер"]


def test_title_longer_than_limit_rejected():
    with pytest.raises(ValidationError, match="at most"):
        CardDraft.model_validate(_card(title="Б" * (TITLE_MAX_LENGTH + 1)))


def test_title_is_stripped():
    card = CardDraft.model_validate(_card(title="  Блендер 800 Вт  "))
    assert card.title == "Блендер 800 Вт"


def test_empty_title_rejected():
    with pytest.raises(ValidationError):
        CardDraft.model_validate(_card(title="   "))


def test_blank_characteristics_dropped():
    card = CardDraft.model_validate(
        _card(characteristics={"Мощность": "800 Вт", "Цвет": "  ", "Гарантия": ""})
    )
    assert card.characteristics == {"Мощность": "800 Вт"}


def test_confidence_out_of_range_rejected():
    with pytest.raises(ValidationError):
        CardDraft.model_validate(_card(confidence=1.5))
    with pytest.raises(ValidationError):
        CardDraft.model_validate(_card(confidence=-0.1))


def test_field_cannot_be_both_known_and_missing():
    with pytest.raises(ValidationError, match="одновременно"):
        CardDraft.model_validate(
            _card(characteristics={"Гарантия": "12 месяцев"}, missing_fields=["Гарантия"])
        )
