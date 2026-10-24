"""Фрагменты документов: единственное место SQL по таблице chunks."""
import json

import psycopg

from app.parsers.chunker import Chunk


def replace_chunks(
    conn: psycopg.Connection, document_id: str, chunks: list[Chunk]
) -> int:
    """Заменить фрагменты документа целиком — повторный разбор не плодит дубли."""
    rows = [
        (
            document_id,
            index,
            chunk.text,
            chunk.page,
            chunk.section,
            chunk.article,
            chunk.brand,
            json.dumps(chunk.metadata, ensure_ascii=False),
        )
        for index, chunk in enumerate(chunks)
    ]
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
            if rows:
                cur.executemany(
                    """
                    INSERT INTO chunks
                        (document_id, chunk_index, text, page, section, article, brand, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    rows,
                )
    return len(rows)


def count_chunks(conn: psycopg.Connection, document_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM chunks WHERE document_id = %s", (document_id,)
        )
        return cur.fetchone()[0]


def list_chunks(conn: psycopg.Connection, document_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT chunk_index, text, page, section, article, brand, metadata
            FROM chunks WHERE document_id = %s ORDER BY chunk_index
            """,
            (document_id,),
        )
        rows = cur.fetchall()
        columns = [column.name for column in cur.description]
    return [dict(zip(columns, row)) for row in rows]
