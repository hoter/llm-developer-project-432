"""XLSX: спецификация «артикул → параметры».

Заголовки колонок лежат первой строкой и обязательны: «800» без «Мощность, Вт»
ничего не значит. Каждая строка превращается в текст
«KTL-1700: Бренд КеттлПро; Мощность, Вт 2200; …» — так её находит поиск
по смыслу.
"""
from pathlib import Path

from openpyxl import load_workbook

from app.parsers import Block, ParseError, row_to_text


def parse_xlsx(path: Path) -> list[Block]:
    try:
        workbook = load_workbook(str(path), data_only=True, read_only=True)
    except Exception as exc:
        raise ParseError(f"не удалось открыть XLSX: {exc}") from exc

    blocks: list[Block] = []
    for sheet_number, sheet in enumerate(workbook.worksheets, start=1):
        rows = [list(row) for row in sheet.iter_rows(values_only=True)]
        if not rows:
            continue

        headers = ["" if cell is None else str(cell).strip() for cell in rows[0]]
        if not any(headers):
            raise ParseError(f"лист «{sheet.title}» начинается без заголовков колонок")

        for row_number, row in enumerate(rows[1:], start=2):
            values = ["" if cell is None else str(cell).strip() for cell in row]
            if not any(values):
                continue
            text, article, brand = row_to_text(headers, values)
            if not text:
                continue
            blocks.append(
                Block(
                    text=text,
                    page=sheet_number,
                    section=sheet.title,
                    article=article,
                    brand=brand,
                    kind="table",
                    metadata={"headers": headers, "row": row_number, "sheet": sheet.title},
                )
            )

    if not blocks:
        raise ParseError("в XLSX нет строк со значениями")
    return blocks
