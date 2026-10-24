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
from app.guardrails import injection, pii
from app.rag.context import DocumentContext, build_context
from app.rag.retrieval import SearchFilters, search
from app.repositories import chunks as chunks_repo
from app.repositories import documents as documents_repo
from app.schemas import TITLE_MAX_LENGTH, CardDraft, Citation, CritiqueReport
from app.services.structured import call_structured

log = get_logger(__name__)


class NoContextError(RuntimeError):
    """По выбранным документам ничего не нашлось."""


class GuardrailsBlocked(RuntimeError):
    """Подозрительных фрагментов слишком много — документ уходит человеку."""


@dataclass
class RagPipelineResult:
    draft: CardDraft
    attempts: int
    verdict: str
    context: DocumentContext
    guard_report: dict


@dataclass
class GuardedContext:
    context: DocumentContext
    report: dict

    def to_json(self) -> str:
        return json.dumps(
            {
                "context": json.loads(self.context.to_json()),
                "report": self.report,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str) -> "GuardedContext":
        data = json.loads(raw)
        return cls(
            context=DocumentContext.from_json(json.dumps(data["context"])),
            report=data["report"],
        )


async def retrieve_and_guard(
    document_ids: list[str], hint: str | None = None
) -> GuardedContext:
    """Поиск, проверка на инъекции и сборка контекста с маскированием PII.

    Порядок рубежей: сначала дешёвые правила инъекций (модель — только по
    помеченным фрагментам), затем маскирование PII при сборке контекста.
    Исходные контакты не попадают ни в промпт, ни в лог, ни в историю процесса.
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
    if not rows:
        raise NoContextError(
            "по выбранным документам не нашлось ни одного фрагмента для контекста"
        )

    clean: list[dict] = []
    excluded: list[dict] = []
    for chunk in rows:
        verdict = await injection.detect(chunk.get("text") or "")
        if verdict.suspicious:
            excluded.append(
                {
                    "chunk_id": str(chunk["id"]),
                    "document": chunk.get("filename"),
                    "page": chunk.get("page"),
                    "reasons": verdict.reasons,
                }
            )
            continue
        clean.append(chunk)

    context = build_context(clean)
    threshold = settings.injection_max_suspicious
    blocked = len(excluded) >= threshold or (bool(excluded) and not context.sources)

    if blocked:
        reason = (
            "все найденные фрагменты исключены как подозрительные"
            if not context.sources
            else f"исключено подозрительных фрагментов: {len(excluded)} "
            f"(порог {threshold})"
        )
    elif excluded:
        reason = f"исключено подозрительных фрагментов: {len(excluded)}"
    else:
        reason = ""

    report = {
        "masked": context.masked,
        "excluded": excluded,
        "threshold": threshold,
        "blocked": blocked,
        "reason": reason,
    }
    return GuardedContext(context=context, report=report)


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
    guarded = await retrieve_and_guard(document_ids, hint)
    if guarded.report["blocked"]:
        raise GuardrailsBlocked(guarded.report["reason"])
    context = guarded.context
    feedback: list[str] = []
    draft: CardDraft | None = None
    verdict = "rejected"
    attempts = 0

    for attempt in range(1, max_attempts + 1):
        attempts = attempt
        draft = await generate_card(context, hint, feedback or None)

        citation_errors = verify_citations(draft, context)
        output_errors = check_output(draft)
        if citation_errors or output_errors:
            feedback = citation_errors + output_errors
            log.info(
                "generation_rejected",
                attempt=attempt,
                citation_errors=citation_errors,
                output_errors=output_errors,
            )
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
        draft=draft,
        attempts=attempts,
        verdict=verdict,
        context=context,
        guard_report=guarded.report,
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


def card_text(card: CardDraft) -> str:
    """Весь человекочитаемый текст карточки — для фильтра выхода."""
    parts = [card.title, card.description]
    parts.extend(card.characteristics.keys())
    parts.extend(card.characteristics.values())
    parts.extend(card.benefits)
    parts.extend(card.missing_fields)
    parts.extend([card.seo.title, card.seo.description, *card.seo.keywords])
    return "\n".join(parts)


def check_output(card: CardDraft) -> list[str]:
    """Фильтр выхода: не просочились ли контакты и следы инструкций."""
    text = card_text(card)
    errors: list[str] = []

    masked = pii.mask(text)
    for kind, count in masked.counts.items():
        errors.append(f"в карточке остались персональные данные: {kind} ({count})")

    reasons = injection.rule_check(text)
    if reasons:
        errors.append("в карточке следы служебных инструкций: " + "; ".join(reasons))
    return errors


def sanitize_card(card: CardDraft) -> CardDraft:
    """Точка страховки: в сохранённой карточке не должно быть исходных PII."""
    data = card.model_dump()
    data["title"] = pii.mask(data["title"]).text[:TITLE_MAX_LENGTH]
    data["description"] = pii.mask(data["description"]).text
    data["characteristics"] = {
        pii.mask(name).text: pii.mask(value).text
        for name, value in data["characteristics"].items()
    }
    data["benefits"] = [pii.mask(item).text for item in data["benefits"]]
    data["missing_fields"] = [pii.mask(item).text for item in data["missing_fields"]]
    data["seo"] = {
        "title": pii.mask(data["seo"]["title"]).text[:TITLE_MAX_LENGTH],
        "description": pii.mask(data["seo"]["description"]).text,
        "keywords": [pii.mask(item).text for item in data["seo"].get("keywords", [])],
    }
    return CardDraft.model_validate(data)
