"""Метрики: нормализация и поддержка цитат."""
from app.schemas import CardDraft, SourceRef
from evals.metrics import characteristic_match, citation_support, normalize_value


def _card(chunk_id: str = "c1") -> CardDraft:
    return CardDraft(
        title="Блендер 800 Вт",
        description="Погружной блендер.",
        characteristics={"Мощность": "800 Вт"},
        sources=[SourceRef(chunk_id=chunk_id)],
    )


def test_normalization():
    assert normalize_value("800 Вт") == normalize_value("800 вт.")
    assert normalize_value("1,7 л") == normalize_value("1.7 л")


def test_characteristic_match():
    result = characteristic_match(
        {"Мощность": "800 Вт", "Цвет": "графит"}, {"Мощность": "800 вт"}
    )
    assert result["score"] == 0.5
    assert result["missed"] == ["Цвет"]


def test_citation_support_checks_source_text_and_page():
    chunks = {"c1": {"text": "Мощность 800 Вт", "metadata": {"page": 1}}}
    probes = {"Мощность": {"page": 1, "text_contains": "800 Вт"}}

    assert citation_support(_card(), probes, chunks)["score"] == 1.0
    assert citation_support(_card(), {"Мощность": {"page": 2, "text_contains": "800 Вт"}}, chunks)["score"] == 0.0
    assert citation_support(_card(), {"Мощность": {"page": None, "text_contains": "24 месяца"}}, chunks)["score"] == 0.0
