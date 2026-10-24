"""Поиск на заранее заданных векторах: без загрузки модели эмбеддингов.

Проверяем арифметику и SQL: объединение списков, порядок RRF, порог,
фильтры по метаданным и идемпотентность досчёта векторов.
"""
import uuid

import psycopg
import pytest

from app.core.config import settings
from app.core.migrate import apply_migrations
from app.parsers import Block
from app.parsers.chunker import chunk_blocks
from app.rag import reindex
from app.rag.retrieval import SearchFilters
from app.repositories import chunks as chunks_repo
from app.repositories import documents as documents_repo


def _vector(x: float, y: float) -> list[float]:
    vector = [0.0] * settings.embedding_dimension
    vector[0] = x
    vector[1] = y
    return vector


@pytest.fixture(scope="module")
def conn():
    try:
        connection = psycopg.connect(settings.database_url, autocommit=True)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL недоступен: {exc}")
    apply_migrations(connection)
    yield connection
    connection.close()


@pytest.fixture
def corpus(conn):
    """Документ из трёх фрагментов с заданными векторами."""
    document_id = uuid.uuid4().hex[:12]
    stored = documents_repo.create_document(
        conn,
        document_id=document_id,
        filename="spec.xlsx",
        content_type=None,
        extension=".xlsx",
        size_bytes=1,
        sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        stored_path="/tmp/spec.xlsx",
    )
    document_id = stored[0]

    try:
        by_text = _fill_corpus(conn, document_id)
    except Exception:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = %s", (document_id,))
        raise

    yield document_id, by_text

    with conn.cursor() as cur:
        cur.execute("DELETE FROM documents WHERE id = %s", (document_id,))


def _fill_corpus(conn, document_id: str) -> dict[str, int]:
    blocks = [
        Block(text="Мощность блендера 800 Вт", page=1, section="Характеристики"),
        Block(text="Артикул KTL-1700, чайник электрический", page=1, section="Спецификация"),
        Block(text="KTL-1700: мощность 2200 Вт", page=2, section="Спецификация"),
    ]
    chunks_repo.replace_chunks(conn, document_id, chunk_blocks(blocks, document="spec.xlsx"))

    pending = chunks_repo.chunks_without_embedding(conn, limit=10, document_id=document_id)
    by_text = {row["text"]: row["id"] for row in pending}
    vectors = {
        "Мощность блендера 800 Вт": _vector(0.8, 0.6),
        "Артикул KTL-1700, чайник электрический": _vector(0.0, 1.0),
        "KTL-1700: мощность 2200 Вт": _vector(0.9, 0.1),
    }
    chunks_repo.set_embeddings(
        conn, [(vectors[text], chunk_id) for text, chunk_id in by_text.items()]
    )
    return by_text


def test_vector_search_respects_threshold(conn, corpus):
    document_id, by_text = corpus
    embedding = _vector(1.0, 0.0)

    strict = chunks_repo.search_vector(
        conn, embedding, limit=5, min_similarity=0.9, document_id=document_id
    )
    assert [row["text"] for row in strict] == ["KTL-1700: мощность 2200 Вт"]
    assert strict[0]["score"] == pytest.approx(0.994, abs=1e-3)

    loose = chunks_repo.search_vector(
        conn, embedding, limit=5, min_similarity=0.5, document_id=document_id
    )
    assert {row["text"] for row in loose} == {
        "KTL-1700: мощность 2200 Вт",
        "Мощность блендера 800 Вт",
    }
    assert "Артикул KTL-1700, чайник электрический" not in {row["text"] for row in loose}


def test_text_search_finds_article(conn, corpus):
    document_id, _ = corpus

    results = chunks_repo.search_text(
        conn, "KTL-1700", limit=5, document_id=document_id
    )

    assert {row["text"] for row in results} == {
        "Артикул KTL-1700, чайник электрический",
        "KTL-1700: мощность 2200 Вт",
    }


def test_hybrid_returns_union_and_ranks_both_lists_first(conn, corpus):
    document_id, by_text = corpus

    results = chunks_repo.search_hybrid(
        conn,
        _vector(1.0, 0.0),
        "KTL-1700",
        limit=5,
        min_similarity=0.5,
        document_id=document_id,
    )

    texts = [row["text"] for row in results]
    assert set(texts) == {
        "Мощность блендера 800 Вт",
        "Артикул KTL-1700, чайник электрический",
        "KTL-1700: мощность 2200 Вт",
    }
    # Найденный обоими списками — выше найденных одним.
    assert texts[0] == "KTL-1700: мощность 2200 Вт"
    assert results[0]["id"] == by_text["KTL-1700: мощность 2200 Вт"]
    assert all(row["filename"] == "spec.xlsx" for row in results)


def test_filters_narrow_both_lists(conn, corpus):
    document_id, _ = corpus

    by_section = chunks_repo.search_hybrid(
        conn,
        _vector(1.0, 0.0),
        "KTL-1700",
        limit=5,
        min_similarity=0.5,
        document_id=document_id,
        section="Спецификация",
    )
    assert {row["section"] for row in by_section} == {"Спецификация"}

    by_article = chunks_repo.search_text(
        conn, "KTL-1700", limit=5, document_id=document_id, article="KTL-1700"
    )
    assert all(row["article"] == "KTL-1700" for row in by_article)


def test_reindex_is_idempotent(conn, corpus, monkeypatch):
    document_id, _ = corpus
    calls: list[list[str]] = []

    def fake_embed(texts):
        calls.append(texts)
        return [_vector(1.0, 0.0) for _ in texts]

    monkeypatch.setattr(reindex, "embed_documents", fake_embed)

    # В corpus векторы уже стоят — сначала обнулим, как после сбоя.
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE chunks SET embedding = NULL WHERE document_id = %s",
            (document_id,),
        )

    assert reindex.index_pending(document_id=document_id) == 3
    assert len(calls) == 1
    assert reindex.index_pending(document_id=document_id) == 0
    assert len(calls) == 1


def test_search_filters_dataclass():
    assert SearchFilters(document_id="x", section=None).as_kwargs() == {
        "document_id": "x"
    }
