-- 0001: векторное расширение и журнал применённых миграций.
--
-- CREATE EXTENSION не устанавливает pgvector, а лишь активирует уже собранное
-- в образе расширение. Поэтому база поднимается на образе pgvector/pgvector,
-- а не на обычном postgres: на нём этот запрос падает.

CREATE EXTENSION IF NOT EXISTS vector;

-- Журнал раннера (app/core/migrate.py): какие версии уже применены.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
