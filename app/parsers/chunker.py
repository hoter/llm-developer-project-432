"""Резка на фрагменты.

Текст режется фиксированным размером с перекрытием: утверждение на границе
не должно потеряться. Таблица режется по строкам: строку рвать нельзя, и
каждый фрагмент несёт заголовки колонок — иначе «800» без «Мощность, Вт»
бессмысленно.

Каждый фрагмент уносит метаданные: документ, страницу, секцию, артикул,
бренд.
"""
from dataclasses import dataclass, field

from app.parsers import Block

CHUNK_SIZE = 900
CHUNK_OVERLAP = 180


@dataclass
class Chunk:
    text: str
    page: int | None
    section: str
    article: str | None = None
    brand: str | None = None
    metadata: dict = field(default_factory=dict)


def chunk_blocks(
    blocks: list[Block],
    *,
    document: str,
    size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[Chunk]:
    """Разрезать блоки документа на фрагменты."""
    chunks: list[Chunk] = []
    for group in _groups(blocks):
        if group[0].kind == "table":
            chunks.extend(_table_chunks(group, document))
        else:
            chunks.extend(_text_chunks(group, document, size, overlap))
    return chunks


def split_text(text: str, size: int, overlap: int) -> list[str]:
    """Нарезать текст по словам с перекрытием."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for word in text.split():
        addition = len(word) + (1 if current else 0)
        if current and current_len + addition > size:
            chunks.append(" ".join(current))
            tail: list[str] = []
            tail_len = 0
            for previous in reversed(current):
                if tail_len + len(previous) + 1 > overlap:
                    break
                tail.insert(0, previous)
                tail_len += len(previous) + 1
            current = tail
            current_len = tail_len
            addition = len(word) + (1 if current else 0)

        current.append(word)
        current_len += addition

    if current:
        chunks.append(" ".join(current))
    return chunks


def _groups(blocks: list[Block]) -> list[list[Block]]:
    """Подряд идущие блоки с одной страницей, секцией и видом."""
    groups: list[list[Block]] = []
    for block in blocks:
        if groups:
            last = groups[-1][0]
            if (
                block.kind == last.kind
                and block.page == last.page
                and block.section == last.section
                and block.kind == "text"
            ):
                groups[-1].append(block)
                continue
        groups.append([block])
    return groups


def _text_chunks(
    group: list[Block], document: str, size: int, overlap: int
) -> list[Chunk]:
    text = "\n".join(block.text for block in group)
    first = group[0]
    chunks = []
    for piece in split_text(text, size, overlap):
        chunks.append(
            Chunk(
                text=piece,
                page=first.page,
                section=first.section or "Документ",
                metadata={"document": document, "kind": "text"},
            )
        )
    return chunks


def _table_chunks(group: list[Block], document: str) -> list[Chunk]:
    """Каждая строка — отдельный фрагмент с заголовками колонок."""
    chunks: list[Chunk] = []
    for block in group:
        headers = [str(h).strip() for h in (block.metadata.get("headers") or []) if str(h).strip()]
        header_line = "Колонки: " + " | ".join(headers) if headers else ""
        text = f"{header_line}\n{block.text}".strip() if header_line else block.text
        chunks.append(
            Chunk(
                text=text,
                page=block.page,
                section=block.section or "Документ",
                article=block.article,
                brand=block.brand,
                metadata={
                    "document": document,
                    "kind": "table",
                    "headers": headers,
                    "row": block.metadata.get("row"),
                    "sheet": block.metadata.get("sheet"),
                },
            )
        )
    return chunks
