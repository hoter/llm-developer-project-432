"""Temporal-activities: единственные места, где шагу процесса разрешены side-effects.

Каждый вызов оборачивается контекстом логов: job_id приходит аргументом
процесса, request_id — из HTTP-запроса, который его запустил.
"""
import asyncio
import json
from contextlib import contextmanager

from structlog.contextvars import bound_contextvars
from temporalio import activity

from app.core import db
from app.core.logging import get_logger
from app.guardrails import guard_output
from app.repositories import jobs as jobs_repo
from app.schemas import CardDraft, SupplierFacts
from app.services import documents as documents_service
from app.services import pipeline, rag_pipeline

log = get_logger(__name__)

HEARTBEAT_INTERVAL_S = 10


@contextmanager
def activity_context(job_id: str | None = None, request_id: str | None = None):
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
    with activity_context(job_id, request_id):
        result = None
        if result_json:
            cleaned, _issues = guard_output(result_json)
            result = CardDraft.model_validate_json(cleaned)
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
    with activity_context(request_id=request_id):
        return documents_service.ingest_document(document_id)


@activity.defn
async def retrieve_context_activity(
    document_ids: list[str],
    hint: str | None = None,
    job_id: str | None = None,
    request_id: str | None = None,
) -> str:
    with activity_context(job_id, request_id):
        context, report = await _with_heartbeat(
            rag_pipeline.retrieve_context_async(hint or "", document_ids)
        )
        return json.dumps(
            {
                "context": context,
                "report": {
                    "masked_pii": report.masked_pii,
                    "suspicious_chunks": report.suspicious_chunks,
                    "needs_review": report.needs_review,
                },
            },
            ensure_ascii=False,
        )


@activity.defn
def set_guard_report_activity(
    job_id: str, report_json: str, request_id: str | None = None
) -> None:
    with activity_context(job_id, request_id):
        with db.connection() as conn:
            jobs_repo.set_guard_report(conn, job_id, json.loads(report_json))


@activity.defn
async def generate_card_activity(
    context: str,
    hint: str | None = None,
    feedback_json: str | None = None,
    job_id: str | None = None,
    request_id: str | None = None,
) -> str:
    with activity_context(job_id, request_id):
        feedback = json.loads(feedback_json) if feedback_json else None
        draft = await _with_heartbeat(rag_pipeline.generate_card(context, hint, feedback))
        return draft.model_dump_json()


@activity.defn
def verify_citations_activity(
    draft_json: str,
    context: str,
    job_id: str | None = None,
    request_id: str | None = None,
) -> str:
    with activity_context(job_id, request_id):
        draft = CardDraft.model_validate_json(draft_json)
        errors = rag_pipeline.validate_sources(draft, context)
        return json.dumps(errors, ensure_ascii=False)


@activity.defn
def output_guard_activity(
    draft_json: str, job_id: str | None = None, request_id: str | None = None
) -> str:
    with activity_context(job_id, request_id):
        _cleaned, issues = guard_output(draft_json)
        return json.dumps(issues, ensure_ascii=False)


@activity.defn
async def critique_card_activity(
    draft_json: str,
    context: str,
    job_id: str | None = None,
    request_id: str | None = None,
) -> str:
    with activity_context(job_id, request_id):
        draft = CardDraft.model_validate_json(draft_json)
        report = await _with_heartbeat(rag_pipeline.critique_card(context, draft))
        return report.model_dump_json()
