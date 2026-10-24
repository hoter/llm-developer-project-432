"""Разбор выданных документов и нормализация."""
from pathlib import Path

import pytest

from app.parsers.docx import parse_docx
from app.parsers.normalizer import clean_text, normalize
from app.parsers.pdf import PdfNoTextLayer, parse_pdf
from app.services.documents import parse_to_chunks

DATA = Path(__file__).resolve().parent.parent / "data"


def test_pdf_pages_and_tables():
    blocks = parse_pdf((DATA / "blender_passport.pdf").read_bytes())
    full = "\n".join(block.content for block in blocks)

    for probe in ("МиксерПро 800", "BLD-800", "800 Вт", "24 месяца"):
        assert probe in full
    tables = [block for block in blocks if block.kind == "table"]
    assert len(tables) == 2
    assert len(tables[0].rows) == 13


def test_scanned_pdf_rejected():
    with pytest.raises(PdfNoTextLayer):
        parse_pdf((DATA / "boiler_scan.pdf").read_bytes())


def test_docx_keeps_contacts_and_prices():
    blocks = parse_docx((DATA / "blender_kp.docx").read_bytes())
    full = "\n".join(block.content for block in blocks)
    assert "+7 926 555-14-08" in full
    assert "2 190" in full
    assert len([b for b in blocks if b.kind == "table"]) == 1


def test_xlsx_rows_become_chunks_with_articul():
    chunks = parse_to_chunks((DATA / "kettle_spec.xlsx").read_bytes(), "xlsx", "doc1")
    full = "\n".join(chunk["text"] for chunk in chunks)
    for articul in ("KTL-1700", "KTL-1000", "KTL-THRM"):
        assert articul in full
    assert len([c for c in chunks if c["metadata"].get("articul")]) == 3


def test_footer_stripped_from_two_page_pdf():
    blocks = normalize(parse_pdf((DATA / "blender_passport.pdf").read_bytes()))
    full = "\n".join(block.content for block in blocks)
    assert "стр. 1" not in full
    assert "стр. 2" not in full


def test_clean_text_glues_hyphenation():
    assert clean_text("мощ-\nность") == "мощность"
    assert clean_text("слева  справа") == "слева справа"
