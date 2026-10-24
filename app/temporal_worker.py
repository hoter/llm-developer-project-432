"""Точка входа Temporal-воркера: регистрирует workflow + activities.

Здесь же выдаётся пул потоков: синхронные activities (запись статуса)
не отдают управление, и без activity_executor движок откажется их брать —
один разбор документа встал бы поперёк всех остальных процессов.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from app.core import db
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.temporal.activities import (
    critique_activity,
    critique_card_activity,
    extract_activity,
    generate_activity,
    generate_card_activity,
    parse_document_activity,
    retrieve_context_activity,
    set_status_activity,
    verify_citations_activity,
)
from app.temporal.workflows import CardWorkflow, DocumentWorkflow, RagCardWorkflow

log = get_logger(__name__)

ACTIVITY_THREADS = 8


async def main() -> None:
    setup_logging()
    db.pool()
    client = await Client.connect(settings.temporal_host)
    executor = ThreadPoolExecutor(
        max_workers=ACTIVITY_THREADS, thread_name_prefix="activity"
    )
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[CardWorkflow, DocumentWorkflow, RagCardWorkflow],
        activities=[
            extract_activity,
            generate_activity,
            critique_activity,
            set_status_activity,
            parse_document_activity,
            retrieve_context_activity,
            generate_card_activity,
            verify_citations_activity,
            critique_card_activity,
        ],
        activity_executor=executor,
    )
    log.info(
        "temporal_worker_started",
        task_queue=settings.temporal_task_queue,
        activity_threads=ACTIVITY_THREADS,
    )
    try:
        await worker.run()
    finally:
        executor.shutdown(wait=True)
        db.close_pool()
        log.info("temporal_worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
