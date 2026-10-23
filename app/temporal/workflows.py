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
        extract_activity,
        generate_activity,
        set_status_activity,
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
        self, job_id: str, supplier_text: str, max_attempts: int = MAX_ATTEMPTS
    ) -> str:
        try:
            await self._set_status(job_id, "extracting")
            facts_json = await workflow.execute_activity(
                extract_activity,
                supplier_text,
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=STEP_RETRY,
            )

            feedback: list[str] = []
            draft_json = "{}"
            attempts = 0
            while attempts < max_attempts:
                attempts += 1
                await self._set_status(job_id, "generating", bump_attempts=True)
                draft_json = await workflow.execute_activity(
                    generate_activity,
                    args=[
                        facts_json,
                        json.dumps(feedback, ensure_ascii=False) if feedback else None,
                    ],
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=STEP_RETRY,
                )

                await self._set_status(job_id, "critiquing")
                report_json = await workflow.execute_activity(
                    critique_activity,
                    args=[facts_json, draft_json],
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=STEP_RETRY,
                )
                report = json.loads(report_json)
                if report.get("verdict") == "approve":
                    break

                feedback = report.get("issues") or []
                if attempts < max_attempts:
                    await self._set_status(job_id, "regenerating")

            # Человек решает всегда: петля могла исчерпаться, но черновик есть,
            # и последнее слово — за контент-менеджером.
            await self._set_status(job_id, "awaiting_approval", result_json=draft_json)
            await workflow.wait_condition(lambda: self._decision is not None)

            if self._decision == "approve":
                await self._set_status(job_id, "approved", result_json=draft_json)
            else:
                await self._set_status(
                    job_id, "rejected", result_json=draft_json, error="rejected by human"
                )
            return draft_json
        except Exception as exc:
            # Best effort: если воркер убили, статус останется прежним и
            # процесс продолжится после рестарта — история в Temporal цела.
            try:
                await self._set_status(job_id, "failed", error=repr(exc))
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
    ) -> None:
        """Статус предметной области — отдельным шагом процесса."""
        self._status = status
        await workflow.execute_activity(
            set_status_activity,
            args=[job_id, status, result_json, error, bump_attempts],
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
