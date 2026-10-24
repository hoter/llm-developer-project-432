"""Сервис документа: индексация и отказ скану."""
import os
import shutil
import uuid
from pathlib import Path

import psycopg
import pytest

from app.core.config import settings
from app.repositories import chunks as chunks_repo
from app.repositories import documents as documents_repo
from app.services.documents import ingest_document

pytestmark = pytest.mark.skipif(
    os.environ.get("PCA_SKIP_DB_TESTS") == "1", reason="PCA_SKIP_DB_TESTS=1"
)

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture
def conn(monkeypatch):
    try:
        connection = psycopg.connect(settings.database_url, autocommit=True)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL недоступен: {exc}")
    monkeypatch.setattr("app.services.documents.index_document", lambda document_id: 0)
    created: list[str] = []
    yield connection, created
    if created:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = ANY(%s)", (created,))
    connection.close()


def _document(conn, created: list[str], tmp_path: Path, filename: str) -> tuple[str, Path]:
    target = tmp_path / filename
    shutil.copyfile(DATA / filename, target)
    doc_id = uuid.uuid4().hex[:12]
    documents_repo.create_document(
        conn,
        document_id=doc_id,
        filename=filename,
        content_hash=uuid.uuid4().hex,
        kind=filename.rsplit(".", 1)[-1],
        size_bytes=target.stat().st_size,
        stored_path=str(target),
    )
    created.append(doc_id)
    return doc_id, target


def test_xlsx_indexed_with_articul(conn, tmp_path):
    connection, created = conn
    doc_id, _ = _document(connection, created, tmp_path, "kettle_spec.xlsx")

    assert ingest_document(doc_id) == "indexed"

    stored = documents_repo.get_document(connection, doc_id)
    assert stored["status"] == "indexed"
    assert stored["chunks_count"] == 3
    chunks = chunks_repo.list_chunks(connection, doc_id)
    assert [chunk["metadata"].get("articul") for chunk in chunks] == [
        "KTL-1700",
        "KTL-1000",
        "KTL-THRM",
    ]


def test_scanned_pdf_failed_with_reason(conn, tmp_path):
    connection, created = conn
    doc_id, _ = _document(connection, created, tmp_path, "boiler_scan.pdf")

    assert ingest_document(doc_id) == "failed"

    stored = documents_repo.get_document(connection, doc_id)
    assert "текстового слоя" in stored["error"]
    assert chunks_repo.count_chunks(connection, doc_id) == 0
