-- 0004: векторная колонка и полнотекстовый поиск по фрагментам.
--
-- Метрика расстояния — косинус (vector_cosine_ops). Она выбирается один раз:
-- HNSW-индекс строится под неё, и менять метрику задним числом нельзя.
-- Полнотекстовая колонка генерируемая: tsv всегда соответствует text.

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedding vector(1024);

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('russian', text)) STORED;

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS chunks_tsv_gin_idx
    ON chunks USING gin (tsv);
