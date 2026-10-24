"""Модель в роли судьи: подтверждены ли утверждения карточки источниками.

Приём спорный: судья — та же модель, что и генератор, и его число — оценка,
а не истина. Тренд по нему виден, абсолютной верой его принимать нельзя.
"""
from app.agents.prompts import judge_agent
from app.rag.context import DocumentContext
from app.schemas import CardDraft, JudgeVerdict
from app.services.structured import call_structured


def build_judge_prompt(card: CardDraft, context: DocumentContext) -> str:
    return (
        context.text
        + "\n\nКарточка для проверки:\n"
        + card.model_dump_json(indent=2)
        + "\n\nПроверь каждое утверждение карточки по фрагменту, на который оно "
        "ссылается. supported=false, если хотя бы одно утверждение не подтверждено; "
        "перечисли такие утверждения в unsupported_claims."
    )


async def judge_card(card: CardDraft, context: DocumentContext) -> JudgeVerdict:
    """Спросить модель-судью. Служебный вызов — на дешёвой модели."""
    verdict = await call_structured(
        judge_agent,
        build_judge_prompt(card, context),
        JudgeVerdict,
        aux=True,
    )
    return verdict
