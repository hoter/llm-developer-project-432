"""Модель в роли судьи: подтверждены ли утверждения карточки источниками."""
from app.agents.prompts import judge_agent
from app.schemas import CardDraft, JudgeVerdict
from app.services.structured import call_structured


def build_judge_prompt(card: CardDraft, context: str) -> str:
    return (
        context
        + "\n\nКарточка для проверки:\n"
        + card.model_dump_json(indent=2)
        + "\n\nПроверь каждое утверждение карточки по фрагменту, на который оно "
        "ссылается. supported=false, если хотя бы одно утверждение не подтверждено; "
        "перечисли такие утверждения в unsupported_claims."
    )


async def judge_card(card: CardDraft, context: str) -> JudgeVerdict:
    return await call_structured(
        judge_agent, build_judge_prompt(card, context), JudgeVerdict, aux=True
    )
