"""Ресурсы уровня приложения: пул соединений Postgres.

Пул живёт столько же, сколько процесс: создаётся на старте (lifespan FastAPI
или первый вызов pool() из воркера) и освобождается при остановке. Операция
берёт соединение через connection() и возвращает его на выходе из контекста.

Правило: соединение берут на операцию, а не на весь шаг процесса. Шаг
генерации ждёт модель минутами — держать коннект всё это время бессмысленно,
он занимает место в пуле. Статус в базу пишут отдельным коротким обращением.
"""
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool

from app.core.config import settings

_pool: ConnectionPool | None = None


def pool() -> ConnectionPool:
    """Пул соединений приложения (ленивый синглтон)."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=settings.db_pool_min_size,
            max_size=settings.db_pool_max_size,
            timeout=settings.db_pool_timeout_s,
            # autocommit как у прежнего connect(): репозитории пишут без
            # явных commit(), а миграции работают отдельным соединением.
            kwargs={"autocommit": True},
            open=False,
            name="card-pool",
        )
        # wait=False: приложение поднимается и при лежащей базе — живость
        # (/live) должна отвечать, а готовность (/ready) сообщит об ошибке.
        _pool.open(wait=False)
    return _pool


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    """Соединение на одну операцию: берём из пула и возвращаем обратно."""
    with pool().connection() as conn:
        yield conn


def close_pool() -> None:
    """Освободить пул при остановке процесса."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
