import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from structlog.contextvars import bind_contextvars, clear_contextvars

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


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Идентификатор запроса рождается здесь и живёт в контексте логов."""
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    clear_contextvars()
    bind_contextvars(request_id=request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        log.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
        )
        return response
    finally:
        clear_contextvars()
app.include_router(health.router)
app.include_router(cards.router)
app.include_router(jobs.router)
app.include_router(documents.router)
app.include_router(generate.router)
app.include_router(workflows.router)
