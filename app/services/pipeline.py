"""Стадии пайплайна: extract → generate → critique.

Тот же код работает в синхронном обработчике и в Temporal-activities.
Генерация идёт через structured.validate_or_retry: ответ модели проверяется
по контракту, ошибка возвращается модели, попытки ограничены.
"""
from app.agents.prompts import critic_agent, extractor_agent
from app.core.logging import get_logger
from app.llm.client import run_agent
from app.schemas import CardDraft, CritiqueReport, SupplierFacts
from app.services import structured
from app.services.json_utils import parse_llm_json

log = get_logger(__name__)


async def extract(supplier_text: str) -> SupplierFacts:
    log.info("step_extract_start")
    raw = await run_agent(extractor_agent, supplier_text)
    return SupplierFacts.model_validate(parse_llm_json(raw))


async def generate(facts: SupplierFacts, feedback: list[str] | None = None) -> CardDraft:
    prompt = "Факты о товаре:\n" + facts.model_dump_json(indent=2)
    if feedback:
        prompt += "\n\nЗамечания критика, учти:\n" + "\n".join(f"- {i}" for i in feedback)
    log.info("step_generate_start", feedback=bool(feedback))
    return await structured.validate_or_retry(prompt)


async def critique(facts: SupplierFacts, draft: CardDraft) -> CritiqueReport:
    prompt = (
        "Факты о товаре:\n"
        + facts.model_dump_json(indent=2)
        + "\n\nЧерновик карточки для проверки:\n"
        + draft.model_dump_json(indent=2)
    )
    log.info("step_critique_start")
    raw = await run_agent(critic_agent, prompt)
    return CritiqueReport.model_validate(parse_llm_json(raw))


async def run_pipeline(supplier_text: str, max_attempts: int = 3):
    """Полный цикл. Возвращает (черновик, попытки, вердикт, статус)."""
    facts = await extract(supplier_text)
    feedback: list[str] = []
    attempts = 0
    draft = None
    verdict = "rejected"
    status = "rejected"

    while attempts < max_attempts:
        attempts += 1
        draft = await generate(facts, feedback or None)
        report = await critique(facts, draft)
        if report.verdict == "approve":
            status = structured.confidence_gate(draft)
            verdict = "approved" if status == "done" else "needs_review"
            break
        feedback = report.issues
        log.info("pipeline_regenerate", attempt=attempts, issues=report.issues)

    return draft, attempts, verdict, status
