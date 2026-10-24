"""Temporal-activities: единственные места, где шагу процесса разрешены side-effects.

Activities выполняются вне песочницы workflow: можно ходить в базу, в LLM,
читать файлы. Между workflow и activities данные передаём JSON-строками —
Temporal сериализует их в историю процесса, Pydantic-валидация происходит
на границе шага.

Каждый вызов оборачивается контекстом логов: job_id приходит аргументом
процесса, request_id — из HTTP-запроса, который его запустил. Поэтому один
поиск по job_id показывает весь путь: обработчик, шаги, вызовы модели.
"""
import asyncio
import json
from contextlib import contextmanager

from structlog.contextvars import bound_contextvars
from temporalio import activity

from app.core import db
from app.core.logging import get_logger
from app.rag.context import DocumentContext
from app.repositories import jobs as jobs_repo
from app.schemas import CardDraft, SupplierFacts
from app.services import documents as documents_service
from app.services import pipeline, rag_pipeline

log = get_logger(__name__)

# Как часто долгий шаг отмечается в движке. По heartbeat_timeout движок
# понимает, что воркер умер, и отдаёт шаг на повтор другому воркеру —
# не дожидаясь start_to_close_timeout в несколько минут.
HEARTBEAT_INTERVAL_S = 10


@contextmanager
def activity_context(job_id: str | None = None, request_id: str | None = None):
    """Привязать задачу и запрос к контексту логов на время activity."""
    values = {}
    if job_id:
        values["job_id"] = job_id
    if request_id:
        values["request_id"] = request_id
    with bound_contextvars(**values):
        yield


async def _with_heartbeat(coro):
    async def _beat() -> None:
        while True:
            activity.heartbeat()
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)

    task = asyncio.create_task(_beat())
    try:
        return await coro
    finally:
        task.cancel()


@activity.defn
async def extract_activity(
    supplier_text: str, job_id: str | None = None, request_id: str | None = None
) -> str:
    with activity_context(job_id, request_id):
        facts = await _with_heartbeat(pipeline.extract(supplier_text))
        return facts.model_dump_json()


@activity.defn
async def generate_activity(
    facts_json: str,
    feedback_json: str | None = None,
    job_id: str | None = None,
    request_id: str | None = None,
) -> str:
    with activity_context(job_id, request_id):
        facts = SupplierFacts.model_validate_json(facts_json)
        feedback = json.loads(feedback_json) if feedback_json else None
        draft = await _with_heartbeat(pipeline.generate(facts, feedback))
        return draft.model_dump_json()


@activity.defn
async def critique_activity(
    facts_json: str,
    draft_json: str,
    job_id: str | None = None,
    request_id: str | None = None,
) -> str:
    with activity_context(job_id, request_id):
        facts = SupplierFacts.model_validate_json(facts_json)
        draft = CardDraft.model_validate_json(draft_json)
        report = await _with_heartbeat(pipeline.critique(facts, draft))
        return report.model_dump_json()


@activity.defn
def set_status_activity(
    job_id: str,
    status: str,
    result_json: str | None = None,
    error: str | None = None,
    bump_attempts: bool = False,
    request_id: str | None = None,
) -> None:
    """Синхронная activity: короткое обращение к базе.

    Не отдаёт управление, поэтому воркер запускает её в пуле потоков
    (activity_executor в app/temporal_worker.py). Соединение берём на
    операцию и сразу возвращаем в пул.
    """
    with activity_context(job_id, request_id):
        result = CardDraft.model_validate_json(result_json) if result_json else None
        with db.connection() as conn:
            jobs_repo.set_status(
                conn,
                job_id,
                status,
                result=result,
                error=error,
                bump_attempts=bump_attempts,
            )
        log.info("job_status", job_id=job_id, status=status)


@activity.defn
def parse_document_activity(document_id: str, request_id: str | None = None) -> str:
    """Разбор документа: диск + база, синхронно, в пуле потоков воркера.

    Возвращает новый статус документа («indexed» или «failed»). Отказ с
    причиной — нормальный исход: скан без текстового слоя не индексируется.
    """
    with activity_context(request_id=request_id):
        return documents_service.ingest_document(document_id)


@activity.defn
def retrieve_context_activity(
    document_ids: list[str],
    hint: str | None = None,
    job_id: str | None = None,
    request_id: str | None = None,
) -> str:
    """Поиск и сборка контекста: embeddings + SQL, синхронно в пуле потоков."""
    with activity_context(job_id, request_id):
        return rag_pipeline.retrieve_context(document_ids, hint).to_json()


@activity.defn
async def generate_card_activity(
    context_json: str,
    hint: str | None = None,
    feedback_json: str | None = None,
    job_id: str | None = None,
    request_id: str | None = None,
) -> str:
    with activity_context(job_id, request_id):
        context = DocumentContext.from_json(context_json)
        feedback = json.loads(feedback_json) if feedback_json else None
        draft = await _with_heartbeat(
            rag_pipeline.generate_card(context, hint, feedback)
        )
        return draft.model_dump_json()


@activity.defn
def verify_citations_activity(
    draft_json: str,
    context_json: str,
    job_id: str | None = None,
    request_id: str | None = None,
) -> str:
    """Проверка ссылок: фрагмент существует и был в контексте (SQL + память)."""
    with activity_context(job_id, request_id):
        draft = CardDraft.model_validate_json(draft_json)
        context = DocumentContext.from_json(context_json)
        errors = rag_pipeline.verify_citations(draft, context)
        return json.dumps(errors, ensure_ascii=False)


@activity.defn
async def critique_card_activity(
    draft_json: str,
    context_json: str,
    job_id: str | None = None,
    request_id: str | None = None,
) -> str:
    with activity_context(job_id, request_id):
        draft = CardDraft.model_validate_json(draft_json)
        context = DocumentContext.from_json(context_json)
        report = await _with_heartbeat(rag_pipeline.critique_card(draft, context))
        return report.model_dump_json()
