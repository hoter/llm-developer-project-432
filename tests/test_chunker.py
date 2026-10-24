"""Резка на фрагменты: перекрытие текста и неразрывные строки таблицы."""
from app.parsers import Block
from app.parsers.chunker import chunk_blocks, split_text


def test_long_text_is_split_with_overlap():
    text = " ".join(f"слово{i}" for i in range(300))

    chunks = split_text(text, size=200, overlap=50)

    assert len(chunks) > 5
    for previous, following in zip(chunks, chunks[1:]):
        assert previous.split()[-1] in following.split()


def test_short_text_is_one_chunk():
    assert split_text("короткий текст", size=200, overlap=50) == ["короткий текст"]


def test_table_row_is_not_split_and_headers_repeat():
    headers = ["Артикул", "Мощность, Вт"]
    blocks = [
        Block(
            text=f"ART-{index}: Мощность, Вт {index}00",
            page=1,
            section="Спецификация",
            article=f"ART-{index}",
            brand="Бренд",
            kind="table",
            metadata={"headers": headers, "row": index + 2},
        )
        for index in range(1, 4)
    ]

    chunks = chunk_blocks(blocks, document="spec.xlsx")

    assert len(chunks) == 3
    for index, chunk in enumerate(chunks, start=1):
        assert f"ART-{index}: Мощность, Вт {index}00" in chunk.text
        assert "Колонки: Артикул | Мощность, Вт" in chunk.text
        assert chunk.article == f"ART-{index}"
        assert chunk.brand == "Бренд"
        assert chunk.section == "Спецификация"
        assert chunk.metadata["document"] == "spec.xlsx"


def test_text_chunks_keep_page_and_section():
    blocks = [
        Block(text="Первый абзац", page=2, section="Правила эксплуатации"),
        Block(text="Второй абзац", page=2, section="Правила эксплуатации"),
    ]

    chunks = chunk_blocks(blocks, document="manual.pdf")

    assert len(chunks) == 1
    assert chunks[0].page == 2
    assert chunks[0].section == "Правила эксплуатации"
    assert "Первый абзац" in chunks[0].text
    assert "Второй абзац" in chunks[0].text
