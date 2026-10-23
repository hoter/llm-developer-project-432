"""LLM-клиент как слой: обёртка над OpenAI Agents SDK с таймаутом и ретраями.

Единственное место в приложении, которое знает про LLM API:
retry-политика, таймаут, различие ошибок 429/5xx/4xx — всё здесь.
Сервисы вызывают run_agent() и не знают про провайдера.
"""
import asyncio
import random

from agents import (
    Agent,
    Runner,
    set_default_openai_api,
    set_default_openai_client,
    set_tracing_disabled,
)
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_client_configured = False


def setup_llm() -> None:
    """Инициализация OpenAI-compatible клиента (LM Studio / OpenRouter / Z.ai).

    Вызывается один раз на процесс. Идемпотентна.
    """
    global _client_configured
    if _client_configured:
        return
    client = AsyncOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout_s,
    )
    set_default_openai_client(client)
    # LM Studio / Ollama / OpenRouter говорят на Chat Completions, а не Responses API.
    set_default_openai_api("chat_completions")
    # Иначе SDK шлёт спаны на api.openai.com и падает с 401 на не-OpenAI ключе.
    set_tracing_disabled(True)
    _client_configured = True


def _retryable(exc: Exception) -> bool:
    """Ретраим только транспортные и серверные ошибки: 429, 5xx, таймаут, сеть.

    4xx (кроме 429) — ошибка запроса, повтор бессмыслен.
    """
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


async def run_agent(agent: Agent, prompt: str):
    """Запустить агента с ретраями: экспоненциальная задержка + jitter.

    Ретраится только вызов LLM — не вся бизнес-задача (это работа очереди/workflow).
    """
    setup_llm()
    max_retries = settings.llm_max_retries
    for attempt in range(1, max_retries + 1):
        try:
            result = await asyncio.wait_for(
                Runner.run(agent, prompt), timeout=settings.llm_timeout_s
            )
            return result.final_output
        except Exception as exc:
            if attempt == max_retries or not _retryable(exc):
                log.error(
                    "llm_call_failed",
                    agent=agent.name,
                    attempt=attempt,
                    error=repr(exc),
                )
                raise
            delay = min(2**attempt * 0.5, 8.0) * (1 + random.random() * 0.25)
            log.warning(
                "llm_call_retry",
                agent=agent.name,
                attempt=attempt,
                delay_s=round(delay, 2),
                error=repr(exc),
            )
            await asyncio.sleep(delay)
