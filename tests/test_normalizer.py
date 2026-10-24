"""Нормализация: переносы, лигатуры, пробелы и ловушка с колонтитулами."""
from app.parsers import Block
from app.parsers.normalizer import normalize_blocks, normalize_text


def test_hyphen_break_is_glued():
    assert normalize_text("мощ-\nность 800 Вт") == "мощность 800 Вт"


def test_ligatures_and_extra_spaces():
    assert normalize_text("ﬁle  with   spaces") == "file with spaces"
    assert normalize_text("мощность   800\u00a0Вт") == "мощность 800 Вт"


def test_soft_hyphen_removed():
    assert normalize_text("мощ\u00adность") == "мощность"


def test_two_page_document_keeps_repeated_lines():
    """Ловушка: на двух страницах «большинство» — это одна страница."""
    blocks = [
        Block(text="ООО «ТехноДом» — стр. 1\nПервый абзац", page=1),
        Block(text="ООО «ТехноДом» — стр. 2\nВторой абзац", page=2),
    ]

    result = normalize_blocks(blocks)

    joined = "\n".join(block.text for block in result)
    assert "ООО «ТехноДом»" in joined
    assert "Первый абзац" in joined
    assert "Второй абзац" in joined


def test_long_document_footer_removed():
    bodies = [
        "Первый абзац про мощность",
        "Второй абзац про гарантию",
        "Третий абзац про уход",
        "Четвёртый абзац про доставку",
    ]
    blocks = [
        Block(
            text=(
                f"ООО «ТехноДом» — стр. {page}\n"
                f"{body}\n"
                "Подвал: supplies@technodom.example"
            ),
            page=page,
        )
        for page, body in enumerate(bodies, start=1)
    ]

    result = normalize_blocks(blocks)
    joined = "\n".join(block.text for block in result)

    assert "ООО «ТехноДом»" not in joined
    assert "supplies@technodom.example" not in joined
    assert "Второй абзац про гарантию" in joined


def test_section_filled_when_parser_did_not_know_it():
    blocks = [Block(text="ПАСПОРТ ИЗДЕЛИЯ\nБлендер погружной", page=1)]
    result = normalize_blocks(blocks)
    assert result[0].section == "ПАСПОРТ ИЗДЕЛИЯ"
