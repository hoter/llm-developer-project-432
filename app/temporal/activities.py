"""Temporal-activities: единственные места, где шагу процесса разрешены side-effects.

Activities выполняются вне песочницы workflow: можно ходить в базу, в LLM,
читать файлы. Между workflow и activities данные передаём JSON-строками —
Temporal сериализует их в историю процесса, Pydantic-валидация происходит
на границе шага.

Статус предметной области пишется отдельной activity, а не внутри пайплайна:
шаг генерации минутами ждёт модель, а короткая запись в базу не должна
удерживать ни соединение, ни внимание движка.
"""
import asyncio
import json

from temporalio import activity

from app.core import db
from app.core.logging import get_logger
from app.repositories import jobs as jobs_repo
from app.schemas import CardDraft, SupplierFacts
from app.services import pipeline

log = get_logger(__name__)

# Как часто долгий шаг отмечается в движке. По heartbeat_timeout движок
# понимает, что воркер умер, и отдаёт шаг на повтор другому воркеру —
# не дожидаясь start_to_close_timeout в несколько минут.
HEARTBEAT_INTERVAL_S = 10


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
async def extract_activity(supplier_text: str) -> str:
    facts = await _with_heartbeat(pipeline.extract(supplier_text))
    return facts.model_dump_json()


@activity.defn
async def generate_activity(facts_json: str, feedback_json: str | None = None) -> str:
    facts = SupplierFacts.model_validate_json(facts_json)
    feedback = json.loads(feedback_json) if feedback_json else None
    draft = await _with_heartbeat(pipeline.generate(facts, feedback))
    return draft.model_dump_json()


@activity.defn
async def critique_activity(facts_json: str, draft_json: str) -> str:
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
) -> None:
    """Синхронная activity: короткое обращение к базе.

    Не отдаёт управление, поэтому воркер запускает её в пуле потоков
    (activity_executor в app/temporal_worker.py). Соединение берём на
    операцию и сразу возвращаем в пул.
    """
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
