"""Резка: метаданные и неразрывные строки таблицы."""
from app.parsers import Block
from app.parsers.chunker import chunk_blocks


def test_text_chunks_keep_metadata():
    blocks = [
        Block(content="Первый абзац", metadata={"page": 2, "section": "Правила"}),
        Block(content="Второй абзац", metadata={"page": 2, "section": "Правила"}),
    ]
    chunks = chunk_blocks(blocks, "doc1")

    assert len(chunks) == 1
    assert chunks[0]["metadata"]["doc_id"] == "doc1"
    assert chunks[0]["metadata"]["page"] == 2
    assert chunks[0]["metadata"]["section"] == "Правила"
    assert "Второй абзац" in chunks[0]["text"]


def test_table_row_is_not_split_and_keeps_articul():
    rows = [
        ["Артикул", "Мощность, Вт"],
        ["KTL-1700", "2200"],
        ["KTL-1000", "1800"],
    ]
    blocks = [Block(kind="table", rows=rows, metadata={"page": 1, "section": "Спецификация"})]
    chunks = chunk_blocks(blocks, "doc2")

    assert len(chunks) == 2
    assert chunks[0]["metadata"]["articul"] == "KTL-1700"
    assert chunks[0]["text"].startswith("KTL-1700: ")
    assert "2200" in chunks[0]["text"]
