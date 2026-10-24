"""Документы поставщиков: единственное место SQL по таблице documents."""
from datetime import UTC, datetime

import psycopg


def _now() -> str:
    return datetime.now(UTC).isoformat()


def create_document(
    conn: psycopg.Connection,
    *,
    document_id: str,
    filename: str,
    content_hash: str,
    kind: str,
    size_bytes: int | None = None,
    content_type: str | None = None,
    stored_path: str | None = None,
) -> tuple[str, bool]:
    """Создать документ; повторный content_hash возвращает существующий id."""
    with conn.cursor() as cur:
        row = cur.execute(
            """
            INSERT INTO documents
                (id, filename, content_hash, kind, size_bytes, content_type, stored_path)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (content_hash) DO NOTHING
            RETURNING id
            """,
            (
                document_id,
                filename,
                content_hash,
                kind,
                size_bytes,
                content_type,
                stored_path,
            ),
        ).fetchone()
        if row:
            return row[0], True
        row = cur.execute(
            "SELECT id FROM documents WHERE content_hash = %s", (content_hash,)
        ).fetchone()
        return row[0], False


def get_document(conn: psycopg.Connection, document_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, filename, content_hash, kind, status, size_bytes,
                   content_type, stored_path, error, chunks_count
            FROM documents WHERE id = %s
            """,
            (document_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        columns = [column.name for column in cur.description]
    return dict(zip(columns, row))


def get_by_hash(conn: psycopg.Connection, content_hash: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM documents WHERE content_hash = %s", (content_hash,))
        row = cur.fetchone()
    return {"id": row[0]} if row else None


def set_status(
    conn: psycopg.Connection,
    document_id: str,
    status: str,
    *,
    error: str | None = None,
    chunks_count: int | None = None,
) -> None:
    sets = ["status = %s", "updated_at = %s"]
    args: list = [status, _now()]
    if error is not None:
        sets.append("error = %s")
        args.append(error)
    if chunks_count is not None:
        sets.append("chunks_count = %s")
        args.append(chunks_count)
    args.append(document_id)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE documents SET {', '.join(sets)} WHERE id = %s", args)


def get_documents(conn: psycopg.Connection, document_ids: list[str]) -> list[dict]:
    if not document_ids:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, filename, kind, status, chunks_count
            FROM documents WHERE id = ANY(%s) ORDER BY filename
            """,
            (document_ids,),
        )
        rows = cur.fetchall()
        columns = [column.name for column in cur.description]
    return [dict(zip(columns, row)) for row in rows]


def get_documents_meta(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, filename, status FROM documents ORDER BY filename")
        rows = cur.fetchall()
        columns = [column.name for column in cur.description]
    return [dict(zip(columns, row)) for row in rows]
