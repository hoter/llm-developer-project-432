"""Нормализация текста документа.

Что чиним:
- перенос через дефис («мощ-\\nность» → «мощность») — иначе слово не найдёт
  никакой поиск;
- лигатуры (ﬁ → fi) и мягкие переносы;
- лишние пробелы, табы, пустые строки.

Колонтитулы убираем осторожно: правило «повторяется на большинстве страниц»
на двухстраничном документе выметает весь текст, потому что большинство от
двух — это одна страница. Поэтому на документах короче трёх страниц поиск
колонтитулов не запускается вовсе, а на длинных смотрим только первые и
последние строки страницы.
"""
import re
from collections import Counter
from pathlib import Path

from app.parsers import Block, replace_text

MIN_PAGES_FOR_HEADERS = 3
EDGE_LINES = 2
MAX_HEADER_LINE = 120

_LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "ft",
    "ﬆ": "st",
}
_HYPHEN_BREAK = re.compile(r"(?<=[A-Za-zА-Яа-яЁё])-\s*\n\s*(?=[A-Za-zА-Яа-яЁё])")
_SPACES = re.compile(r"[ \t\u00a0]+")
_BLANK_LINES = re.compile(r"\n{2,}")


def normalize_text(text: str) -> str:
    """Лигатуры, переносы, пробелы — к одному каноническому виду."""
    for ligature, replacement in _LIGATURES.items():
        text = text.replace(ligature, replacement)
    text = text.replace("\u00ad", "")  # мягкий перенос
    text = _HYPHEN_BREAK.sub("", text)
    text = _SPACES.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = _BLANK_LINES.sub("\n", text)
    return text.strip()


def strip_headers_footers(blocks: list[Block]) -> list[Block]:
    """Убрать строки, повторяющиеся на страницах (колонтитулы)."""
    pages = {block.page for block in blocks if block.page is not None}
    if len(pages) < MIN_PAGES_FOR_HEADERS:
        return blocks

    seen: Counter[str] = Counter()
    for block in blocks:
        if block.page is None:
            continue
        lines = _lines(block.text)
        for line in lines[:EDGE_LINES] + lines[-EDGE_LINES:]:
            key = _line_key(line)
            if key:
                seen[key] += 1

    repeated = {key for key, count in seen.items() if count > len(pages) / 2}
    if not repeated:
        return blocks

    cleaned: list[Block] = []
    for block in blocks:
        text = "\n".join(
            line for line in _lines(block.text) if _line_key(line) not in repeated
        ).strip()
        if text:
            cleaned.append(replace_text(block, text))
    return cleaned


def normalize_blocks(blocks: list[Block], *, document_name: str = "") -> list[Block]:
    """Полная нормализация: текст, колонтитулы, секция по умолчанию."""
    prepared = [replace_text(block, normalize_text(block.text)) for block in blocks]
    prepared = [block for block in prepared if block.text]
    prepared = strip_headers_footers(prepared)

    for block in prepared:
        if not block.section:
            block.section = _derive_section(block.text, document_name)
    return prepared


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _line_key(line: str) -> str | None:
    """Ключ строки без цифр: «… — стр. 1» и «… — стр. 2» — один колонтитул."""
    if not line or len(line) > MAX_HEADER_LINE:
        return None
    return re.sub(r"\d+", "#", " ".join(line.lower().split()))


def _derive_section(text: str, document_name: str) -> str:
    for line in _lines(text):
        lowered = line.lower()
        if "@" in line or "www." in lowered or line.isdigit():
            continue
        return line[:80]
    name = Path(document_name).stem if document_name else ""
    return name or "Документ"
