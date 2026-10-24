-- 0005: журнал вызовов модели.
--
-- Пишет его клиент модели, а не вызывающий код: тогда учёт нельзя забыть
-- в новом месте — все вызовы идут через одну границу. Стоимость хранится
-- целым числом микроединиц (1e-6), а не float: деньги не любят округлений.

CREATE TABLE IF NOT EXISTS llm_calls (
    id            BIGSERIAL PRIMARY KEY,
    job_id        TEXT,
    request_id    TEXT,
    model         TEXT NOT NULL,
    role          TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_micros   BIGINT NOT NULL,
    duration_ms   INTEGER NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS llm_calls_job_idx ON llm_calls (job_id);
CREATE INDEX IF NOT EXISTS llm_calls_request_idx ON llm_calls (request_id);
CREATE INDEX IF NOT EXISTS llm_calls_model_idx ON llm_calls (model);
