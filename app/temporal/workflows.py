"""CardWorkflow: extract → (generate → critique)* → сигнал оператора → финал.

Правила детерминизма workflow-кода:
- никаких datetime.now / random / HTTP / чтения конфига — только логика;
- все side-effects — в activities (app/temporal/activities.py);
- таймауты и лимиты — константы модуля, не settings (конфиг меняется
  между реплеями и ломает воспроизведение истории).

Песочница воркфлоу запрещает тяжёлые импорты, поэтому app.schemas
проходит через workflow.unsafe.imports_passed_through().
"""
import json
from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    # Pydantic-модели используются только для парсинга JSON внутри workflow:
    # валидация детерминирована, сетевых вызовов нет — песочницу отключаем.
    from app.schemas import CritiqueReport

    # Activities импортируются под passthrough: их модуль тянет LLM-клиент
    # и openai/httpx2, которым в песочнице не место. Workflow использует
    # только ссылки на функции — исполнение всё равно вне песочницы.
    from app.temporal.activities import (
        critique_activity,
        extract_activity,
        generate_activity,
    )

ACTIVITY_TIMEOUT = timedelta(seconds=300)


@workflow.defn
class CardWorkflow:
    def __init__(self) -> None:
        self._status = "starting"
        self._human_decision: str | None = None

    @workflow.run
    async def run(self, supplier_text: str, max_attempts: int = 3) -> str:
        self._status = "extracting"
        facts_json = await workflow.execute_activity(
            extract_activity,
            supplier_text,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
        )

        feedback: list[str] = []
        attempts = 0
        draft_json = "{}"
        while attempts < max_attempts:
            attempts += 1
            self._status = f"generating (attempt {attempts})"
            draft_json = await workflow.execute_activity(
                generate_activity,
                args=[facts_json, json.dumps(feedback, ensure_ascii=False) if feedback else None],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
            )
            self._status = f"critiquing (attempt {attempts})"
            report = CritiqueReport.model_validate_json(
                await workflow.execute_activity(
                    critique_activity,
                    args=[facts_json, draft_json],
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                )
            )
            if report.verdict == "approve":
                break
            feedback = report.issues

        self._status = "awaiting human decision"
        await workflow.wait_condition(lambda: self._human_decision is not None)

        if self._human_decision == "approve":
            self._status = "completed"
        else:
            self._status = "rejected by human"
        return draft_json

    @workflow.signal
    def approve(self) -> None:
        self._human_decision = "approve"

    @workflow.signal
    def request_changes(self) -> None:
        self._human_decision = "regenerate"

    @workflow.query
    def current_status(self) -> str:
        return self._status
