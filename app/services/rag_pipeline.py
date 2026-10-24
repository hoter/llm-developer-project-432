"""Сквозной RAG-сценарий: поиск → контекст → генерация → проверка ссылок → критик.

Ссылка проходит проверку, только если фрагмент существует в базе И был в
поданном контексте. Сослаться на реальный, но невиденный фрагмент — то же
выдумывание, только правдоподобное.
"""
import json

from app.agents.prompts import critic_agent, rag_generator_agent
from app.core import db
from app.core.config import settings
from app.core.logging import get_logger
from app.guardrails import GuardReport, guard_context
from app.llm.client import run_agent
from app.rag.context import build_context, context_chunk_ids
from app.repositories import chunks as chunks_repo
from app.schemas import CardDraft, CritiqueReport
from app.services.json_utils import parse_llm_json
from app.services.structured import confidence_gate

log = get_logger(__name__)


class SourceValidationError(RuntimeError):
    """Ссылки не подтвердились за отведённое число попыток."""


async def retrieve_context_async(
    query: str, doc_ids: list[str] | None = None
) -> tuple[str, GuardReport]:
    """Найти фрагменты, пропустить их через защиту и собрать контекст."""
    with db.connection() as conn:
        rows = chunks_repo.search_hybrid(
            conn, query, top_k=settings.rag_search_limit, doc_ids=doc_ids
        )
    chunks = [
        {
            "chunk_id": row["chunk_id"],
            "text": row["text"],
            "metadata": row.get("metadata") or {},
            "filename": row.get("filename"),
        }
        for row in rows
    ]
    safe, report = await guard_context(chunks)
    return build_context(safe), report


async def run_rag_pipeline(
    query: str, doc_ids: list[str] | None = None, max_attempts: int = 3
) -> tuple[CardDraft, int, str, str, GuardReport]:
    """Полный цикл. Возвращает (черновик, попытки, вердикт, статус, отчёт защиты)."""
    context, guard = await retrieve_context_async(query, doc_ids)
    if not context:
        raise SourceValidationError("контекст пуст: все фрагменты исключены защитой")

    feedback: list[str] = []
    draft: CardDraft | None = None
    attempts = 0
    verdict = "rejected"
    status = "rejected"
    last_source_errors: list[str] = []

    for attempt in range(1, max_attempts + 1):
        attempts = attempt
        draft = await generate_card(context, query, feedback or None)

        errors = validate_sources(draft, context)
        if errors:
            last_source_errors = errors
            feedback = errors
            log.info("sources_rejected", attempt=attempt, errors=errors)
            continue
        last_source_errors = []

        report = await critique_card(context, draft)
        if report.verdict == "approve":
            status = confidence_gate(draft)
            verdict = "approved" if status == "done" else "needs_review"
            break
        feedback = report.issues
        log.info("rag_regenerate", attempt=attempt, issues=report.issues)

    if last_source_errors:
        raise SourceValidationError("; ".join(last_source_errors))

    assert draft is not None
    return draft, attempts, verdict, status, guard


async def generate_card(
    context: str, hint: str | None = None, feedback: list[str] | None = None
) -> CardDraft:
    raw = await run_agent(rag_generator_agent, _generation_prompt(context, hint, feedback))
    return CardDraft.model_validate(parse_llm_json(raw))


async def critique_card(context: str, draft: CardDraft) -> CritiqueReport:
    prompt = (
        context
        + "\n\nЧерновик карточки:\n"
        + draft.model_dump_json(indent=2)
        + "\n\nСверь каждое утверждение с фрагментом, на который оно ссылается. "
        "Если подтверждения нет — verdict regenerate и конкретные issues."
    )
    raw = await run_agent(critic_agent, prompt)
    return CritiqueReport.model_validate(parse_llm_json(raw))


def validate_sources(draft: CardDraft, context: str) -> list[str]:
    """Ссылка существует в базе и была в поданном контексте."""
    errors: list[str] = []
    if not draft.sources:
        errors.append("в карточке нет ни одной ссылки на источник")
        return errors

    cited = [source.chunk_id for source in draft.sources]
    with db.connection() as conn:
        existing = chunks_repo.existing_chunk_ids(conn, cited)
    context_ids = context_chunk_ids(context)

    for source in draft.sources:
        if source.chunk_id not in context_ids:
            if source.chunk_id in existing:
                errors.append(
                    f"источник {source.chunk_id} существует, но не был в контексте"
                )
            else:
                errors.append(f"источника {source.chunk_id} нет в базе")
    return errors


def _generation_prompt(
    context: str, hint: str | None, feedback: list[str] | None
) -> str:
    parts = [context]
    if hint:
        parts.append(f"Подсказка о товаре: {hint}")
    if feedback:
        parts.append(
            "Предыдущая попытка отклонена, исправь:\n"
            + "\n".join(f"- {issue}" for issue in feedback)
        )
    parts.append(
        "Собери карточку по контексту. Каждая характеристика должна иметь "
        "ссылку sources с chunk_id из шапки фрагмента. Чего нет в контексте — "
        "в missing_fields. Верни только JSON по схеме."
    )
    return "\n\n".join(parts)


def dump_guard_report(report: GuardReport) -> str:
    return json.dumps(
        {
            "masked_pii": report.masked_pii,
            "suspicious_chunks": report.suspicious_chunks,
            "needs_review": report.needs_review,
        },
        ensure_ascii=False,
    )
