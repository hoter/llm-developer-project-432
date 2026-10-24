"""LLM-клиент как слой: обёртка над OpenAI Agents SDK с таймаутом и ретраями.

Единственное место в приложении, которое знает про LLM API:
retry-политика, таймаут, различие ошибок 429/5xx/4xx — всё здесь.
Сервисы вызывают run_agent() и не знают про провайдера.
"""
import asyncio
import random
import time

from agents import (
    Agent,
    Runner,
    set_default_openai_api,
    set_default_openai_client,
    set_tracing_disabled,
)
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from structlog.contextvars import get_contextvars

from app.core import db
from app.core.config import settings
from app.core.logging import get_logger
from app.llm.cost import cost_micros_for
from app.repositories import llm_calls as llm_calls_repo

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


async def run_agent(agent: Agent, prompt: str, *, role: str | None = None, aux: bool = False):
    """Запустить агента с ретраями и учётом стоимости.

    Ретраится только вызов LLM — не вся бизнес-задача (это работа движка).
    ``aux=True`` — служебный вызов на дешёвой модели (критик, судья,
    классификация): сильная модель нужна только основной генерации.

    Учёт пишется здесь, на границе провайдера: вызывающий код не может
    забыть записать расход. Задача и запрос берутся из контекста логов —
    их привязывает обработчик и воркер.
    """
    setup_llm()
    model = settings.llm_aux_model if aux else settings.llm_model
    if getattr(agent, "model", None) is not None and agent.model != model and hasattr(agent, "clone"):
        agent = agent.clone(model=model)

    started = time.monotonic()
    max_retries = settings.llm_max_retries
    for attempt in range(1, max_retries + 1):
        try:
            result = await asyncio.wait_for(
                Runner.run(agent, prompt), timeout=settings.llm_timeout_s
            )
            _record_call(
                role=role or agent.name,
                model=model,
                result=result,
                duration_ms=int((time.monotonic() - started) * 1000),
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


def _usage(result) -> tuple[int, int] | None:
    """Расход токенов из ответа модели: сумма по всем шагам."""
    responses = getattr(result, "raw_responses", None)
    if not responses:
        return None
    input_tokens = 0
    output_tokens = 0
    for response in responses:
        usage = getattr(response, "usage", None)
        if usage is None:
            continue
        input_tokens += getattr(usage, "input_tokens", 0) or 0
        output_tokens += getattr(usage, "output_tokens", 0) or 0
    return input_tokens, output_tokens


def _record_call(*, role: str, model: str, result, duration_ms: int) -> None:
    """Записать вызов в журнал. Сбой учёта не должен ломать генерацию."""
    usage = _usage(result)
    if usage is None:
        return
    input_tokens, output_tokens = usage
    context = get_contextvars()
    log.info(
        "llm_call",
        model=model,
        role=role,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=duration_ms,
    )
    try:
        with db.connection() as conn:
            llm_calls_repo.record_call(
                conn,
                job_id=context.get("job_id"),
                request_id=context.get("request_id"),
                model=model,
                role=role,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_micros=cost_micros_for(model, input_tokens, output_tokens),
                duration_ms=duration_ms,
            )
    except Exception as exc:
        log.warning("llm_call_not_recorded", error=repr(exc))
