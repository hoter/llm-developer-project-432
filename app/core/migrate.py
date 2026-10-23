"""SQL-раннер миграций.

Миграции — обычные SQL-файлы в db/migrations/, применяются по порядку имён
(0001_, 0002_, ...). Применённые версии запоминаются в таблице
schema_migrations; её создаёт первая миграция.

Каждая миграция применяется в отдельной транзакции: SQL и запись о версии
фиксируются вместе, поэтому сбой на середине откатывается целиком, а
повторный запуск продолжит с той же миграции. Повторный запуск на уже
применённой схеме ничего не делает.

Запуск: python -m app.core.migrate (или make migrate).
"""
from pathlib import Path

import psycopg

from app.core.config import settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"


def migration_files() -> list[Path]:
    """Файлы миграций в порядке применения."""
    if not MIGRATIONS_DIR.is_dir():
        return []
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def applied_versions(conn: psycopg.Connection) -> list[str]:
    """Версии, уже записанные в schema_migrations (пусто, если таблицы нет)."""
    row = conn.execute(
        "SELECT to_regclass('public.schema_migrations') IS NOT NULL"
    ).fetchone()
    if not row or not row[0]:
        return []
    rows = conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall()
    return [r[0] for r in rows]


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Применить неприменённые миграции. Возвращает список применённых версий."""
    applied = set(applied_versions(conn))
    applied_now: list[str] = []
    for path in migration_files():
        version = path.stem
        if version in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        with conn.transaction():
            conn.execute(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s)", (version,)
            )
        applied_now.append(version)
    return applied_now


def main() -> None:
    # Раннер — ресурс уровня операции: отдельное соединение на запуск,
    # без пула. autocommit=True, а границы транзакций задаём явно через
    # conn.transaction() — тогда каждая миграция фиксируется отдельно.
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        versions = apply_migrations(conn)

    if versions:
        for version in versions:
            print(f"применена миграция {version}")
    else:
        print("новых миграций нет")


if __name__ == "__main__":
    main()
