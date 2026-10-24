"""Метрики качества генерации на эталонном наборе.

Сравнение значений — не буквальное: «800 Вт», «800 вт» и «800 Вт.» — одно
и то же. Нормализация здесь часть метрики.
"""
import re
import unicodedata

from app.schemas import CardDraft

_SPACES = re.compile(r"\s+")
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")


def normalize_value(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).strip().lower()
    text = text.replace("ё", "е")
    text = _DECIMAL_COMMA.sub(".", text)
    text = _SPACES.sub(" ", text)
    return text.strip(" .,;:!?\"'«»()[]")


def characteristic_match(expected: dict[str, str], actual: dict[str, str]) -> dict:
    if not expected:
        return {"score": 1.0, "matched": [], "missed": []}
    matched, missed = [], []
    for name, value in expected.items():
        actual_value = actual.get(name)
        if actual_value is not None and normalize_value(actual_value) == normalize_value(value):
            matched.append(name)
        else:
            missed.append(name)
    return {"score": len(matched) / len(expected), "matched": matched, "missed": missed}


def citation_support(
    card: CardDraft, probes: dict[str, dict], chunks: dict[str, dict]
) -> dict:
    """Доля probe-полей, чей заявленный источник содержит нужное значение."""
    if not probes:
        return {"score": 1.0, "checked": 0, "failed": []}

    failed: list[str] = []
    for field, probe in probes.items():
        expected_text = normalize_value(probe.get("text_contains", ""))
        expected_page = probe.get("page")
        supported = False

        for citation in card.sources:
            chunk = chunks.get(str(citation.chunk_id))
            if not chunk:
                continue
            page = (chunk.get("metadata") or {}).get("page")
            if expected_page is not None and page != expected_page:
                continue
            if expected_text and expected_text not in normalize_value(chunk.get("text", "")):
                continue
            supported = True
            break

        if not supported:
            failed.append(f"{field}: источник не содержит ожидаемое значение")

    return {
        "score": (len(probes) - len(failed)) / len(probes),
        "checked": len(probes),
        "failed": failed,
    }
