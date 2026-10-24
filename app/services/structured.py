"""Структурированный ответ модели: разбор, валидация, лечение.

Публичный контракт: ``validate_or_retry``, ``regenerate_field``,
``confidence_gate`` и ``CardValidationError``. Внутри — тот же путь:
разбор → Pydantic → возврат ошибки модели → повтор, с ограничением попыток.
"""

from pydantic import BaseModel, ValidationError

from app.agents.prompts import generator_agent
from app.core.config import settings
from app.core.logging import get_logger
from app.llm.client import run_agent
from app.schemas import CardDraft
from app.services.json_utils import LLMJsonError, parse_llm_json

log = get_logger(__name__)


class StructuredOutputError(RuntimeError):
    """Модель так и не вернула валидный ответ по схеме."""

    def __init__(self, message: str, *, fields: set[str] | None = None) -> None:
        super().__init__(message)
        self.fields = fields or set()


class CardValidationError(StructuredOutputError):
    """Карточка не прошла валидацию за отведённое число попыток."""


async def validate_or_retry(prompt: str, *, max_attempts: int = 3) -> CardDraft:
    """Получить валидную карточку: ошибка возвращается модели, попытки ограничены."""
    current_prompt = prompt
    last_error = "модель не вернула ответ"

    for attempt in range(1, max_attempts + 1):
        raw = await run_agent(generator_agent, current_prompt)
        try:
            data = parse_llm_json(raw)
            return CardDraft.model_validate(data)
        except LLMJsonError as exc:
            last_error = f"ответ не является JSON: {exc}"
        except ValidationError as exc:
            last_error = _format_validation_error(exc)

        log.warning("card_validation_retry", attempt=attempt, error=last_error)
        if attempt < max_attempts:
            current_prompt = (
                prompt
                + "\n\nПредыдущий ответ не прошёл проверку: "
                + last_error
                + "\nИсправь ошибку и верни ТОЛЬКО валидный JSON по схеме."
            )

    raise CardValidationError(
        f"карточка не прошла валидацию за {max_attempts} попытки: {last_error}"
    )


async def regenerate_field(card: CardDraft, field: str, error: str) -> CardDraft:
    """Переделать одно поле, не трогая остальные."""
    prompt = (
        "Текущий черновик карточки (JSON):\n"
        + card.model_dump_json(indent=2)
        + f"\n\nПоле «{field}» не прошло проверку: {error}."
        + f"\nИсправь ТОЛЬКО поле «{field}», остальные значения оставь без изменений."
        + "\nВерни ТОЛЬКО валидный JSON по схеме."
    )
    raw = await run_agent(generator_agent, prompt)
    try:
        data = parse_llm_json(raw)
        fixed = CardDraft.model_validate(data)
    except (LLMJsonError, ValidationError) as exc:
        raise CardValidationError(f"не удалось переделать поле {field}: {exc}") from exc

    merged = card.model_dump()
    merged[field] = getattr(fixed, field)
    return CardDraft.model_validate(merged)


def confidence_gate(card: CardDraft) -> str:
    """«done» или «needs_review» по порогу уверенности из настроек."""
    if card.confidence < settings.confidence_threshold:
        return "needs_review"
    return "done"


async def call_structured(
    agent,
    prompt: str,
    model_cls: type[BaseModel],
    *,
    max_attempts: int | None = None,
    aux: bool = False,
) -> BaseModel:
    """Общий вызов со схемой для служебных ролей (детектор, судья)."""
    attempts = max_attempts or settings.llm_structured_attempts
    current_prompt = prompt
    last_error = "модель не вернула ответ"

    for attempt in range(1, attempts + 1):
        raw = await run_agent(agent, current_prompt, role=agent.name, aux=aux)
        try:
            data = parse_llm_json(raw)
            return model_cls.model_validate(data)
        except LLMJsonError as exc:
            last_error = f"ответ не является JSON: {exc}"
        except ValidationError as exc:
            last_error = _format_validation_error(exc)

        log.warning("structured_retry", agent=agent.name, attempt=attempt, error=last_error)
        if attempt < attempts:
            current_prompt = (
                prompt
                + "\n\nПредыдущий ответ не прошёл проверку: "
                + last_error
                + "\nИсправь ошибку и верни ТОЛЬКО валидный JSON по схеме."
            )

    raise StructuredOutputError(
        f"не удалось получить валидный ответ за {attempts} попытки: {last_error}"
    )


def _format_validation_error(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        location = ".".join(str(p) for p in error["loc"]) or "ответ"
        message = error["msg"]
        context = error.get("ctx") or {}
        if "max_length" in context:
            message = f"{message} (максимум {context['max_length']})"
        parts.append(f"{location}: {message}")
    return "; ".join(parts)
