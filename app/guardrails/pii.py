"""Персональные данные: детекторы и маскирование.

Телефон, почта, ИНН и номер карты заменяются метками ``[PHONE_1]``,
``[EMAIL_1]``, ``[INN_1]``, ``[CARD_1]``. ИНН и карта проверяются по
контрольной сумме: детектор «по длине» замаскировал бы артикулы и суммы.
"""
import re
from dataclasses import dataclass
from typing import Literal

PiiKind = Literal["phone", "email", "inn", "card"]

PHONE_RE = re.compile(
    r"(?<![\d+])(?:\+7|8)[\s\-()]*\d{3}[\s\-()]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)"
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
CARD_RE = re.compile(r"(?<!\d)(?:\d[ \-]?){15}\d(?!\d)")
INN_RE = re.compile(r"(?<!\d)(?:\d{12}|\d{10})(?!\d)")

_INN_WEIGHTS_10 = [2, 4, 10, 3, 5, 9, 4, 6, 8]
_INN_WEIGHTS_11 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
_INN_WEIGHTS_12 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]


@dataclass(frozen=True)
class PiiEntity:
    kind: PiiKind
    placeholder: str


def mask_pii(text: str) -> tuple[str, list[PiiEntity]]:
    """Заменить PII метками. Возвращает очищенный текст и найденные сущности."""
    candidates: list[tuple[int, int, PiiKind, str]] = []

    for match in EMAIL_RE.finditer(text):
        candidates.append((match.start(), match.end(), "email", "EMAIL"))
    for match in CARD_RE.finditer(text):
        if _luhn_valid(match.group()):
            candidates.append((match.start(), match.end(), "card", "CARD"))
    for match in INN_RE.finditer(text):
        if _inn_checksum(match.group()):
            candidates.append((match.start(), match.end(), "inn", "INN"))
    for match in PHONE_RE.finditer(text):
        candidates.append((match.start(), match.end(), "phone", "PHONE"))

    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    selected: list[tuple[int, int, PiiKind, str]] = []
    occupied_until = -1
    for start, end, kind, label in candidates:
        if start < occupied_until:
            continue
        selected.append((start, end, kind, label))
        occupied_until = end

    counters: dict[str, int] = {}
    entities: list[PiiEntity] = []
    parts: list[str] = []
    position = 0
    for start, end, kind, label in selected:
        parts.append(text[position:start])
        counters[label] = counters.get(label, 0) + 1
        placeholder = f"[{label}_{counters[label]}]"
        parts.append(placeholder)
        entities.append(PiiEntity(kind=kind, placeholder=placeholder))
        position = end
    parts.append(text[position:])

    return "".join(parts), entities


def contains_pii(text: str) -> bool:
    _cleaned, entities = mask_pii(text)
    return bool(entities)


def _inn_checksum(value: str) -> bool:
    """ИНН 10 или 12 цифр с проверкой контрольной суммы."""
    digits = re.sub(r"\D", "", value)
    if len(digits) == 10:
        return _weighted(digits[:9], _INN_WEIGHTS_10) == int(digits[9])
    if len(digits) == 12:
        first = _weighted(digits[:10], _INN_WEIGHTS_11) == int(digits[10])
        second = _weighted(digits[:11], _INN_WEIGHTS_12) == int(digits[11])
        return first and second
    return False


def _weighted(digits: str, weights: list[int]) -> int:
    return sum(int(d) * w for d, w in zip(digits, weights)) % 11 % 10


def _luhn_valid(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if len(digits) != 16:
        return False
    total = 0
    for index, char in enumerate(reversed(digits)):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0
