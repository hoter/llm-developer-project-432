"""PDF: текст постранично.

Таблицы в pdf — отдельная задача про геометрию страницы, в базовый путь не
входит. Зато отсутствие текстового слоя — входит: скан без OCR нельзя тихо
пропустить, у документа должен быть отказ с причиной.
"""
from pathlib import Path

from pypdf import PdfReader

from app.parsers import Block, ParseError, ScannedDocument


def parse_pdf(path: Path) -> list[Block]:
    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # повреждённый файл
        raise ParseError(f"не удалось открыть PDF: {exc}") from exc

    blocks: list[Block] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            raise ParseError(f"страница {number}: не удалось извлечь текст: {exc}") from exc
        text = text.strip()
        if text:
            blocks.append(Block(text=text, page=number))

    if not blocks:
        raise ScannedDocument(
            "в PDF нет текстового слоя: похоже на скан, а распознавание (OCR) "
            "в базовый путь не входит"
        )
    return blocks
