"""Документы и фрагменты на живой базе: разбор выданных файлов до индекса.

Без Postgres тесты пропускаются, чтобы `pytest` оставался зелёным в
окружении без инфраструктуры. Модель здесь не нужна вовсе.
"""
import hashlib
import shutil
import uuid
from pathlib import Path

import psycopg
import pytest

from app.core.config import settings
from app.core.migrate import apply_migrations
from app.repositories import chunks as chunks_repo
from app.repositories import documents as documents_repo
from app.services.documents import ingest_document

DATA = Path(__file__).resolve().parent.parent / "data"


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
def document(conn, tmp_path):
    """Копия выданного файла + строка документа; после теста всё удаляем."""
    created: list[str] = []

    def make(filename: str) -> tuple[str, Path]:
        source = DATA / filename
        target = tmp_path / filename
        shutil.copyfile(source, target)
        data = target.read_bytes()
        digest = hashlib.sha256(
            data + uuid.uuid4().hex.encode()
        ).hexdigest()  # уникальный sha для теста
        document_id = uuid.uuid4().hex[:12]
        documents_repo.create_document(
            conn,
            document_id=document_id,
            filename=filename,
            content_type="application/octet-stream",
            extension=target.suffix,
            size_bytes=len(data),
            sha256=digest,
            stored_path=str(target),
        )
        created.append(document_id)
        return document_id, target

    yield make

    for document_id in created:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = %s", (document_id,))


def test_xlsx_is_indexed_with_metadata(conn, document):
    document_id, _ = document("kettle_spec.xlsx")

    assert ingest_document(document_id) == "indexed"

    stored = documents_repo.get_document(conn, document_id)
    assert stored["status"] == "indexed"
    assert stored["chunks_count"] == 3

    chunks = chunks_repo.list_chunks(conn, document_id)
    assert len(chunks) == 3
    assert all(chunk["page"] is not None for chunk in chunks)
    assert all(chunk["section"] == "Спецификация" for chunk in chunks)
    assert [chunk["article"] for chunk in chunks] == ["KTL-1700", "KTL-1000", "KTL-THRM"]
    assert all(f"{chunk['article']}: " in chunk["text"] for chunk in chunks)
    assert all("Колонки: Артикул" in chunk["text"] for chunk in chunks)


def test_scanned_pdf_is_marked_failed_with_reason(conn, document):
    document_id, _ = document("boiler_scan.pdf")

    assert ingest_document(document_id) == "failed"

    stored = documents_repo.get_document(conn, document_id)
    assert stored["status"] == "failed"
    assert "текстового слоя" in stored["error"]
    assert chunks_repo.count_chunks(conn, document_id) == 0


def test_reupload_same_file_does_not_create_duplicate(conn, tmp_path):
    source = DATA / "kettle_spec.xlsx"
    target = tmp_path / "kettle_spec.xlsx"
    shutil.copyfile(source, target)
    data = target.read_bytes()
    digest = hashlib.sha256(data + uuid.uuid4().hex.encode()).hexdigest()

    first_id = uuid.uuid4().hex[:12]
    second_id = uuid.uuid4().hex[:12]
    kwargs = dict(
        filename="kettle_spec.xlsx",
        content_type="application/octet-stream",
        extension=".xlsx",
        size_bytes=len(data),
        sha256=digest,
        stored_path=str(target),
    )
    try:
        created_id, created = documents_repo.create_document(
            conn, document_id=first_id, **kwargs
        )
        assert created is True
        assert created_id == first_id

        same_id, created_again = documents_repo.create_document(
            conn, document_id=second_id, **kwargs
        )
        assert created_again is False
        assert same_id == first_id
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = ANY(%s)", ([first_id, second_id],))


def test_reindex_does_not_duplicate_chunks(conn, document):
    document_id, _ = document("blender_passport.pdf")

    assert ingest_document(document_id) == "indexed"
    first_count = chunks_repo.count_chunks(conn, document_id)
    assert ingest_document(document_id) == "indexed"

    assert chunks_repo.count_chunks(conn, document_id) == first_count
