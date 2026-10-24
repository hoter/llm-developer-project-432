"""Сквозной RAG-сценарий с подменённой моделью и живой тестовой базой."""
import asyncio
import json
import os
import uuid

import psycopg
import pytest

from app.core.config import settings
from app.schemas import CritiqueReport
from app.services import rag_pipeline

pytestmark = pytest.mark.skipif(
    os.environ.get("PCA_SKIP_DB_TESTS") == "1", reason="PCA_SKIP_DB_TESTS=1"
)

CHUNK_ID = "ragc1"
CONTEXT = f"[{CHUNK_ID} | test.pdf | стр. 1 | Секция]\nМощность 800 Вт, гарантия 24 месяца."


def _card(chunk_id=CHUNK_ID, confidence=0.9) -> dict:
    return {
        "title": "Блендер 800 Вт",
        "description": "Погружной блендер.",
        "characteristics": {"Мощность": "800 Вт"},
        "benefits": ["Металлическая ножка"],
        "seo": {"title": "Блендер", "description": "Мощный", "keywords": []},
        "sources": [{"chunk_id": chunk_id, "page": 1}],
        "missing_fields": [],
        "confidence": confidence,
    }


@pytest.fixture
def corpus():
    try:
        conn = psycopg.connect(settings.database_url, autocommit=True)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL недоступен: {exc}")

    doc_id = "rag" + uuid.uuid4().hex[:8]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO documents (id, filename, content_hash, kind, status) "
            "VALUES (%s, 'test.pdf', %s, 'pdf', 'indexed')",
            (doc_id, uuid.uuid4().hex),
        )
        cur.execute(
            "INSERT INTO chunks (id, doc_id, ordinal, text, metadata) "
            "VALUES (%s, %s, 0, %s, %s)",
            (CHUNK_ID, doc_id, "Мощность 800 Вт", '{"page": 1, "section": "Секция"}'),
        )
    yield conn, doc_id
    with conn.cursor() as cur:
        cur.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
    conn.close()


def _patch(monkeypatch, card: dict, verdict="approve"):
    async def fake_run(agent, prompt):
        if agent.name == "Critic":
            return CritiqueReport(verdict=verdict).model_dump_json()
        return json.dumps(card, ensure_ascii=False)

    async def fake_retrieve(query, doc_ids=None):
        from app.guardrails import GuardReport

        return CONTEXT, GuardReport()

    monkeypatch.setattr(rag_pipeline, "run_agent", fake_run)
    monkeypatch.setattr(rag_pipeline, "retrieve_context_async", fake_retrieve)


def test_happy_path(monkeypatch, corpus):
    _patch(monkeypatch, _card())
    _conn, doc_id = corpus

    draft, attempts, verdict, status, _guard = asyncio.run(
        rag_pipeline.run_rag_pipeline("блендер", [doc_id])
    )

    assert (attempts, verdict, status) == (1, "approved", "done")
    assert draft.sources[0].chunk_id == CHUNK_ID


def test_hallucinated_source_raises(monkeypatch, corpus):
    _patch(monkeypatch, _card(chunk_id="deadbeef"))
    _conn, doc_id = corpus

    with pytest.raises(rag_pipeline.SourceValidationError):
        asyncio.run(rag_pipeline.run_rag_pipeline("блендер", [doc_id]))


def test_low_confidence_needs_review(monkeypatch, corpus):
    _patch(monkeypatch, _card(confidence=0.2))
    _conn, doc_id = corpus

    _draft, _a, _v, status, _g = asyncio.run(
        rag_pipeline.run_rag_pipeline("блендер", [doc_id])
    )
    assert status == "needs_review"
