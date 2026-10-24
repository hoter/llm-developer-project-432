"""PDF: текст постранично и таблицы по геометрии страницы.

Отсутствие текстового слоя — отказ с причиной, а не пустой результат.
"""
import io

import pdfplumber

from app.parsers import Block, ParseError


class PdfNoTextLayer(ParseError):
    """В PDF нет текстового слоя: скан без OCR."""


def parse_pdf(data: bytes) -> list[Block]:
    blocks: list[Block] = []
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as exc:
        raise ParseError(f"не удалось открыть PDF: {exc}") from exc

    with pdf:
        for number, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                blocks.append(Block(content=text, metadata={"page": number}))

            for table in page.extract_tables() or []:
                rows = [
                    ["" if cell is None else str(cell).strip() for cell in row]
                    for row in table
                    if row is not None
                ]
                rows = [row for row in rows if any(row)]
                if len(rows) < 2:
                    continue
                content = "\n".join(" | ".join(row) for row in rows)
                blocks.append(
                    Block(
                        content=content,
                        kind="table",
                        rows=rows,
                        metadata={"page": number},
                    )
                )

    if not blocks:
        raise PdfNoTextLayer(
            "в PDF нет текстового слоя: похоже на скан, распознавание (OCR) "
            "в базовый путь не входит"
        )
    return blocks
