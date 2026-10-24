"""Фрагменты документов: SQL по таблице chunks.

Здесь живут все три режима поиска: по векторам, по словам и гибридный.
Гибрид — Reciprocal Rank Fusion: фрагмент получает вклад 1/(k+rank) от
каждого списка, где встретился, поэтому найденный обоими оказывается выше.
"""
import json

import psycopg

from app.parsers.chunker import Chunk

RRF_K = 60

_CHUNK_COLUMNS = """
    c.id, c.document_id, d.filename, c.chunk_index, c.text, c.page,
    c.section, c.article, c.brand, c.metadata
"""


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


def chunks_without_embedding(
    conn: psycopg.Connection, *, limit: int = 32, document_id: str | None = None
) -> list[dict]:
    query = "SELECT id, text FROM chunks WHERE embedding IS NULL"
    args: list = []
    if document_id:
        query += " AND document_id = %s"
        args.append(document_id)
    query += " ORDER BY id LIMIT %s"
    args.append(limit)
    with conn.cursor() as cur:
        cur.execute(query, args)
        rows = cur.fetchall()
    return [{"id": row[0], "text": row[1]} for row in rows]


def set_embeddings(
    conn: psycopg.Connection, items: list[tuple[list[float], int]]
) -> int:
    """Записать векторы пачкой: [(vector, chunk_id), ...]."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE chunks SET embedding = %s::vector WHERE id = %s",
                [(_vector_literal(vector), chunk_id) for vector, chunk_id in items],
            )
    return len(items)


def search_vector(
    conn: psycopg.Connection,
    embedding: list[float],
    *,
    limit: int = 5,
    min_similarity: float = 0.0,
    **filters,
) -> list[dict]:
    """Ближайшие к вектору запроса; порог отсекает мусор."""
    where, filter_args = _filter_clause(filters)
    vector = _vector_literal(embedding)
    query = f"""
        SELECT {_CHUNK_COLUMNS}, 1 - (c.embedding <=> %s::vector) AS score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.embedding IS NOT NULL
          AND 1 - (c.embedding <=> %s::vector) >= %s
          {where}
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s
    """
    args = [vector, vector, min_similarity, *filter_args, vector, limit]
    return _fetch(conn, query, args)


def search_text(
    conn: psycopg.Connection, query_text: str, *, limit: int = 5, **filters
) -> list[dict]:
    """Обычное ранжирование полнотекстового поиска (russian)."""
    where, filter_args = _filter_clause(filters)
    query = f"""
        SELECT {_CHUNK_COLUMNS},
               ts_rank_cd(c.tsv, plainto_tsquery('russian', %s)) AS score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.tsv @@ plainto_tsquery('russian', %s)
          {where}
        ORDER BY score DESC, c.id
        LIMIT %s
    """
    args = [query_text, query_text, *filter_args, limit]
    return _fetch(conn, query, args)


def search_hybrid(
    conn: psycopg.Connection,
    embedding: list[float],
    query_text: str,
    *,
    limit: int = 5,
    min_similarity: float = 0.0,
    candidate_limit: int | None = None,
    **filters,
) -> list[dict]:
    """Векторы + слова, слияние по обратным позициям (RRF)."""
    candidates = candidate_limit or max(limit * 4, 20)
    where, filter_args = _filter_clause(filters)
    vector = _vector_literal(embedding)

    query = f"""
        WITH vector_candidates AS (
            SELECT c.id,
                   row_number() OVER (ORDER BY c.embedding <=> %s::vector) AS rank
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
        JOIN documents d ON d.id = c.document_id
        ORDER BY f.score DESC, c.id
        LIMIT %s
    """
    args = [
        vector,
        vector,
        min_similarity,
        *filter_args,
        vector,
        candidates,
        query_text,
        query_text,
        *filter_args,
        query_text,
        candidates,
        limit,
    ]
    return _fetch(conn, query, args)


def _filter_clause(filters: dict) -> tuple[str, list]:
    clauses = []
    args: list = []
    for column in ("document_id", "section", "article", "brand"):
        value = filters.get(column)
        if value:
            clauses.append(f"c.{column} = %s")
            args.append(value)
    if not clauses:
        return "", args
    return "AND " + " AND ".join(clauses), args


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.7f}" for value in vector) + "]"


def _fetch(conn: psycopg.Connection, query: str, args: list) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(query, args)
        rows = cur.fetchall()
        columns = [column.name for column in cur.description]
    return [dict(zip(columns, row)) for row in rows]
