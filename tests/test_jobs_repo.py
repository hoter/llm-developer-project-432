"""Репозиторий задач на живой базе: идемпотентность и статусная машина.

Модель этим тестам не нужна. Без доступного Postgres они пропускаются,
чтобы `pytest` оставался зелёным в окружении без инфраструктуры.
"""
import uuid

import psycopg
import pytest

from app.core.config import settings
from app.core.migrate import apply_migrations
from app.repositories import jobs as jobs_repo
from app.schemas import CardDraft


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
def created(conn):
    """Идентификаторы созданных задач — чистим после теста."""
    ids: list[str] = []
    yield ids
    if ids:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM jobs WHERE id = ANY(%s)", (ids,))


def test_create_and_get_pending(conn, created):
    job_id = jobs_repo.create_job(conn, {"supplier_text": "текст"}, None)
    created.append(job_id)

    job = jobs_repo.get_job(conn, job_id)
    assert job["id"] == job_id
    assert job["status"] == "pending"
    assert job["attempts"] == 0
    assert job["result"] is None


def test_idempotency_key_returns_same_job(conn, created):
    key = f"test-{uuid.uuid4().hex}"
    first = jobs_repo.create_job(conn, {"supplier_text": "первый"}, key)
    second = jobs_repo.create_job(conn, {"supplier_text": "второй"}, key)
    created.append(first)

    assert first == second
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM jobs WHERE idempotency_key = %s", (key,)
        )
        assert cur.fetchone()[0] == 1


def test_status_and_result_roundtrip(conn, created):
    job_id = jobs_repo.create_job(conn, {"supplier_text": "текст"}, None)
    created.append(job_id)

    jobs_repo.set_status(conn, job_id, "extracting")
    jobs_repo.set_status(conn, job_id, "generating", bump_attempts=True)
    draft = CardDraft(
        title="Блендер 800 Вт",
        description="Погружной блендер с металлической ножкой.",
        characteristics={"Мощность": "800 Вт"},
        benefits=["Металлическая ножка"],
    )
    jobs_repo.set_status(conn, job_id, "approved", result=draft)

    job = jobs_repo.get_job(conn, job_id)
    assert job["status"] == "approved"
    assert job["attempts"] == 1
    assert job["result"] is not None
    assert job["result"]["title"] == "Блендер 800 Вт"


def test_get_unknown_job_returns_none(conn):
    assert jobs_repo.get_job(conn, "no-such-job") is None
