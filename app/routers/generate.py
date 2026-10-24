"""Сквозная генерация: документы + подсказка → карточка со ссылками.

Ответ 202 и идентификатор: работа идёт в устойчивом процессе. Результат
читается отдельно и уже с раскрытыми источниками (документ, страница,
секция, артикул, текст фрагмента).
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError

from app.core import db
from app.core.config import settings
from app.core.logging import current_request_id
from app.repositories import chunks as chunks_repo
from app.repositories import documents as documents_repo
from app.repositories import jobs as jobs_repo
from app.schemas import GenerateIn
from app.temporal.client import get_client
from app.temporal.workflows import MAX_ATTEMPTS

router = APIRouter(tags=["generate"])


@router.post("/generate", status_code=202)
async def generate(body: GenerateIn):
    with db.connection() as conn:
        documents = documents_repo.get_documents(conn, body.document_ids)
        if not documents:
            raise HTTPException(404, "документы не найдены")
        if not any(doc["status"] == "indexed" for doc in documents):
            raise HTTPException(400, "среди выбранных документов нет проиндексированных")

        job_id = jobs_repo.create_job(
            conn,
            {"document_ids": body.document_ids, "hint": body.hint},
            None,
        )

    client = await get_client()
    try:
        await client.start_workflow(
            "RagCardWorkflow",
            args=[
                job_id,
                body.document_ids,
                body.hint,
                current_request_id(),
                MAX_ATTEMPTS,
                settings.confidence_threshold,
            ],
            id=job_id,
            task_queue=settings.temporal_task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    except WorkflowAlreadyStartedError:
        pass

    return JSONResponse({"id": job_id, "status": "pending"}, status_code=202)


@router.get("/generate/{job_id}")
async def get_result(job_id: str):
    with db.connection() as conn:
        job = jobs_repo.get_job(conn, job_id)
        if not job:
            raise HTTPException(404, "job not found")

        result = job.get("result")
        if result:
            _enrich_sources(conn, result)

    return job


@router.post("/generate/{job_id}/approve")
async def approve(job_id: str):
    return await _signal(job_id, "approve")


@router.post("/generate/{job_id}/request-changes")
async def request_changes(job_id: str):
    return await _signal(job_id, "request_changes")


def _enrich_sources(conn, result: dict) -> None:
    """Дописать к каждой ссылке документ, страницу, секцию и текст фрагмента."""
    citations = result.get("sources") or []
    ids = [str(citation["chunk_id"]) for citation in citations if citation.get("chunk_id")]
    chunks = chunks_repo.get_chunks_by_ids(conn, ids)
    for citation in citations:
        chunk = chunks.get(str(citation.get("chunk_id")))
        if chunk:
            metadata = chunk.get("metadata") or {}
            citation.update(
                {
                    "document": chunk.get("filename"),
                    "page": metadata.get("page"),
                    "section": metadata.get("section"),
                    "article": metadata.get("articul"),
                    "brand": metadata.get("brand"),
                    "text": chunk.get("text"),
                }
            )


async def _signal(job_id: str, name: str) -> dict:
    with db.connection() as conn:
        if not jobs_repo.get_job(conn, job_id):
            raise HTTPException(404, "job not found")

    client = await get_client()
    handle = client.get_workflow_handle(job_id)
    try:
        await handle.signal(name)
    except RPCError as exc:
        raise HTTPException(404, f"workflow not found: {exc.message}")
    return {"id": job_id, "signaled": name}
