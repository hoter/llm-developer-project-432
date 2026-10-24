"""Структурированный ответ модели: разбор → валидация → лечение.

«Сгенерируй JSON» — не контракт. Здесь три уровня надёжности:

1. разбор переживает markdown-заборы и текст вокруг (json_utils);
2. валидация идёт по Pydantic-схеме — той же, что уходит модели;
3. невалидный ответ не выбрасывается: он возвращается модели вместе с
   текстом ошибки, а число попыток ограничено.

Отдельный приём — точечная переделка: если сломалось одно поле, модель
получает текущий черновик и просьбу исправить только его. Это дешевле,
чем заново генерировать всю карточку.
"""
import json

from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.logging import get_logger
from app.llm.client import run_agent
from app.services.json_utils import JsonParseError, extract_json, parse_json

log = get_logger(__name__)


class StructuredOutputError(RuntimeError):
    """Модель так и не вернула валидный ответ по схеме."""

    def __init__(self, message: str, *, fields: set[str] | None = None) -> None:
        super().__init__(message)
        self.fields = fields or set()


def parse_and_validate(raw, model_cls: type[BaseModel]) -> BaseModel:
    """Разобрать сырой ответ и провалидировать его по схеме."""
    snippet = extract_json(raw)
    try:
        return model_cls.model_validate_json(snippet)
    except ValidationError as exc:
        raise StructuredOutputError(
            _format_validation_error(exc), fields=_error_fields(exc)
        ) from exc


async def call_structured(
    agent,
    prompt: str,
    model_cls: type[BaseModel],
    *,
    max_attempts: int | None = None,
    aux: bool = False,
) -> BaseModel:
    """Вызвать модель и добиться валидного ответа, возвращая ей ошибку.

    Первая неудачная валидация одного поля лечится точечно: модель получает
    текущий черновик и просьбу исправить только это поле. Всё остальное —
    обычный повтор с текстом ошибки в промпте.
    """
    attempts = max_attempts or settings.llm_structured_attempts
    current_prompt = prompt
    last_error = "модель не вернула ответ"

    for attempt in range(1, attempts + 1):
        raw = await run_agent(agent, current_prompt, role=agent.name, aux=aux)
        try:
            return parse_and_validate(raw, model_cls)
        except JsonParseError as exc:
            last_error = f"ответ не является JSON: {exc}"
        except StructuredOutputError as exc:
            last_error = str(exc)
            if attempt == 1 and len(exc.fields) == 1:
                field = next(iter(exc.fields))
                repaired = await _repair_field(
                    agent, raw, model_cls, field, last_error, aux=aux
                )
                if repaired is not None:
                    log.info("structured_targeted_repair", agent=agent.name, field=field)
                    return repaired

        log.warning(
            "structured_retry",
            agent=agent.name,
            attempt=attempt,
            error=last_error,
        )
        if attempt < attempts:
            current_prompt = _heal_prompt(prompt, last_error)

    raise StructuredOutputError(
        f"не удалось получить валидный ответ за {attempts} попытки: {last_error}"
    )


async def _repair_field(
    agent,
    raw,
    model_cls: type[BaseModel],
    field: str,
    error: str,
    *,
    aux: bool = False,
) -> BaseModel | None:
    """Попросить модель исправить одно поле, остальное оставить как есть."""
    try:
        current = parse_json(raw)
    except JsonParseError:
        return None
    if not isinstance(current, dict) or field not in current:
        return None

    prompt = (
        "Текущий черновик (JSON):\n"
        + json.dumps(current, ensure_ascii=False, indent=2)
        + f"\n\nПоле '{field}' не прошло проверку: {error}."
        + f"\nИсправь ТОЛЬКО поле '{field}', остальные значения оставь без изменений."
        + "\nВерни ТОЛЬКО валидный JSON по схеме, без markdown и пояснений."
    )
    raw_fixed = await run_agent(agent, prompt, role=agent.name, aux=aux)
    try:
        fixed = parse_json(raw_fixed)
    except JsonParseError:
        return None
    if not isinstance(fixed, dict) or field not in fixed:
        return None

    merged = {**current, field: fixed[field]}
    try:
        return model_cls.model_validate(merged)
    except ValidationError:
        return None


def _heal_prompt(prompt: str, error: str) -> str:
    return (
        prompt
        + "\n\nПредыдущий ответ не прошёл проверку: "
        + error
        + "\nИсправь ошибку и верни ТОЛЬКО валидный JSON по схеме."
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


def _error_fields(exc: ValidationError) -> set[str]:
    return {
        str(error["loc"][0])
        for error in exc.errors()
        if error.get("loc")
    }
