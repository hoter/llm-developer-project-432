"""Работа с таблицей jobs — единственное место, где живёт SQL по задачам.

Статусная машина предметной области:
pending → retrieving → generating → verifying → critiquing → regenerating →
awaiting_approval | needs_review → approved | rejected | failed

Ветка без документов (текст): extracting → generating → critiquing → …

Это состояние видит клиент. Внутренняя история процесса (попытки шагов,
ретраи) живёт в Temporal и наружу не отдаётся.
"""
import json
import uuid
from datetime import UTC, datetime

import psycopg

from app.schemas import CardDraft


def _now() -> str:
    return datetime.now(UTC).isoformat()


def create_job(conn: psycopg.Connection, payload: dict, idempotency_key: str | None) -> str:
    """INSERT pending. При повторном idempotency_key возвращает существующий id.

    ON CONFLICT закрывает и гонку двух одновременных запросов с одним ключом:
    вторая вставка ничего не делает, и мы читаем уже созданную задачу.
    """
    job_id = uuid.uuid4().hex[:12]
    with conn.cursor() as cur:
        row = cur.execute(
            """
            INSERT INTO jobs (id, idempotency_key, payload)
            VALUES (%s, %s, %s)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
            """,
            (job_id, idempotency_key, json.dumps(payload)),
        ).fetchone()
        if row:
            return row[0]
        row = cur.execute(
            "SELECT id FROM jobs WHERE idempotency_key = %s", (idempotency_key,)
        ).fetchone()
        return row[0]


def set_status(
    conn: psycopg.Connection, job_id: str, status: str, *, result: CardDraft | None = None,
    error: str | None = None, bump_attempts: bool = False,
) -> None:
    sets = ["status = %s", "updated_at = %s"]
    args: list = [status, _now()]
    if result is not None:
        sets.append("result = %s")
        args.append(result.model_dump_json())
    if error is not None:
        sets.append("error = %s")
        args.append(error)
    if bump_attempts:
        sets.append("attempts = attempts + 1")
    args.append(job_id)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = %s", args)


def get_job(conn: psycopg.Connection, job_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, status, attempts, result, error, guard_report FROM jobs WHERE id = %s",
            (job_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    job = {
        "id": row[0],
        "status": row[1],
        "attempts": row[2],
        "result": None,
        "error": row[4],
        "guard_report": row[5],
    }
    if row[3]:
        # psycopg3 возвращает JSONB уже как dict, а не строку
        try:
            draft = (
                CardDraft.model_validate(row[3])
                if isinstance(row[3], dict)
                else CardDraft.model_validate_json(row[3])
            )
            job["result"] = draft.model_dump()
        except Exception:
            job["result"] = None
    return job


def set_guard_report(
    conn: psycopg.Connection, job_id: str, report: dict
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET guard_report = %s, updated_at = %s WHERE id = %s",
            (json.dumps(report, ensure_ascii=False), _now(), job_id),
        )
