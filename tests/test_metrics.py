"""Метрики: нормализация значений и проверка источника под цитатой."""
from app.rag.context import ContextSource, DocumentContext
from app.schemas import CardDraft, Citation
from evals.metrics import characteristic_match, citation_support, normalize_value


def _card(citations: list[Citation] | None = None) -> CardDraft:
    return CardDraft(
        title="Блендер 800 Вт",
        description="Погружной блендер.",
        characteristics={"Мощность": "800 Вт", "Объём": "1,5 л"},
        benefits=["Металлическая ножка"],
        missing_fields=[],
        confidence=0.8,
        seo={"title": "Блендер", "description": "Блендер 800 Вт", "keywords": []},
        sources=citations or [],
    )


def _context() -> DocumentContext:
    return DocumentContext(
        text="[S1]\nтекст: Мощность 800 Вт; Объём 1,5 л",
        sources=[
            ContextSource(
                source_id="S1",
                chunk_id="42",
                text="Мощность 800 Вт; Объём 1,5 л",
                filename="blender_passport.pdf",
                page=1,
                section="ПАСПОРТ ИЗДЕЛИЯ",
            )
        ],
    )


def test_normalization_unifies_case_punctuation_and_decimal_comma():
    assert normalize_value("800 Вт") == normalize_value("800 вт.")
    assert normalize_value("1,7 л") == normalize_value("1.7 л")
    assert normalize_value("  Ёмкость ") == normalize_value("емкость")


def test_characteristic_match_counts_only_known_fields():
    result = characteristic_match(
        {"Мощность": "800 Вт", "Цвет": "графитовый"},
        {"Мощность": "800 вт.", "Объём": "1,5 л"},
    )

    assert result["score"] == 0.5
    assert result["matched"] == ["Мощность"]
    assert result["missed"] == ["Цвет"]


def test_citation_support_checks_page_and_text():
    card = _card(
        [Citation(field="characteristics.Мощность", chunk_id="42")]
    )
    probes = {"Мощность": {"page": 1, "text_contains": "800 Вт"}}

    result = citation_support(card, _context(), probes)

    assert result["score"] == 1.0
    assert result["failed"] == []


def test_citation_support_rejects_wrong_page():
    card = _card([Citation(field="characteristics.Мощность", chunk_id="42")])
    probes = {"Мощность": {"page": 2, "text_contains": "800 Вт"}}

    result = citation_support(card, _context(), probes)

    assert result["score"] == 0.0
    assert "страницы" in result["failed"][0]


def test_citation_support_rejects_wrong_chunk_text():
    card = _card([Citation(field="characteristics.Мощность", chunk_id="42")])
    probes = {"Мощность": {"page": None, "text_contains": "24 месяца"}}

    result = citation_support(card, _context(), probes)

    assert result["score"] == 0.0
    assert "нет" in result["failed"][0]


def test_citation_support_requires_citation():
    result = citation_support(
        _card(), _context(), {"Мощность": {"page": 1, "text_contains": "800 Вт"}}
    )

    assert result["score"] == 0.0
    assert "нет ссылки" in result["failed"][0]
