"""Асинхронный вариант: задача в базе + процесс в Temporal.

POST /jobs создаёт задачу, запускает процесс и отвечает 202 идентификатором.
Статус читается из базы (POST /jobs/{id}) — это состояние предметной области.
История движка (попытки шагов, ретраи) живёт в Temporal и видна в его UI.
"""
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError

from app.core import db
from app.core.config import settings
from app.repositories import jobs as jobs_repo
from app.schemas import JobIn, JobOut
from app.temporal.client import get_client
from app.temporal.workflows import MAX_ATTEMPTS

router = APIRouter(tags=["jobs"])


async def _start_workflow(job_id: str, supplier_text: str) -> None:
    """Запустить процесс с id = id задачи.

    Повторный запрос с тем же ключом идемпотентности не создаёт вторую
    задачу, а start_workflow на уже запущенный id просто игнорируется.
    """
    client = await get_client()
    try:
        await client.start_workflow(
            "CardWorkflow",
            args=[job_id, supplier_text, MAX_ATTEMPTS],
            id=job_id,
            task_queue=settings.temporal_task_queue,
            # Тот же ключ идемпотентности не должен запускать второй прогон
            # уже завершённой задачи: иначе двойной клик = двойной счёт.
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    except WorkflowAlreadyStartedError:
        pass


@router.post("/jobs", status_code=202)
async def create_job(
    body: JobIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    with db.connection() as conn:
        job_id = jobs_repo.create_job(
            conn, {"supplier_text": body.supplier_text}, idempotency_key
        )
        job = jobs_repo.get_job(conn, job_id) or {"status": "pending"}

    await _start_workflow(job_id, body.supplier_text)
    return JSONResponse({"id": job_id, "status": job["status"]}, status_code=202)


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: str):
    with db.connection() as conn:
        job = jobs_repo.get_job(conn, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


async def _signal(job_id: str, name: str) -> dict:
    with db.connection() as conn:
        job = jobs_repo.get_job(conn, job_id)
    if not job:
        raise HTTPException(404, "job not found")

    client = await get_client()
    handle = client.get_workflow_handle(job_id)
    try:
        await handle.signal(name)
    except RPCError as exc:
        raise HTTPException(404, f"workflow not found: {exc.message}")
    return {"id": job_id, "signaled": name}


@router.post("/jobs/{job_id}/approve")
async def approve(job_id: str):
    """Сигнал подтверждения: процесс выходит из ожидания и фиксирует approved."""
    return await _signal(job_id, "approve")


@router.post("/jobs/{job_id}/request-changes")
async def request_changes(job_id: str):
    """Сигнал отказа: карточка уходит в rejected, черновик сохраняется."""
    return await _signal(job_id, "request_changes")
