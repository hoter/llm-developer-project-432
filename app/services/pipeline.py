"""Стадии пайплайна: extract → generate → critique.

Каждая функция — один агент-шаг. Один и тот же код работает в двух runtime:
- синхронный эндпоинт POST /cards (весь пайплайн в запросе),
- Temporal activities в фоновом процессе.
Это и есть выигрыш слоистой архитектуры.

Пайплайн не знает про базу и статусы: состояние задачи пишет отдельный шаг
процесса (app/temporal/activities.py). Зато он знает про контракт: ответ
модели проходит через app/services/structured.py — разбор, валидацию и
лечение, а не «повезёт/не повезёт».
"""
from app.agents.prompts import critic_agent, extractor_agent, generator_agent
from app.core.config import settings
from app.core.logging import get_logger
from app.schemas import CardDraft, CritiqueReport, SupplierFacts
from app.services.structured import call_structured

log = get_logger(__name__)


async def extract(supplier_text: str) -> SupplierFacts:
    log.info("step_extract_start")
    return await call_structured(extractor_agent, supplier_text, SupplierFacts)


async def generate(facts: SupplierFacts, feedback: list[str] | None = None) -> CardDraft:
    prompt = "Факты о товаре:\n" + facts.model_dump_json(indent=2)
    if feedback:
        prompt += "\n\nЗамечания критика, учти:\n" + "\n".join(f"- {i}" for i in feedback)
    log.info("step_generate_start", feedback=bool(feedback))
    return await call_structured(generator_agent, prompt, CardDraft)


async def critique(facts: SupplierFacts, draft: CardDraft) -> CritiqueReport:
    prompt = (
        "Факты о товаре:\n"
        + facts.model_dump_json(indent=2)
        + "\n\nЧерновик карточки для проверки:\n"
        + draft.model_dump_json(indent=2)
    )
    log.info("step_critique_start")
    return await call_structured(critic_agent, prompt, CritiqueReport)


async def run_pipeline(supplier_text: str, max_attempts: int = 3):
    """Полный цикл: extract → (generate → critique → feedback)* → итог.

    Возвращает (итоговый черновик, число генераций, вердикт).

    Вердикт ``needs_review`` — критик доволен, но уверенность модели ниже
    порога: такая карточка не «готова», её обязан посмотреть человек.
    """
    facts = await extract(supplier_text)
    feedback: list[str] = []
    attempts = 0
    draft = None
    verdict = "rejected"
    while attempts < max_attempts:
        attempts += 1
        draft = await generate(facts, feedback or None)
        report = await critique(facts, draft)
        if report.verdict == "approve":
            if draft.confidence < settings.confidence_threshold:
                verdict = "needs_review"
                log.info(
                    "pipeline_low_confidence",
                    confidence=draft.confidence,
                    threshold=settings.confidence_threshold,
                    missing=len(draft.missing_fields),
                )
            else:
                verdict = "approved"
            break
        feedback = report.issues
        log.info("pipeline_regenerate", attempt=attempts, issues=report.issues)
    return draft, attempts, verdict
