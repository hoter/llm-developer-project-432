from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core import db
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.routers import cards, documents, generate, health, jobs, workflows

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    # Ресурс уровня приложения: пул создаётся на старте и живёт до остановки.
    # Схему здесь больше не создаём — только миграции (make migrate).
    db.pool()
    log.info(
        "db_pool_opened",
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
    )
    try:
        yield
    finally:
        db.close_pool()
        log.info("db_pool_closed")


app = FastAPI(title="card-pipeline", lifespan=lifespan)
app.include_router(health.router)
app.include_router(cards.router)
app.include_router(jobs.router)
app.include_router(documents.router)
app.include_router(generate.router)
app.include_router(workflows.router)
