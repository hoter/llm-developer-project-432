"""Мульти-агент через брокер: две очереди, две таски, петля регенерации.

generate_card (очередь card.generate):
    extract → generate → UPDATE jobs → отправить critique_card.

critique_card (очередь card.critique):
    critique → approve: финализировать; regenerate и attempts < 3:
    отправить generate_card с feedback; иначе rejected.

Celery-таски sync, а Agents SDK async → мост asyncio.run() в каждой таске.
Стейт между агентами живёт ТОЛЬКО в таблице jobs — не в памяти воркера.

Соединение берём на операцию, а не на весь шаг: пока идёт вызов модели,
коннект уже вернулся в пул и не занимает место зря.
"""
import asyncio

from app.core import db
from app.core.logging import get_logger
from app.repositories import jobs as jobs_repo
from app.schemas import CardDraft, SupplierFacts
from app.services import pipeline
from app.workers.celery_app import celery_app

log = get_logger(__name__)

MAX_ATTEMPTS = 3


def _set_status(job_id: str, status: str, **kwargs) -> None:
    """Короткое обращение к базе: соединение на операцию."""
    with db.connection() as conn:
        jobs_repo.set_status(conn, job_id, status, **kwargs)


@celery_app.task(name="app.workers.tasks.generate_card", max_retries=2)
def generate_card(job_id: str, supplier_text: str, feedback: list[str] | None = None):
    try:
        _set_status(job_id, "extracting")
        facts = asyncio.run(pipeline.extract(supplier_text))
        _set_status(job_id, "generating", bump_attempts=True)
        draft = asyncio.run(pipeline.generate(facts, feedback))
        _set_status(job_id, "critiquing")
        celery_app.send_task(
            "app.workers.tasks.critique_card",
            kwargs={
                "job_id": job_id,
                "supplier_text": supplier_text,
                "facts_json": facts.model_dump_json(),
                "draft_json": draft.model_dump_json(),
            },
            queue="card.critique",
        )
    except Exception as exc:
        _set_status(job_id, "failed", error=repr(exc))
        log.error("generate_failed", job_id=job_id, error=repr(exc))
        raise


@celery_app.task(name="app.workers.tasks.critique_card", max_retries=2)
def critique_card(job_id: str, supplier_text: str, facts_json: str, draft_json: str):
    try:
        facts = SupplierFacts.model_validate_json(facts_json)
        draft = CardDraft.model_validate_json(draft_json)
        report = asyncio.run(pipeline.critique(facts, draft))

        if report.verdict == "approve":
            _set_status(job_id, "approved", result=draft)
            log.info("job_approved", job_id=job_id)
            return

        with db.connection() as conn:
            row = jobs_repo.get_job(conn, job_id)
        if row and row["attempts"] < MAX_ATTEMPTS:
            _set_status(job_id, "regenerating")
            log.info("job_regenerate", job_id=job_id, issues=report.issues)
            celery_app.send_task(
                "app.workers.tasks.generate_card",
                kwargs={
                    "job_id": job_id,
                    "supplier_text": supplier_text,
                    "feedback": report.issues,
                },
                queue="card.generate",
            )
        else:
            attempts = row["attempts"] if row else 0
            _set_status(
                job_id, "rejected", result=draft,
                error=f"critic not satisfied after {attempts} attempts",
            )
            log.info("job_rejected", job_id=job_id, issues=report.issues)
    except Exception as exc:
        _set_status(job_id, "failed", error=repr(exc))
        log.error("critique_failed", job_id=job_id, error=repr(exc))
        raise
