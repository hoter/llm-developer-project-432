"""Резка на фрагменты: текст с перекрытием, таблицы по строкам.

Строку таблицы рвать нельзя; каждый фрагмент несёт заголовки колонок и
метаданные: документ, страницу, секцию, артикул.
"""
from app.parsers import Block, row_to_text

CHUNK_SIZE = 900
CHUNK_OVERLAP = 180


def chunk_blocks(blocks: list[Block], doc_id: str) -> list[dict]:
    """Разрезать блоки на фрагменты-словари."""
    chunks: list[dict] = []
    text_group: list[Block] = []

    def flush() -> None:
        if not text_group:
            return
        first = text_group[0]
        metadata = first.metadata
        text = "\n".join(block.content for block in text_group)
        for piece in split_text(text, CHUNK_SIZE, CHUNK_OVERLAP):
            chunks.append(
                {
                    "text": piece,
                    "metadata": {
                        "doc_id": doc_id,
                        "page": metadata.get("page"),
                        "section": metadata.get("section") or "",
                    },
                }
            )
        text_group.clear()

    for block in blocks:
        if block.kind == "table":
            flush()
            chunks.extend(_table_chunks(block, doc_id))
            continue
        if text_group:
            previous = text_group[0].metadata
            current = block.metadata
            same = (
                previous.get("page") == current.get("page")
                and (previous.get("section") or "") == (current.get("section") or "")
            )
            if not same:
                flush()
        text_group.append(block)
    flush()
    return chunks


def split_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    pieces: list[str] = []
    current: list[str] = []
    current_len = 0

    for word in text.split():
        addition = len(word) + (1 if current else 0)
        if current and current_len + addition > size:
            pieces.append(" ".join(current))
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
        pieces.append(" ".join(current))
    return pieces


def _table_chunks(block: Block, doc_id: str) -> list[dict]:
    rows = block.rows
    if len(rows) < 2:
        return []
    headers = rows[0]
    page = block.metadata.get("page")
    section = block.metadata.get("section") or ""

    chunks: list[dict] = []
    for row in rows[1:]:
        text, articul = _row_text(headers, row)
        if not text:
            continue
        metadata = {
            "doc_id": doc_id,
            "page": page,
            "section": section,
        }
        if articul:
            metadata["articul"] = articul
        chunks.append({"text": text, "metadata": metadata})
    return chunks


def _row_text(headers: list[str], row: list[str]) -> tuple[str, str | None]:
    if len(headers) == 2 and headers[0].strip().lower() in {"параметр", "показатель"}:
        name = row[0].strip() if row else ""
        value = row[1].strip() if len(row) > 1 else ""
        return (f"{name}: {value}" if name else value), None
    return row_to_text(headers, row)
