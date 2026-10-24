"""Персональные данные: детекторы и маскирование.

Телефон, почта, ИНН и номер карты заменяются метками вида ``[телефон №1]``.
Маскирование работает на фрагменте при сборке контекста — до любого
обращения к модели и до записи в лог. Исходные значения не возвращаются
наружу: только вид сущности и метка, иначе они утекут в логи.

ИНН и номер карты проверяются по контрольной сумме. Детектор «по длине»
замаскировал бы артикулы, суммы и даты — защита, ломающая данные, это тоже
отказ, только заметить его труднее.
"""
import re
from dataclasses import dataclass, field
from typing import Literal

PiiKind = Literal["phone", "email", "inn", "card"]

PHONE_LABEL = "телефон"
EMAIL_LABEL = "почта"
INN_LABEL = "ИНН"
CARD_LABEL = "карта"

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


@dataclass
class MaskResult:
    text: str
    entities: list[PiiEntity] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for entity in self.entities:
            result[entity.kind] = result.get(entity.kind, 0) + 1
        return result

    @property
    def found(self) -> bool:
        return bool(self.entities)


def mask(text: str) -> MaskResult:
    """Заменить PII метками. Порядок важен: карта — раньше ИНН."""
    candidates: list[tuple[int, int, PiiKind, str]] = []

    for match in EMAIL_RE.finditer(text):
        candidates.append((match.start(), match.end(), "email", EMAIL_LABEL))
    for match in CARD_RE.finditer(text):
        digits = re.sub(r"\D", "", match.group())
        if is_valid_card(digits):
            candidates.append((match.start(), match.end(), "card", CARD_LABEL))
    for match in INN_RE.finditer(text):
        if is_valid_inn(match.group()):
            candidates.append((match.start(), match.end(), "inn", INN_LABEL))
    for match in PHONE_RE.finditer(text):
        candidates.append((match.start(), match.end(), "phone", PHONE_LABEL))

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
        placeholder = f"[{label} №{counters[label]}]"
        parts.append(placeholder)
        entities.append(PiiEntity(kind=kind, placeholder=placeholder))
        position = end
    parts.append(text[position:])

    return MaskResult(text="".join(parts), entities=entities)


def contains_pii(text: str) -> bool:
    return mask(text).found


def is_valid_inn(value: str) -> bool:
    """ИНН 10 или 12 цифр с проверкой контрольной суммы."""
    digits = re.sub(r"\D", "", value)
    if not (len(digits) == 10 or len(digits) == 12):
        return False
    if len(digits) == 10:
        return _checksum(digits[:9], _INN_WEIGHTS_10) == int(digits[9])
    first = _checksum(digits[:10], _INN_WEIGHTS_11) == int(digits[10])
    second = _checksum(digits[:11], _INN_WEIGHTS_12) == int(digits[11])
    return first and second


def is_valid_card(value: str) -> bool:
    """Номер карты: 16 цифр и алгоритм Луна."""
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


def _checksum(digits: str, weights: list[int]) -> int:
    return sum(int(digit) * weight for digit, weight in zip(digits, weights)) % 11 % 10
