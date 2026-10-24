-- 0003: документы поставщиков и их фрагменты.
--
-- id фрагмента — строка: на неё ссылается модель в sources.
-- Метаданные (страница, секция, артикул) живут в JSONB.

CREATE TABLE IF NOT EXISTS documents (
    id           TEXT PRIMARY KEY,
    filename     TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    kind         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'new',
    size_bytes   BIGINT,
    content_type TEXT,
    stored_path  TEXT,
    error        TEXT,
    chunks_count INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id         TEXT PRIMARY KEY,
    doc_id     TEXT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    ordinal    INTEGER NOT NULL,
    text       TEXT NOT NULL,
    metadata   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (doc_id, ordinal)
);

CREATE INDEX IF NOT EXISTS chunks_doc_id_idx ON chunks (doc_id);
