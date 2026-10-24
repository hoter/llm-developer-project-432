"""Модель-судья: промпт с фрагментами и разбор структурированного вердикта."""
import asyncio
import json

from app.rag.context import ContextSource, DocumentContext
from app.schemas import CardDraft, Citation
from app.services import structured
from evals import judge


def _card() -> CardDraft:
    return CardDraft(
        title="Блендер 800 Вт",
        description="Погружной блендер.",
        characteristics={"Мощность": "800 Вт"},
        benefits=[],
        missing_fields=[],
        confidence=0.8,
        seo={"title": "Блендер", "description": "Блендер 800 Вт", "keywords": []},
        sources=[Citation(field="characteristics.Мощность", chunk_id="42")],
    )


def _context() -> DocumentContext:
    return DocumentContext(
        text="[S1]\nдокумент: blender_passport.pdf\nтекст: Мощность 800 Вт",
        sources=[
            ContextSource(
                source_id="S1",
                chunk_id="42",
                text="Мощность 800 Вт",
                filename="blender_passport.pdf",
                page=1,
                section="ПАСПОРТ ИЗДЕЛИЯ",
            )
        ],
    )


def test_judge_prompt_contains_fragments_and_card():
    prompt = judge.build_judge_prompt(_card(), _context())

    assert "[S1]" in prompt
    assert "Мощность 800 Вт" in prompt
    assert "Блендер 800 Вт" in prompt
    assert "unsupported_claims" in prompt


def test_judge_card_parses_structured_verdict(monkeypatch):
    prompts: list[str] = []

    async def fake_run(agent, prompt, *, role=None, aux=False):
        prompts.append(prompt)
        assert aux is True  # судья — служебный вызов на дешёвой модели
        return json.dumps(
            {
                "supported": False,
                "unsupported_claims": ["Гарантия 24 месяца не подтверждена"],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(structured, "run_agent", fake_run)

    verdict = asyncio.run(judge.judge_card(_card(), _context()))

    assert verdict.supported is False
    assert verdict.unsupported_claims == ["Гарантия 24 месяца не подтверждена"]
    assert "Карточка для проверки" in prompts[0]
