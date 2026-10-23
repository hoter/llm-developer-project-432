-- 0002: таблица задач. До появления миграций эта схема создавалась на
-- старте приложения (бывший schema.sql) — теперь только миграциями.

CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    idempotency_key TEXT UNIQUE,
    status          TEXT NOT NULL DEFAULT 'pending',
    payload         JSONB NOT NULL,
    result          JSONB,
    attempts        INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
