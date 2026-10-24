"""Сборка контекста: метки, дедупликация, предел размера."""
from app.rag.context import build_context


def _chunk(chunk_id: str, text: str, **overrides) -> dict:
    chunk = {
        "id": chunk_id,
        "text": text,
        "filename": "kettle_spec.xlsx",
        "page": 1,
        "section": "Спецификация",
        "article": "KTL-1700",
        "brand": "КеттлПро",
    }
    chunk.update(overrides)
    return chunk


def test_each_source_is_identifiable():
    context = build_context(
        [_chunk("1", "Мощность 2200 Вт"), _chunk("2", "Объём 1,7 л")],
        max_chars=6000,
    )

    assert [source.source_id for source in context.sources] == ["S1", "S2"]
    assert "[S1]" in context.text and "[S2]" in context.text
    assert "документ: kettle_spec.xlsx" in context.text
    assert "страница: 1" in context.text
    assert "секция: Спецификация" in context.text


def test_identical_texts_from_different_documents_are_deduplicated():
    context = build_context(
        [
            _chunk("1", "Мощность 2200 Вт", filename="a.pdf"),
            _chunk("2", "Мощность 2200 Вт", filename="b.pdf"),
        ],
        max_chars=6000,
    )

    assert len(context.sources) == 1
    assert context.sources[0].chunk_id == "1"
    assert context.text.count("Мощность 2200 Вт") == 1


def test_context_respects_size_limit():
    long_text = "слово " * 500
    context = build_context(
        [_chunk("1", long_text), _chunk("2", "второй фрагмент")],
        max_chars=200,
    )

    assert len(context.text) <= 200
    assert len(context.sources) == 1
    assert context.text.endswith("...")


def test_empty_chunks_are_skipped():
    context = build_context([_chunk("1", "   "), _chunk("2", "полезный текст")])
    assert [source.chunk_id for source in context.sources] == ["2"]
