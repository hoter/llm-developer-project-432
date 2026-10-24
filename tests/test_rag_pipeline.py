"""Сквозной сценарий с подменённым клиентом модели и живой тестовой базой.

Фрагменты в базе → поиск → контекст → генерация → проверка ссылок → критика.
Модель эмбеддингов не загружается: вектор запроса подменён.
"""
import asyncio
import json
import uuid

import psycopg
import pytest

from app.core.config import settings
from app.core.migrate import apply_migrations
from app.parsers import Block
from app.parsers.chunker import chunk_blocks
from app.rag import retrieval
from app.repositories import chunks as chunks_repo
from app.repositories import documents as documents_repo
from app.services import rag_pipeline, structured

SPEC_TEXT = "KTL-1700: Мощность 2200 Вт; Объём 1,7 л"


def _vector(x: float, y: float) -> list[float]:
    vector = [0.0] * settings.embedding_dimension
    vector[0] = x
    vector[1] = y
    return vector


def _card(chunk_id: str = "S1", title: str = "Чайник KTL-1700") -> dict:
    return {
        "title": title,
        "description": "Электрический чайник с закрытой спиралью.",
        "characteristics": {"Мощность": "2200 Вт", "Объём": "1,7 л"},
        "benefits": ["Быстро кипит"],
        "missing_fields": ["Гарантия"],
        "confidence": 0.8,
        "seo": {
            "title": "Чайник KTL-1700",
            "description": "Чайник 2200 Вт",
            "keywords": ["чайник"],
        },
        "sources": [
            {"field": "characteristics.Мощность", "chunk_id": chunk_id},
            {"field": "characteristics.Объём", "chunk_id": chunk_id},
        ],
    }


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
def corpus(conn, monkeypatch):
    """Документ с двумя фрагментами и заранее заданными векторами."""
    document_id = uuid.uuid4().hex[:12]
    documents_repo.create_document(
        conn,
        document_id=document_id,
        filename="kettle_spec.xlsx",
        content_type=None,
        extension=".xlsx",
        size_bytes=1,
        sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        stored_path="/tmp/kettle_spec.xlsx",
    )

    try:
        blocks = [
            Block(
                text=SPEC_TEXT,
                page=1,
                section="Спецификация",
                article="KTL-1700",
            ),
            Block(text="Гарантия 12 месяцев", page=2, section="Гарантия"),
        ]
        chunks_repo.replace_chunks(
            conn, document_id, chunk_blocks(blocks, document="kettle_spec.xlsx")
        )
        pending = chunks_repo.chunks_without_embedding(
            conn, limit=10, document_id=document_id
        )
        vectors = {SPEC_TEXT: _vector(1.0, 0.0), "Гарантия 12 месяцев": _vector(0.0, 1.0)}
        chunks_repo.set_embeddings(
            conn, [(vectors[row["text"]], row["id"]) for row in pending]
        )
        ids = {row["text"]: row["id"] for row in pending}
    except Exception:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = %s", (document_id,))
        raise

    # Модель эмбеддингов в тестах не грузим: вектор запроса задан вручную.
    monkeypatch.setattr(retrieval, "embed_query", lambda query: _vector(1.0, 0.0))

    yield {"document_id": document_id, "ids": ids}

    with conn.cursor() as cur:
        cur.execute("DELETE FROM documents WHERE id = %s", (document_id,))


@pytest.fixture
def fake_llm(monkeypatch):
    prompts: list[str] = []
    scenario: list = []

    async def fake_run(agent, prompt, **kwargs):
        prompts.append(prompt)
        item = scenario.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(structured, "run_agent", fake_run)
    return prompts, scenario


def test_end_to_end_generates_card_with_verified_sources(conn, corpus, fake_llm):
    prompts, scenario = fake_llm
    scenario += [
        json.dumps(_card(), ensure_ascii=False),
        json.dumps({"verdict": "approve", "issues": []}),
    ]

    result = asyncio.run(
        rag_pipeline.run_pipeline([corpus["document_id"]], hint="KTL-1700")
    )

    assert result.verdict == "approved"
    assert result.attempts == 1
    assert len(result.draft.sources) == 2
    assert all(
        citation.chunk_id == str(corpus["ids"][SPEC_TEXT])
        for citation in result.draft.sources
    )
    assert "[S1]" in prompts[0]
    assert "KTL-1700" in prompts[0]


def test_fabricated_citation_goes_to_regeneration(conn, corpus, fake_llm):
    prompts, scenario = fake_llm
    scenario += [
        json.dumps(_card(chunk_id="S99"), ensure_ascii=False),
        json.dumps(_card(), ensure_ascii=False),
        json.dumps({"verdict": "approve", "issues": []}),
    ]

    result = asyncio.run(
        rag_pipeline.run_pipeline([corpus["document_id"]], hint="KTL-1700")
    )

    assert result.verdict == "approved"
    assert result.attempts == 2
    assert "S99" in prompts[1]
    assert "нет в базе" in prompts[1] or "не был в контексте" in prompts[1]


def test_citation_to_chunk_outside_context_is_rejected(conn, corpus, fake_llm):
    prompts, scenario = fake_llm
    outside = corpus["ids"]["Гарантия 12 месяцев"]
    scenario += [json.dumps(_card(chunk_id=str(outside)), ensure_ascii=False)]

    result = asyncio.run(
        rag_pipeline.run_pipeline(
            [corpus["document_id"]], hint="KTL-1700", max_attempts=1
        )
    )

    assert result.verdict == "rejected"
    # Критик не вызывался: карточка отсечена проверкой ссылок.
    assert len(prompts) == 1


def test_never_valid_citation_stops_at_max_attempts(conn, corpus, fake_llm):
    prompts, scenario = fake_llm
    scenario += [
        json.dumps(_card(chunk_id="S99"), ensure_ascii=False),
        json.dumps(_card(chunk_id="S98"), ensure_ascii=False),
    ]

    result = asyncio.run(
        rag_pipeline.run_pipeline(
            [corpus["document_id"]], hint="KTL-1700", max_attempts=2
        )
    )

    assert result.verdict == "rejected"
    assert result.attempts == 2
    assert len(prompts) == 2


def test_low_confidence_needs_review(conn, corpus, fake_llm):
    _, scenario = fake_llm
    card = _card()
    card["confidence"] = 0.3
    card["missing_fields"] = ["Гарантия", "Цвет"]
    scenario += [
        json.dumps(card, ensure_ascii=False),
        json.dumps({"verdict": "approve", "issues": []}),
    ]

    result = asyncio.run(
        rag_pipeline.run_pipeline([corpus["document_id"]], hint="KTL-1700")
    )

    assert result.verdict == "needs_review"
    assert result.draft.missing_fields == ["Гарантия", "Цвет"]
    assert result.draft.confidence < settings.confidence_threshold
