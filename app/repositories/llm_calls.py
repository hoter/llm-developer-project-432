"""Журнал вызовов модели: единственное место SQL по таблице llm_calls."""
import psycopg


def record_call(
    conn: psycopg.Connection,
    *,
    job_id: str | None,
    request_id: str | None,
    model: str,
    role: str,
    input_tokens: int,
    output_tokens: int,
    cost_micros: int,
    duration_ms: int,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO llm_calls
                (job_id, request_id, model, role, input_tokens, output_tokens,
                 cost_micros, duration_ms)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                job_id,
                request_id,
                model,
                role,
                input_tokens,
                output_tokens,
                cost_micros,
                duration_ms,
            ),
        )


def calls_for_job(conn: psycopg.Connection, job_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, request_id, model, role, input_tokens, output_tokens,
                   cost_micros, duration_ms, created_at
            FROM llm_calls WHERE job_id = %s ORDER BY id
            """,
            (job_id,),
        )
        rows = cur.fetchall()
        columns = [column.name for column in cur.description]
    return [dict(zip(columns, row)) for row in rows]


def total_for_job(conn: psycopg.Connection, job_id: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) AS calls,
                   coalesce(sum(input_tokens), 0)::bigint AS input_tokens,
                   coalesce(sum(output_tokens), 0)::bigint AS output_tokens,
                   coalesce(sum(cost_micros), 0)::bigint AS cost_micros,
                   coalesce(sum(duration_ms), 0)::bigint AS duration_ms
            FROM llm_calls WHERE job_id = %s
            """,
            (job_id,),
        )
        row = cur.fetchone()
        columns = [column.name for column in cur.description]
    return dict(zip(columns, row))


def summary_by_model(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT model, role, count(*) AS calls,
                   coalesce(sum(input_tokens), 0)::bigint AS input_tokens,
                   coalesce(sum(output_tokens), 0)::bigint AS output_tokens,
                   coalesce(sum(cost_micros), 0)::bigint AS cost_micros
            FROM llm_calls
            GROUP BY model, role
            ORDER BY model, role
            """
        )
        rows = cur.fetchall()
        columns = [column.name for column in cur.description]
    return [dict(zip(columns, row)) for row in rows]
