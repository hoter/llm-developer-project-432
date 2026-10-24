"""Пайплайн с подменённым клиентом модели; без сети и модели."""
import asyncio

import pytest

from app.llm import client as llm_client
from app.schemas import CardDraft, CritiqueReport, SupplierFacts
from app.services import pipeline, structured


def _facts() -> SupplierFacts:
    return SupplierFacts(product_name="Блендер", characteristics={"Мощность": "800 Вт"})


def _draft() -> CardDraft:
    return CardDraft(title="Блендер 800 Вт", description="Погружной блендер.")


@pytest.fixture
def fake_llm(monkeypatch):
    calls = {"n": 0}
    scenario: list = []

    async def fake_run(agent, prompt):
        result = scenario[calls["n"]]
        calls["n"] += 1
        if isinstance(result, Exception):
            raise result
        return result if isinstance(result, str) else result.model_dump_json()

    monkeypatch.setattr(pipeline, "run_agent", fake_run)
    monkeypatch.setattr(structured, "run_agent", fake_run)
    return {"scenario": scenario, "calls": calls}


def test_extract_parses_fenced_json(fake_llm):
    fake_llm["scenario"].append("```json\n" + _facts().model_dump_json() + "\n```")
    facts = asyncio.run(pipeline.extract("текст"))
    assert facts.characteristics["Мощность"] == "800 Вт"


def test_pipeline_approved(fake_llm):
    fake_llm["scenario"] += [_facts(), _draft(), CritiqueReport(verdict="approve")]
    draft, attempts, verdict, status = asyncio.run(pipeline.run_pipeline("текст"))
    assert (verdict, status, attempts) == ("approved", "done", 1)
    assert draft.title == "Блендер 800 Вт"


def test_pipeline_rejected_after_max_attempts(fake_llm):
    fake_llm["scenario"] += [
        _facts(),
        _draft(), CritiqueReport(verdict="regenerate", issues=["плохо"]),
        _draft(), CritiqueReport(verdict="regenerate", issues=["плохо"]),
        _draft(), CritiqueReport(verdict="regenerate", issues=["плохо"]),
    ]
    _draft_out, attempts, verdict, status = asyncio.run(pipeline.run_pipeline("текст"))
    assert (attempts, verdict, status) == (3, "rejected", "rejected")


def test_run_agent_no_retry_on_4xx(monkeypatch):
    from openai import APIStatusError

    err = APIStatusError.__new__(APIStatusError)
    err.status_code = 400

    class FakeRunner:
        @staticmethod
        async def run(agent, prompt):
            raise err

    class FakeAgent:
        name = "test"

    monkeypatch.setattr(llm_client, "setup_llm", lambda: None)
    monkeypatch.setattr(llm_client, "Runner", FakeRunner)

    with pytest.raises(APIStatusError):
        asyncio.run(llm_client.run_agent(FakeAgent(), "x"))
