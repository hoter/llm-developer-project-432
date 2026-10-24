"""Поиск на фиксированных векторах: модель эмбеддингов не грузим."""
import math
import os
import uuid

import psycopg
import pytest

from app.core.config import settings

pytestmark = pytest.mark.skipif(
    os.environ.get("PCA_SKIP_DB_TESTS") == "1", reason="PCA_SKIP_DB_TESTS=1"
)


def _unit(x: float, y: float) -> list[float]:
    vector = [x, y]
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] + [0.0] * (settings.embed_dim - 2)


E_BLENDER = _unit(1, 0)
E_KETTLE = _unit(0, 1)


def _literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in vector) + "]"


@pytest.fixture
def conn(monkeypatch):
    try:
        connection = psycopg.connect(settings.database_url, autocommit=True)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL недоступен: {exc}")

    doc_id = "test" + uuid.uuid4().hex[:8]
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO documents (id, filename, content_hash, kind, status) "
            "VALUES (%s, 'test.pdf', %s, 'pdf', 'indexed')",
            (doc_id, uuid.uuid4().hex),
        )
        rows = [
            ("c1", 0, "Мощность блендера 800 Вт", E_BLENDER),
            ("c2", 1, "Чайник 2200 Вт", E_KETTLE),
            ("c3", 2, "Гарантия 24 месяца", _unit(1, 1)),
        ]
        for cid, ordinal, text, vector in rows:
            cur.execute(
                "INSERT INTO chunks (id, doc_id, ordinal, text, metadata, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s::vector)",
                (cid, doc_id, ordinal, text, '{"page": 1}', _literal(vector)),
            )

    from app.repositories import chunks as chunks_repo

    monkeypatch.setattr(
        chunks_repo,
        "embed_query",
        lambda text: E_BLENDER if "блендер" in text.lower() else E_KETTLE,
    )

    yield connection

    with connection.cursor() as cur:
        cur.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
    connection.close()


def test_vector_search_and_threshold(conn):
    from app.repositories import chunks as chunks_repo

    found = chunks_repo.search_vector(conn, "мощность блендера", top_k=3)
    assert found[0]["chunk_id"] == "c1"
    assert found[0]["score"] >= 0.99

    strict = chunks_repo.search_vector(conn, "мощность блендера", top_k=5, threshold=1.0)
    assert [row["chunk_id"] for row in strict] == ["c1"]


def test_fts_finds_exact_word(conn):
    from app.repositories import chunks as chunks_repo

    results = chunks_repo.search_fts(conn, "гарантия", top_k=10)
    assert any(row["chunk_id"] == "c3" for row in results)


def test_doc_filter(conn):
    from app.repositories import chunks as chunks_repo

    assert chunks_repo.search_vector(
        conn, "блендер", top_k=3, doc_ids=["other"]
    ) == []
