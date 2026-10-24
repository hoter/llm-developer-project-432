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
    content_type: str | None,
    extension: str,
    size_bytes: int,
    sha256: str,
    stored_path: str,
) -> tuple[str, bool]:
    """Создать документ. Возвращает (id, создан_ли).

    Уникальный sha256 делает повторную загрузку того же файла идемпотентной:
    вторая вставка ничего не делает, и мы возвращаем существующий id.
    """
    with conn.cursor() as cur:
        row = cur.execute(
            """
            INSERT INTO documents
                (id, filename, content_type, extension, size_bytes, sha256, stored_path)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (sha256) DO NOTHING
            RETURNING id
            """,
            (
                document_id,
                filename,
                content_type,
                extension,
                size_bytes,
                sha256,
                stored_path,
            ),
        ).fetchone()
        if row:
            return row[0], True
        row = cur.execute(
            "SELECT id FROM documents WHERE sha256 = %s", (sha256,)
        ).fetchone()
        return row[0], False


def get_document(conn: psycopg.Connection, document_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, filename, content_type, extension, size_bytes, sha256,
                   stored_path, status, error, chunks_count
            FROM documents WHERE id = %s
            """,
            (document_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        columns = [column.name for column in cur.description]
    return dict(zip(columns, row))


def get_by_sha(conn: psycopg.Connection, sha256: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM documents WHERE sha256 = %s", (sha256,))
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
    """Документы по списку id — для проверки выбора и подписи контекста."""
    if not document_ids:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, filename, status, chunks_count
            FROM documents WHERE id = ANY(%s) ORDER BY filename
            """,
            (document_ids,),
        )
        rows = cur.fetchall()
        columns = [column.name for column in cur.description]
    return [dict(zip(columns, row)) for row in rows]
