"""DOCX: параграфы и таблицы в порядке документа, заголовок — секция."""
import io

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.parsers import Block, ParseError


def parse_docx(data: bytes) -> list[Block]:
    try:
        document = Document(io.BytesIO(data))
    except Exception as exc:
        raise ParseError(f"не удалось открыть DOCX: {exc}") from exc

    blocks: list[Block] = []
    section: str | None = None

    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            text = item.text.strip()
            if not text:
                continue
            style = (item.style.name or "").lower() if item.style else ""
            if style.startswith("heading") or style == "title":
                section = text
            blocks.append(
                Block(content=text, metadata={"page": 1, "section": section})
            )
        elif isinstance(item, Table):
            rows = [
                [cell.text.strip() for cell in row.cells] for row in item.rows
            ]
            rows = [row for row in rows if any(row)]
            if len(rows) < 2:
                continue
            blocks.append(
                Block(
                    content="\n".join(" | ".join(row) for row in rows),
                    kind="table",
                    rows=rows,
                    metadata={"page": 1, "section": section},
                )
            )

    if not blocks:
        raise ParseError("в DOCX нет текста")
    return blocks
