"""Сквозной сценарий: поиск → контекст → генерация → проверка ссылок → критика.

Три рубежа против выдумывания:
1. поиск: модель видит только найденные фрагменты;
2. проверка ссылок: каждый cited фрагмент существует в базе И был в поданном
   контексте (второе важнее первого — «правдоподобная» ссылка на фрагмент,
   которого модель не видела, и есть выдумывание);
3. критик: сверяет каждое утверждение с заявленным для него источником.

Функции шага используются и Temporal-activities, и тестами: durable-процесс
повторяет ту же последовательность, но с записью состояния после каждого шага.
"""
import json
from dataclasses import dataclass
from pathlib import Path

from app.agents.prompts import rag_critic_agent, rag_generator_agent
from app.core import db
from app.core.config import settings
from app.core.logging import get_logger
from app.rag.context import DocumentContext, build_context
from app.rag.retrieval import SearchFilters, search
from app.repositories import chunks as chunks_repo
from app.repositories import documents as documents_repo
from app.schemas import CardDraft, Citation, CritiqueReport
from app.services.structured import call_structured

log = get_logger(__name__)


class NoContextError(RuntimeError):
    """По выбранным документам ничего не нашлось."""


@dataclass
class RagPipelineResult:
    draft: CardDraft
    attempts: int
    verdict: str
    context: DocumentContext


def retrieve_context(document_ids: list[str], hint: str | None = None) -> DocumentContext:
    """Найти фрагменты выбранных документов и собрать контекст.

    Запрос — подсказка, а если её нет, названия документов (заголовки видны
    в именах файлов и секциях).
    """
    query = (hint or "").strip()
    if not query:
        with db.connection() as conn:
            documents = documents_repo.get_documents(conn, document_ids)
        query = " ".join(Path(doc["filename"]).stem.replace("_", " ") for doc in documents)

    rows = search(
        query or "товар",
        mode="hybrid",
        limit=settings.rag_search_limit,
        filters=SearchFilters(document_ids=document_ids),
    )
    context = build_context(rows)
    if not context.sources:
        raise NoContextError(
            "по выбранным документам не нашлось ни одного фрагмента для контекста"
        )
    return context


async def generate_card(
    context: DocumentContext,
    hint: str | None = None,
    feedback: list[str] | None = None,
) -> CardDraft:
    """Сгенерировать карточку по контексту и подменить метки на id фрагментов."""
    prompt = _generation_prompt(context, hint, feedback)
    draft = await call_structured(rag_generator_agent, prompt, CardDraft)
    return _apply_source_ids(draft, context)


async def critique_card(draft: CardDraft, context: DocumentContext) -> CritiqueReport:
    """Сверить карточку с источниками отдельной ролью."""
    prompt = (
        context.text
        + "\n\nЧерновик карточки:\n"
        + draft.model_dump_json(indent=2)
        + "\n\nСверь каждое утверждение с фрагментом, на который оно ссылается. "
        "Если подтверждения нет — verdict regenerate и конкретные issues."
    )
    # Сверка утверждений — служебный вызов: дешёвая модель
    return await call_structured(rag_critic_agent, prompt, CritiqueReport, aux=True)


def verify_citations(draft: CardDraft, context: DocumentContext) -> list[str]:
    """Проверить ссылки: фрагмент существует и был в поданном контексте."""
    errors: list[str] = []
    if not draft.sources:
        errors.append("в карточке нет ни одной ссылки на источник")

    numeric_ids = [int(item.chunk_id) for item in draft.sources if item.chunk_id.isdigit()]
    with db.connection() as conn:
        existing = {
            str(chunk_id) for chunk_id in chunks_repo.existing_chunk_ids(conn, numeric_ids)
        }

    context_ids = context.chunk_ids()
    for citation in draft.sources:
        if citation.chunk_id in context_ids:
            continue
        if citation.chunk_id in existing:
            errors.append(
                f"источник {citation.chunk_id} для поля «{citation.field}» "
                "существует, но не был в контексте"
            )
        else:
            errors.append(
                f"источника {citation.chunk_id} для поля «{citation.field}» "
                "нет в базе"
            )

    cited_fields = {citation.field for citation in draft.sources}
    for name in draft.characteristics:
        if f"characteristics.{name}" not in cited_fields:
            errors.append(f"характеристика «{name}» без ссылки на источник")

    return errors


async def run_pipeline(
    document_ids: list[str],
    hint: str | None = None,
    max_attempts: int = 3,
) -> RagPipelineResult:
    """Полный цикл для тестов и не-Temporal вызовов."""
    context = retrieve_context(document_ids, hint)
    feedback: list[str] = []
    draft: CardDraft | None = None
    verdict = "rejected"
    attempts = 0

    for attempt in range(1, max_attempts + 1):
        attempts = attempt
        draft = await generate_card(context, hint, feedback or None)

        citation_errors = verify_citations(draft, context)
        if citation_errors:
            feedback = citation_errors
            log.info("citations_rejected", attempt=attempt, errors=citation_errors)
            continue

        report = await critique_card(draft, context)
        if report.verdict == "approve":
            verdict = (
                "needs_review"
                if draft.confidence < settings.confidence_threshold
                else "approved"
            )
            break
        feedback = report.issues
        log.info("rag_regenerate", attempt=attempt, issues=report.issues)

    assert draft is not None
    return RagPipelineResult(
        draft=draft, attempts=attempts, verdict=verdict, context=context
    )


def _apply_source_ids(draft: CardDraft, context: DocumentContext) -> CardDraft:
    """[S1] из ответа модели → настоящий id фрагмента (если метка из контекста)."""
    mapping = {source.source_id: source.chunk_id for source in context.sources}
    citations = [
        Citation(
            field=citation.field,
            chunk_id=mapping.get(citation.chunk_id, citation.chunk_id),
        )
        for citation in draft.sources
    ]
    return draft.model_copy(update={"sources": citations})


def _generation_prompt(
    context: DocumentContext, hint: str | None, feedback: list[str] | None
) -> str:
    parts = [context.text]
    if hint:
        parts.append(f"Подсказка о товаре: {hint}")
    if feedback:
        parts.append(
            "Предыдущая попытка отклонена, исправь:\n"
            + "\n".join(f"- {issue}" for issue in feedback)
        )
    parts.append(
        "Собери карточку по контексту. У каждой характеристики должна быть "
        "ссылка вида {\"field\": \"characteristics.<имя>\", \"chunk_id\": \"S1\"}. "
        "Чего нет в контексте — в missing_fields."
    )
    return "\n\n".join(parts)


def dump_result(result: RagPipelineResult) -> str:
    """Сериализация результата для activity."""
    return json.dumps(
        {
            "draft": result.draft.model_dump(),
            "attempts": result.attempts,
            "verdict": result.verdict,
        },
        ensure_ascii=False,
    )
