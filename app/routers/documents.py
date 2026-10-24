"""Документы: загрузка файла и чтение состояния.

Загрузка отвечает 202 и идентификатором: разбор делает фоновый процесс.
Повторная загрузка того же файла (sha256) возвращает существующий документ
и не создаёт дубль.
"""
import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from app.core import db
from app.core.config import settings
from app.core.logging import current_request_id
from app.rag import retrieval
from app.repositories import documents as documents_repo
from app.schemas import DocumentOut
from app.temporal.client import get_client

router = APIRouter(tags=["documents"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx"}


@router.post("/documents", status_code=202)
async def upload_document(file: UploadFile = File(...)):
    filename = Path(file.filename or "").name
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            415, f"формат «{extension or 'без расширения'}» не поддерживается"
        )

    data = await file.read(settings.max_upload_bytes + 1)
    if not data:
        raise HTTPException(400, "пустой файл")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            413, f"файл больше допустимых {settings.max_upload_bytes} байт"
        )

    digest = hashlib.sha256(data).hexdigest()

    with db.connection() as conn:
        existing = documents_repo.get_by_hash(conn, digest)
        if existing:
            document = documents_repo.get_document(conn, existing["id"])
            return JSONResponse(
                {"id": document["id"], "status": document["status"]}, status_code=202
            )

    uploads_dir = Path(settings.uploads_dir)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    stored_path = uploads_dir / f"{digest}{extension}"
    stored_path.write_bytes(data)

    document_id = uuid.uuid4().hex[:12]
    with db.connection() as conn:
        document_id, _created = documents_repo.create_document(
            conn,
            document_id=document_id,
            filename=filename,
            content_hash=digest,
            kind=extension.lstrip("."),
            size_bytes=len(data),
            content_type=file.content_type,
            stored_path=str(stored_path),
        )

    await _start_workflow(document_id)
    return JSONResponse({"id": document_id, "status": "new"}, status_code=202)


@router.get("/search")
async def search(
    q: str,
    mode: str = "hybrid",
    limit: int | None = None,
    min_similarity: float | None = None,
    document_id: str | None = None,
    section: str | None = None,
    article: str | None = None,
    brand: str | None = None,
):
    """Поиск по фрагментам: vector | text | hybrid + фильтры по метаданным."""
    try:
        return retrieval.search(
            q,
            mode=mode,
            limit=limit,
            min_similarity=min_similarity,
            filters=retrieval.SearchFilters(
                document_id=document_id,
                section=section,
                article=article,
                brand=brand,
            ),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(document_id: str):
    with db.connection() as conn:
        document = documents_repo.get_document(conn, document_id)
    if not document:
        raise HTTPException(404, "document not found")
    return document


async def _start_workflow(document_id: str) -> None:
    client = await get_client()
    try:
        await client.start_workflow(
            "DocumentWorkflow",
            args=[document_id, current_request_id()],
            id=f"document-{document_id}",
            task_queue=settings.temporal_task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    except WorkflowAlreadyStartedError:
        pass
