"""Разбор выданных документов: pdf постранично, docx с секциями, xlsx строки."""
from pathlib import Path

import pytest

from app.parsers import ScannedDocument
from app.parsers.docx import parse_docx
from app.parsers.pdf import parse_pdf
from app.parsers.xlsx import parse_xlsx

DATA = Path(__file__).resolve().parent.parent / "data"


def test_pdf_is_split_by_pages():
    blocks = parse_pdf(DATA / "blender_passport.pdf")

    assert [block.page for block in blocks] == [1, 2]
    assert "BLD-800" in blocks[0].text
    assert "800 Вт" in blocks[0].text
    assert "Комплект поставки" in blocks[1].text


def test_scanned_pdf_gets_rejection_with_reason():
    with pytest.raises(ScannedDocument) as error:
        parse_pdf(DATA / "boiler_scan.pdf")

    assert "текстового слоя" in str(error.value)


def test_docx_headings_become_sections():
    blocks = parse_docx(DATA / "blender_kp.docx")

    sections = {block.section for block in blocks}
    assert "Прайс-лист (опт)" in sections
    assert any("Смирнова Анна" in block.text for block in blocks)

    table_rows = [block for block in blocks if block.kind == "table"]
    assert table_rows
    assert table_rows[0].article == "BLD-500"
    assert table_rows[0].section == "Прайс-лист (опт)"
    assert table_rows[0].metadata["headers"][0] == "Артикул"


def test_xlsx_row_becomes_readable_text():
    blocks = parse_xlsx(DATA / "kettle_spec.xlsx")

    assert len(blocks) == 3
    first = blocks[0]
    assert first.article == "KTL-1700"
    assert first.brand == "КеттлПро"
    assert first.text.startswith("KTL-1700: ")
    assert "Мощность, Вт 2200" in first.text
    assert "Объём, л 1,7" in first.text
    assert first.section == "Спецификация"
    assert first.page == 1
    assert all(block.kind == "table" for block in blocks)
