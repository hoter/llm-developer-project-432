"""Контекст: опознаваемые фрагменты, дедупликация, предел."""
from app.rag.context import build_context, context_chunk_ids


def _chunk(chunk_id: str, text: str, page: int = 1, section: str = "Секция") -> dict:
    return {
        "chunk_id": chunk_id,
        "text": text,
        "metadata": {"doc_id": "d1", "page": page, "section": section},
        "filename": "doc.pdf",
    }


def test_headers_identify_sources():
    context = build_context([_chunk("c1", "Мощность 800 Вт", page=2, section="Характеристики")])
    header = context.splitlines()[0]

    for part in ("c1", "doc.pdf", "2", "Характеристики"):
        assert part in header
    assert context_chunk_ids(context) == {"c1"}


def test_duplicates_removed():
    context = build_context([_chunk("c1", "одно и то же"), _chunk("c2", "одно и то же")])
    assert context.count("одно и то же") == 1
    assert context_chunk_ids(context) == {"c1"}


def test_size_limit():
    chunks = [_chunk(f"c{i}", "x" * 4000) for i in range(5)]
    assert len(build_context(chunks, max_chars=6000)) < 6100
