"""Судья: промпт с контекстом и разбор вердикта."""
import asyncio
import json

from app.schemas import CardDraft
from app.services import structured
from evals import judge


def _card() -> CardDraft:
    return CardDraft(
        title="Блендер 800 Вт",
        description="Погружной блендер.",
        characteristics={"Мощность": "800 Вт"},
        sources=[{"chunk_id": "c1"}],
    )


def test_prompt_contains_context_and_card():
    prompt = judge.build_judge_prompt(_card(), "[c1 | f.pdf]\nМощность 800 Вт")
    assert "[c1" in prompt
    assert "Блендер 800 Вт" in prompt
    assert "unsupported_claims" in prompt


def test_judge_parses_verdict(monkeypatch):
    async def fake_run(agent, prompt, **kwargs):
        assert kwargs.get("aux") is True
        return json.dumps({"supported": False, "unsupported_claims": ["гарантия"]})

    monkeypatch.setattr(structured, "run_agent", fake_run)

    verdict = asyncio.run(judge.judge_card(_card(), "контекст"))
    assert verdict.supported is False
    assert verdict.unsupported_claims == ["гарантия"]
