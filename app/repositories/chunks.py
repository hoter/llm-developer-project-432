"""Фрагменты документов: SQL по chunks и три режима поиска.

Гибрид — Reciprocal Rank Fusion: фрагмент получает вклад 1/(k+rank) от
каждого списка, где встретился, поэтому найденный обоими идёт выше.
"""
import json
import uuid

import psycopg

from app.core.config import settings
from app.rag.embedder import embed_query

RRF_K = 60

_CHUNK_COLUMNS = """
    c.id AS chunk_id, c.doc_id, c.text, c.metadata, d.filename
"""


def replace_chunks(
    conn: psycopg.Connection, doc_id: str, chunks: list[dict]
) -> int:
    """Заменить фрагменты документа целиком — повторный разбор не плодит дубли."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE doc_id = %s", (doc_id,))
            rows = [
                (
                    uuid.uuid4().hex,
                    doc_id,
                    index,
                    chunk["text"],
                    json.dumps(chunk.get("metadata", {}), ensure_ascii=False),
                )
                for index, chunk in enumerate(chunks)
            ]
            if rows:
                cur.executemany(
                    """
                    INSERT INTO chunks (id, doc_id, ordinal, text, metadata)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    rows,
                )
    return len(chunks)


def count_chunks(conn: psycopg.Connection, doc_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM chunks WHERE doc_id = %s", (doc_id,))
        return cur.fetchone()[0]


def list_chunks(conn: psycopg.Connection, doc_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id AS chunk_id, text, metadata
            FROM chunks WHERE doc_id = %s ORDER BY ordinal
            """,
            (doc_id,),
        )
        rows = cur.fetchall()
        columns = [column.name for column in cur.description]
    return [dict(zip(columns, row)) for row in rows]


def chunks_without_embedding(
    conn: psycopg.Connection, *, limit: int = 32, doc_id: str | None = None
) -> list[dict]:
    query = "SELECT id AS chunk_id, text FROM chunks WHERE embedding IS NULL"
    args: list = []
    if doc_id:
        query += " AND doc_id = %s"
        args.append(doc_id)
    query += " ORDER BY id LIMIT %s"
    args.append(limit)
    with conn.cursor() as cur:
        cur.execute(query, args)
        rows = cur.fetchall()
    return [{"chunk_id": row[0], "text": row[1]} for row in rows]


def set_embeddings(
    conn: psycopg.Connection, items: list[tuple[list[float], str]]
) -> int:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE chunks SET embedding = %s::vector WHERE id = %s",
                [(_vector_literal(vector), chunk_id) for vector, chunk_id in items],
            )
    return len(items)


def existing_chunk_ids(conn: psycopg.Connection, chunk_ids: list[str]) -> set[str]:
    if not chunk_ids:
        return set()
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM chunks WHERE id = ANY(%s)", (chunk_ids,))
        return {row[0] for row in cur.fetchall()}


def get_chunks_by_ids(
    conn: psycopg.Connection, chunk_ids: list[str]
) -> dict[str, dict]:
    if not chunk_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_CHUNK_COLUMNS}
            FROM chunks c JOIN documents d ON d.id = c.doc_id
            WHERE c.id = ANY(%s)
            """,
            (chunk_ids,),
        )
        rows = cur.fetchall()
        columns = [column.name for column in cur.description]
    return {str(row[0]): dict(zip(columns, row)) for row in rows}


def search_vector(
    conn: psycopg.Connection,
    query: str,
    *,
    top_k: int = 5,
    threshold: float | None = None,
    doc_ids: list[str] | None = None,
) -> list[dict]:
    min_similarity = settings.search_min_similarity if threshold is None else threshold
    vector = _vector_literal(embed_query(query))
    where, args = _doc_filter(doc_ids)
    sql = f"""
        SELECT {_CHUNK_COLUMNS}, 1 - (c.embedding <=> %s::vector) AS score
        FROM chunks c JOIN documents d ON d.id = c.doc_id
        WHERE c.embedding IS NOT NULL
          AND 1 - (c.embedding <=> %s::vector) >= %s
          {where}
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s
    """
    return _fetch(conn, sql, [vector, vector, min_similarity, *args, vector, top_k])


def search_fts(
    conn: psycopg.Connection,
    query: str,
    *,
    top_k: int = 5,
    doc_ids: list[str] | None = None,
) -> list[dict]:
    where, args = _doc_filter(doc_ids)
    sql = f"""
        SELECT {_CHUNK_COLUMNS},
               ts_rank_cd(c.tsv, plainto_tsquery('russian', %s)) AS score
        FROM chunks c JOIN documents d ON d.id = c.doc_id
        WHERE c.tsv @@ plainto_tsquery('russian', %s)
          {where}
        ORDER BY score DESC, c.id
        LIMIT %s
    """
    return _fetch(conn, sql, [query, query, *args, top_k])


def search_hybrid(
    conn: psycopg.Connection,
    query: str,
    *,
    top_k: int = 5,
    threshold: float | None = None,
    doc_ids: list[str] | None = None,
) -> list[dict]:
    min_similarity = settings.search_min_similarity if threshold is None else threshold
    candidates = max(top_k * 4, 20)
    vector = _vector_literal(embed_query(query))
    where, args = _doc_filter(doc_ids)

    sql = f"""
        WITH vector_candidates AS (
            SELECT c.id, row_number() OVER (ORDER BY c.embedding <=> %s::vector) AS rank
            FROM chunks c
            WHERE c.embedding IS NOT NULL
              AND 1 - (c.embedding <=> %s::vector) >= %s
              {where}
            ORDER BY c.embedding <=> %s::vector
            LIMIT %s
        ),
        word_candidates AS (
            SELECT c.id,
                   row_number() OVER (
                       ORDER BY ts_rank_cd(c.tsv, plainto_tsquery('russian', %s)) DESC
                   ) AS rank
            FROM chunks c
            WHERE c.tsv @@ plainto_tsquery('russian', %s)
              {where}
            ORDER BY ts_rank_cd(c.tsv, plainto_tsquery('russian', %s)) DESC
            LIMIT %s
        ),
        fused AS (
            SELECT id, sum(1.0 / ({RRF_K} + rank)) AS score
            FROM (
                SELECT id, rank FROM vector_candidates
                UNION ALL
                SELECT id, rank FROM word_candidates
            ) lists
            GROUP BY id
        )
        SELECT {_CHUNK_COLUMNS}, f.score
        FROM fused f
        JOIN chunks c ON c.id = f.id
        JOIN documents d ON d.id = c.doc_id
        ORDER BY f.score DESC, c.id
        LIMIT %s
    """
    params = [
        vector, vector, min_similarity, *args, vector, candidates,
        query, query, *args, query, candidates, top_k,
    ]
    return _fetch(conn, sql, params)


def _doc_filter(doc_ids: list[str] | None) -> tuple[str, list]:
    if not doc_ids:
        return "", []
    return "AND c.doc_id = ANY(%s)", [doc_ids]


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.7f}" for value in vector) + "]"


def _fetch(conn: psycopg.Connection, sql: str, args: list) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()
        columns = [column.name for column in cur.description]
    return [dict(zip(columns, row)) for row in rows]
