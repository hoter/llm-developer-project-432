"""Проверки живости и готовности.

/live (он же /health) внешние ресурсы не трогает: пока процесс отвечает на
запросы, он живой — даже если база остановлена. /ready проверяет зависимости:
соединение из пула и активное расширение vector.

Обработчики синхронные (def): psycopg блокирующий, FastAPI уведёт его в
threadpool и не заблокирует event loop.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core import db

router = APIRouter(tags=["health"])


@router.get("/health")
@router.get("/live")
def live() -> dict:
    """Живость: отвечает независимо от состояния базы."""
    return {"status": "ok"}


@router.get("/ready")
def ready():
    """Готовность: база доступна и расширение vector активно."""
    try:
        with db.connection() as conn:
            row = conn.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            ).fetchone()
    except Exception as exc:  # пул недоступен, база не отвечает
        return JSONResponse(
            {"status": "error", "database": "unavailable", "detail": str(exc)},
            status_code=503,
        )

    if row is None:
        return JSONResponse(
            {"status": "error", "database": "ok", "vector": "missing"},
            status_code=503,
        )

    return {"status": "ok", "database": "ok", "vector": row[0]}
