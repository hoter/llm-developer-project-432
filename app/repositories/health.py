"""Проверки зависимостей сервиса: расширение vector в базе."""
import psycopg


def vector_version(conn: psycopg.Connection) -> str | None:
    """Версия pgvector или None, если расширение не активировано."""
    with conn.cursor() as cur:
        cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        row = cur.fetchone()
    return row[0] if row else None
