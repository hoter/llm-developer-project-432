"""Нормализация текста документа.

Перенос через дефис склеивается, лигатуры и лишние пробелы схлопываются.
Колонтитул — строка, повторяющаяся на ВСЕХ страницах: правило «на большинстве»
на двухстраничном документе вымело бы весь текст.
"""
import re
from collections import Counter

from app.parsers import Block

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


def clean_text(text: str) -> str:
    """Лигатуры, переносы, пробелы — к одному виду."""
    for ligature, replacement in _LIGATURES.items():
        text = text.replace(ligature, replacement)
    text = text.replace("\u00ad", "")
    text = _HYPHEN_BREAK.sub("", text)
    text = _SPACES.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = _BLANK_LINES.sub("\n", text)
    return text.strip()


def normalize(blocks: list[Block]) -> list[Block]:
    """Почистить текст, убрать колонтитулы и заполнить секции."""
    pages = {
        block.metadata.get("page")
        for block in blocks
        if block.kind == "text" and block.metadata.get("page") is not None
    }

    repeated: set[str] = set()
    if len(pages) >= 2:
        seen: Counter[str] = Counter()
        for block in blocks:
            if block.kind != "text":
                continue
            for line in _lines(block.content):
                key = _line_key(line)
                if key:
                    seen[key] += 1
        repeated = {key for key, count in seen.items() if count == len(pages)}

    result: list[Block] = []
    for block in blocks:
        if block.kind == "table":
            rows = [[clean_text(cell) for cell in row] for row in block.rows]
            result.append(
                Block(
                    content="\n".join(" | ".join(row) for row in rows),
                    kind="table",
                    rows=rows,
                    metadata=dict(block.metadata),
                )
            )
            continue

        text = "\n".join(
            line for line in _lines(clean_text(block.content))
            if _line_key(line) not in repeated
        )
        if not text:
            continue
        metadata = dict(block.metadata)
        if not metadata.get("section"):
            metadata["section"] = _derive_section(text)
        result.append(Block(content=text, metadata=metadata))
    return result


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _line_key(line: str) -> str | None:
    if not line or len(line) > 120:
        return None
    return re.sub(r"\d+", "#", " ".join(line.lower().split()))


def _derive_section(text: str) -> str:
    for line in _lines(text):
        lowered = line.lower()
        if "@" in line or "www." in lowered or line.isdigit():
            continue
        return line[:80]
    return ""
