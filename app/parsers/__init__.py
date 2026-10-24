"""Разбор документов поставщиков: общие типы и помощники.

Block — структурная единица: текст или таблица. Строка таблицы остаётся
строкой, чтобы её нельзя было разорвать при резке.
"""
from dataclasses import dataclass, field


class ParseError(Exception):
    """Документ не удалось разобрать; причина показывается пользователю."""


class UnsupportedFormat(ParseError):
    """Расширение файла не поддерживается."""


@dataclass
class Block:
    content: str = ""
    kind: str = "text"  # text | table
    rows: list[list[str]] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


ARTICLE_HEADERS = {"артикул", "sku", "article", "код"}
BRAND_HEADERS = {"бренд", "brand", "производитель"}


def row_to_text(headers: list[str], values: list[str]) -> tuple[str, str | None]:
    """Строка таблицы → «артикул: параметр значение; …»."""
    articul: str | None = None
    parts: list[str] = []
    for header, value in zip(headers, values):
        cell = "" if value is None else str(value).strip()
        if not cell:
            continue
        name = str(header).strip()
        if name.lower() in ARTICLE_HEADERS:
            articul = cell
            continue
        parts.append(f"{name} {cell}")
    prefix = f"{articul}: " if articul else ""
    return prefix + "; ".join(parts), articul
