"""DOCX: параграфы + таблицы, заголовок — граница секции.

Параграфы и таблицы идут вперемешку, поэтому обходим тело документа в
порядке следования (`iter_inner_content`), а не отдельными списками.
Строка таблицы превращается в тот же текст «артикул: параметр значение»,
что и в xlsx.
"""
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.parsers import Block, ParseError, row_to_text


def parse_docx(path: Path) -> list[Block]:
    try:
        document = Document(str(path))
    except Exception as exc:
        raise ParseError(f"не удалось открыть DOCX: {exc}") from exc

    blocks: list[Block] = []
    section: str | None = None

    try:
        content = document.iter_inner_content()
    except AttributeError:  # старый python-docx
        content = list(document.paragraphs) + list(document.tables)

    for item in content:
        if isinstance(item, Paragraph):
            text = item.text.strip()
            if not text:
                continue
            style = (item.style.name or "").lower() if item.style else ""
            if style.startswith("heading") or style == "title":
                section = text
            blocks.append(Block(text=text, page=1, section=section))
        elif isinstance(item, Table):
            blocks.extend(_table_blocks(item, section))

    if not blocks:
        raise ParseError("в DOCX нет текста")
    return blocks


def _table_blocks(table: Table, section: str | None) -> list[Block]:
    rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
    if len(rows) < 2:
        return []
    headers = rows[0]
    if not any(headers):
        raise ParseError("таблица в DOCX без строки заголовков")

    blocks: list[Block] = []
    for row_number, row in enumerate(rows[1:], start=2):
        text, article, brand = row_to_text(headers, row)
        if not text:
            continue
        blocks.append(
            Block(
                text=text,
                page=1,
                section=section,
                article=article,
                brand=brand,
                kind="table",
                metadata={"headers": headers, "row": row_number},
            )
        )
    return blocks
