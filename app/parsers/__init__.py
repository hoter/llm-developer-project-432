"""Разбор документов поставщиков: общие типы и диспетчер по расширению.

Каждый формат — свой модуль (pdf.py, docx.py, xlsx.py). Наружу отдаём
список блоков: текст, страница, секция, артикул и бренд, если они известны.
Блоки — ещё не фрагменты: нормализацию и резку делает следующий слой.
"""
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal


class ParseError(Exception):
    """Документ не удалось разобрать. Причина показывается пользователю."""


class UnsupportedFormat(ParseError):
    """Расширение файла не поддерживается."""


class ScannedDocument(ParseError):
    """В документе нет текстового слоя (скан без OCR)."""


@dataclass
class Block:
    """Структурная единица документа: страница pdf, абзац, строка таблицы."""

    text: str
    page: int | None = None
    section: str | None = None
    article: str | None = None
    brand: str | None = None
    kind: Literal["text", "table"] = "text"
    metadata: dict = field(default_factory=dict)


ARTICLE_HEADERS = {"артикул", "sku", "article", "код"}
BRAND_HEADERS = {"бренд", "brand", "производитель"}


def row_to_text(
    headers: list[str], values: list[str]
) -> tuple[str, str | None, str | None]:
    """Строка таблицы → «артикул: параметр значение; параметр значение».

    Артикул выносится в префикс (по нему ищут и фильтруют), бренд остаётся
    и в тексте, и в метаданных. Пустые ячейки пропускаются.
    """
    article: str | None = None
    brand: str | None = None
    parts: list[str] = []

    for header, value in zip(headers, values):
        if value is None:
            continue
        cell = str(value).strip()
        if not cell:
            continue
        name = str(header).strip()
        normalized = name.lower()
        if normalized in ARTICLE_HEADERS:
            article = cell
            continue
        if normalized in BRAND_HEADERS:
            brand = cell
        parts.append(f"{name} {cell}")

    prefix = f"{article}: " if article else ""
    return prefix + "; ".join(parts), article, brand


def parse_document(path: Path) -> list[Block]:
    """Разобрать файл по расширению."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from app.parsers.pdf import parse_pdf

        return parse_pdf(path)
    if suffix == ".docx":
        from app.parsers.docx import parse_docx

        return parse_docx(path)
    if suffix == ".xlsx":
        from app.parsers.xlsx import parse_xlsx

        return parse_xlsx(path)
    raise UnsupportedFormat(f"формат «{suffix or 'без расширения'}» не поддерживается")


def replace_text(block: Block, text: str) -> Block:
    """Копия блока с новым текстом (dataclass неизменяем по смыслу)."""
    return replace(block, text=text)
