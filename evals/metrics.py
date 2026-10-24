"""Метрики качества генерации на эталонном наборе.

Сравнение значений — не буквальное: «800 Вт», «800 вт» и «800 Вт.» — одно
и то же. Нормализация здесь часть метрики, а не деталь реализации.
"""
import re
import unicodedata

from app.rag.context import DocumentContext
from app.schemas import CardDraft

_SPACES = re.compile(r"\s+")
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")


def normalize_value(value: str) -> str:
    """Канонический вид значения: регистр, ё, десятичная запятая, пунктуация."""
    text = unicodedata.normalize("NFKC", value).strip().lower()
    text = text.replace("ё", "е")
    text = _DECIMAL_COMMA.sub(".", text)
    text = _SPACES.sub(" ", text)
    text = text.replace(" ,", ",")
    return text.strip(" .,;:!?\"'«»()[]")


def characteristic_match(
    expected: dict[str, str], actual: dict[str, str]
) -> dict:
    """Доля характеристик, совпавших с эталоном (с нормализацией)."""
    if not expected:
        return {"score": 1.0, "matched": [], "missed": []}

    matched: list[str] = []
    missed: list[str] = []
    for name, value in expected.items():
        actual_value = actual.get(name)
        if actual_value is not None and normalize_value(actual_value) == normalize_value(value):
            matched.append(name)
        else:
            missed.append(name)

    return {
        "score": len(matched) / len(expected),
        "matched": matched,
        "missed": missed,
    }


def citation_support(
    card: CardDraft, context: DocumentContext, probes: dict[str, dict]
) -> dict:
    """Доля проверок, где заявленный источник действительно содержит значение.

    Проверяем не «есть ли ссылка», а «тот ли это фрагмент»: для каждого
    probe берём цитату поля, находим фрагмент в контексте и сверяем страницу
    и подстроку.
    """
    if not probes:
        return {"score": 1.0, "checked": 0, "failed": []}

    citations = {citation.field: citation.chunk_id for citation in card.sources}
    by_chunk = {source.chunk_id: source for source in context.sources}

    failed: list[str] = []
    for field, probe in probes.items():
        citation_chunk = citations.get(f"characteristics.{field}")
        source = by_chunk.get(citation_chunk) if citation_chunk else None
        if source is None:
            failed.append(f"{field}: нет ссылки на фрагмент из контекста")
            continue

        expected_page = probe.get("page")
        if expected_page is not None and source.page != expected_page:
            failed.append(
                f"{field}: фрагмент со страницы {source.page}, а ответ на {expected_page}"
            )
            continue

        expected_text = probe.get("text_contains", "")
        if expected_text and normalize_value(expected_text) not in normalize_value(source.text):
            failed.append(f"{field}: в источнике нет «{expected_text}»")

    return {
        "score": (len(probes) - len(failed)) / len(probes),
        "checked": len(probes),
        "failed": failed,
    }
