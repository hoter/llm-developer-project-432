"""CardWorkflow: extract → (generate → critique)* → подтверждение → финал.

Правила детерминизма workflow-кода: никаких datetime.now / random / сети /
чтения базы и конфига — только логика и вызовы activities. Всё, что ходит
наружу, живёт в app/temporal/activities.py.

Два уровня повторов, и это разные вещи:
- клиент модели (app/llm/client.py) повторяет один вызов — дёшево;
- движок повторяет шаг целиком (RetryPolicy ниже) — дорого, поэтому попыток
  меньше и только на ошибках, которые повтор лечит.

Таймауты и лимиты — константы модуля, а не settings: конфиг меняется между
реплеями и ломает воспроизведение истории.
"""
import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    # Activities импортируются под passthrough: их модуль тянет psycopg,
    # LLM-клиент и openai, которым в песочнице не место. Workflow использует
    # только ссылки на функции — исполнение всё равно вне песочницы.
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

ACTIVITY_TIMEOUT = timedelta(seconds=300)
# Воркер шлёт heartbeat каждые 10 секунд (app/temporal/activities.py),
# поэтому смерть воркера видна через полминуты, а не через 5 минут.
HEARTBEAT_TIMEOUT = timedelta(seconds=30)
STATUS_TIMEOUT = timedelta(seconds=30)
MAX_ATTEMPTS = 3

# Один шаг = один вызов модели (внутри него клиент уже сделал свои ретраи).
STEP_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=3,
    # Кривой ответ модели и ошибка валидации повтором не лечатся.
    non_retryable_error_types=["ValidationError", "ValueError"],
)

STATUS_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_attempts=5,
)


@workflow.defn
class CardWorkflow:
    def __init__(self) -> None:
        self._status = "starting"
        self._decision: str | None = None

    @workflow.run
    async def run(
        self,
        job_id: str,
        supplier_text: str,
        request_id: str | None = None,
        max_attempts: int = MAX_ATTEMPTS,
        confidence_threshold: float = 0.6,
    ) -> str:
        try:
            await self._set_status(job_id, "extracting", request_id=request_id)
            facts_json = await workflow.execute_activity(
                extract_activity,
                args=[supplier_text, job_id, request_id],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=STEP_RETRY,
            )

            feedback: list[str] = []
            draft_json = "{}"
            attempts = 0
            while attempts < max_attempts:
                attempts += 1
                await self._set_status(job_id, "generating", bump_attempts=True, request_id=request_id)
                draft_json = await workflow.execute_activity(
                    generate_activity,
                    args=[
                        facts_json,
                        json.dumps(feedback, ensure_ascii=False) if feedback else None,
                        job_id,
                        request_id,
                    ],
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=STEP_RETRY,
                )

                await self._set_status(job_id, "critiquing", request_id=request_id)
                report_json = await workflow.execute_activity(
                    critique_activity,
                    args=[facts_json, draft_json, job_id, request_id],
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=STEP_RETRY,
                )
                report = json.loads(report_json)
                if report.get("verdict") == "approve":
                    break

                feedback = report.get("issues") or []
                if attempts < max_attempts:
                    await self._set_status(job_id, "regenerating", request_id=request_id)

            # Человек решает всегда: петля могла исчерпаться, но черновик есть,
            # и последнее слово — за контент-менеджером. Порог уверенности
            # только уточняет состояние: «уверенная» карточка ждёт подтверждения,
            # «неуверенная» помечается как требующая разбора.
            confidence = float(json.loads(draft_json).get("confidence", 0.0))
            needs_review = confidence < confidence_threshold
            await self._set_status(
                job_id,
                "needs_review" if needs_review else "awaiting_approval",
                result_json=draft_json,
                request_id=request_id,
            )
            if needs_review:
                workflow.logger.info(
                    "low confidence %.2f < %.2f for job %s",
                    confidence,
                    confidence_threshold,
                    job_id,
                )
            await workflow.wait_condition(lambda: self._decision is not None)

            if self._decision == "approve":
                await self._set_status(job_id, "approved", result_json=draft_json, request_id=request_id)
            else:
                await self._set_status(
                    job_id,
                    "rejected",
                    result_json=draft_json,
                    error="rejected by human",
                    request_id=request_id,
                )
            return draft_json
        except Exception as exc:
            # Best effort: если воркер убили, статус останется прежним и
            # процесс продолжится после рестарта — история в Temporal цела.
            try:
                await self._set_status(job_id, "failed", error=repr(exc), request_id=request_id)
            except Exception:
                workflow.logger.exception("failed to mark job %s as failed", job_id)
            raise

    async def _set_status(
        self,
        job_id: str,
        status: str,
        *,
        result_json: str | None = None,
        error: str | None = None,
        bump_attempts: bool = False,
        request_id: str | None = None,
    ) -> None:
        """Статус предметной области — отдельным шагом процесса."""
        self._status = status
        await workflow.execute_activity(
            set_status_activity,
            args=[job_id, status, result_json, error, bump_attempts, request_id],
            start_to_close_timeout=STATUS_TIMEOUT,
            retry_policy=STATUS_RETRY,
        )

    @workflow.signal
    def approve(self) -> None:
        self._decision = "approve"

    @workflow.signal
    def request_changes(self) -> None:
        self._decision = "reject"

    @workflow.query
    def current_status(self) -> str:
        return self._status


DOCUMENT_TIMEOUT = timedelta(minutes=10)
DOCUMENT_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=3,
)


@workflow.defn
class DocumentWorkflow:
    """Разбор документа поставщика: один шаг, повтор на инфраструктурных сбоях.

    Ошибка разбора (скан без OCR, битый файл) не ретраится: activity сама
    ставит документу статус failed с причиной и возвращает его.
    """

    @workflow.run
    async def run(self, document_id: str, request_id: str | None = None) -> str:
        return await workflow.execute_activity(
            parse_document_activity,
            args=[document_id, request_id],
            start_to_close_timeout=DOCUMENT_TIMEOUT,
            retry_policy=DOCUMENT_RETRY,
        )


@workflow.defn
class RagCardWorkflow:
    """Сквозной сценарий: поиск, генерация, проверка ссылок, критик, человек."""

    def __init__(self) -> None:
        self._status = "starting"
        self._decision: str | None = None

    @workflow.run
    async def run(
        self,
        job_id: str,
        document_ids: list[str],
        hint: str | None = None,
        request_id: str | None = None,
        max_attempts: int = MAX_ATTEMPTS,
        confidence_threshold: float = 0.6,
    ) -> str:
        try:
            await self._set_status(job_id, "retrieving", request_id=request_id)
            context_json = await workflow.execute_activity(
                retrieve_context_activity,
                args=[document_ids, hint, job_id, request_id],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=STEP_RETRY,
            )

            feedback: list[str] = []
            draft_json = "{}"
            attempts = 0
            while attempts < max_attempts:
                attempts += 1

                await self._set_status(job_id, "generating", bump_attempts=True, request_id=request_id)
                draft_json = await workflow.execute_activity(
                    generate_card_activity,
                    args=[
                        context_json,
                        hint,
                        json.dumps(feedback, ensure_ascii=False) if feedback else None,
                        job_id,
                        request_id,
                    ],
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=STEP_RETRY,
                )

                await self._set_status(job_id, "verifying", request_id=request_id)
                errors = json.loads(
                    await workflow.execute_activity(
                        verify_citations_activity,
                        args=[draft_json, context_json, job_id, request_id],
                        start_to_close_timeout=STATUS_TIMEOUT,
                        retry_policy=STATUS_RETRY,
                    )
                )
                if errors:
                    feedback = errors
                    workflow.logger.info("citations rejected on attempt %s", attempts)
                    if attempts < max_attempts:
                        await self._set_status(job_id, "regenerating", request_id=request_id)
                    continue

                await self._set_status(job_id, "critiquing", request_id=request_id)
                report = json.loads(
                    await workflow.execute_activity(
                        critique_card_activity,
                        args=[draft_json, context_json, job_id, request_id],
                        start_to_close_timeout=ACTIVITY_TIMEOUT,
                        heartbeat_timeout=HEARTBEAT_TIMEOUT,
                        retry_policy=STEP_RETRY,
                    )
                )
                if report.get("verdict") == "approve":
                    break
                feedback = report.get("issues") or []
                if attempts < max_attempts:
                    await self._set_status(job_id, "regenerating", request_id=request_id)

            confidence = float(json.loads(draft_json).get("confidence", 0.0))
            await self._set_status(
                job_id,
                "needs_review" if confidence < confidence_threshold else "awaiting_approval",
                result_json=draft_json,
                request_id=request_id,
            )
            await workflow.wait_condition(lambda: self._decision is not None)

            if self._decision == "approve":
                await self._set_status(job_id, "approved", result_json=draft_json, request_id=request_id)
            else:
                await self._set_status(
                    job_id,
                    "rejected",
                    result_json=draft_json,
                    error="rejected by human",
                    request_id=request_id,
                )
            return draft_json
        except Exception as exc:
            try:
                await self._set_status(job_id, "failed", error=repr(exc), request_id=request_id)
            except Exception:
                workflow.logger.exception("failed to mark job %s as failed", job_id)
            raise

    async def _set_status(
        self,
        job_id: str,
        status: str,
        *,
        result_json: str | None = None,
        error: str | None = None,
        bump_attempts: bool = False,
        request_id: str | None = None,
    ) -> None:
        self._status = status
        await workflow.execute_activity(
            set_status_activity,
            args=[job_id, status, result_json, error, bump_attempts, request_id],
            start_to_close_timeout=STATUS_TIMEOUT,
            retry_policy=STATUS_RETRY,
        )

    @workflow.signal
    def approve(self) -> None:
        self._decision = "approve"

    @workflow.signal
    def request_changes(self) -> None:
        self._decision = "reject"

    @workflow.query
    def current_status(self) -> str:
        return self._status
