from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_base_url: str = "http://localhost:1234/v1"
    llm_api_key: str = "lm-studio"
    llm_model: str = "gemma-4-e4b-it"
    # Служебные вызовы (критик, судья, классификация) — на дешёвой модели
    llm_aux_model: str = "gemma-4-e4b-it"

    # Цены в микроединицах за 1M токенов (1e-6 денежной единицы).
    # Локальная модель бесплатна — поставьте 0; здесь тариф для учёта.
    llm_price_input_micros_per_1m: int = 150_000
    llm_price_output_micros_per_1m: int = 600_000
    llm_aux_price_input_micros_per_1m: int = 50_000
    llm_aux_price_output_micros_per_1m: int = 200_000

    database_url: str = "postgresql://card:card@localhost:5432/card"

    # Пул соединений — ресурс уровня приложения (см. app/core/db.py)
    db_pool_min_size: int = 1
    db_pool_max_size: int = 10
    db_pool_timeout_s: float = 5.0

    temporal_host: str = "localhost:7233"
    temporal_task_queue: str = "card-queue"

    llm_timeout_s: float = 120.0
    llm_max_retries: int = 3

    # Сколько раз просить модель переделать невалидный ответ (разбор + лечение)
    llm_structured_attempts: int = 3
    # Ниже порога карточка не считается готовой: задача уходит человеку
    confidence_threshold: float = 0.6

    # Документы поставщиков
    uploads_dir: str = "data/uploads"
    max_upload_bytes: int = 10 * 1024 * 1024

    # Эмбеддинги и поиск
    embedding_model: str = "google/embeddinggemma-300m"
    embed_dim: int = 768
    embedding_batch_size: int = 32
    # Порог косинусной близости откалиброван на выданных документах
    # (см. docs/decisions.md, ADR-005)
    search_min_similarity: float = 0.826
    search_limit: int = 5
    # Сколько фрагментов брать в контекст и сколько символов он может занять
    rag_search_limit: int = 8
    rag_context_max_chars: int = 6000

    # Защита: больше этого числа подозрительных фрагментов — документ человеку
    suspicious_chunk_limit: int = 2


settings = Settings()
