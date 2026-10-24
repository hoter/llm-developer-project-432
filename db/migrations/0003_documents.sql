-- 0003: документы поставщиков и их фрагменты.
--
-- Документ проходит состояния new → parsing → indexed | failed.
-- sha256 уникален: повторная загрузка того же файла не создаёт дубль.
-- Векторная колонка появится на шаге эмбеддингов — здесь только текст и
-- метаданные, по которым фильтруется поиск и строится ссылка на источник.

CREATE TABLE IF NOT EXISTS documents (
    id           TEXT PRIMARY KEY,
    filename     TEXT NOT NULL,
    content_type TEXT,
    extension    TEXT NOT NULL,
    size_bytes   BIGINT NOT NULL,
    sha256       TEXT NOT NULL UNIQUE,
    stored_path  TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'new',
    error        TEXT,
    chunks_count INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS documents_status_idx ON documents (status);

CREATE TABLE IF NOT EXISTS chunks (
    id          BIGSERIAL PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    text        TEXT NOT NULL,
    page        INTEGER,
    section     TEXT NOT NULL,
    article     TEXT,
    brand       TEXT,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS chunks_document_id_idx ON chunks (document_id);
