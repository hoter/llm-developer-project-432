"""Промпт как код: три агента кард-пайплайна — extractor, generator, critic.

Схема ответа не пишется руками: она генерируется из Pydantic-модели и
дублируется в инструкции текстом. LM Studio (chat completions) строгий
json_schema-режим не поддерживает, поэтому принудить модель к форме на её
стороне нельзя — форму проверяет приложение (app/services/structured.py).

Поэтому у агентов нет output_type: SDK не парсит и не валидирует ответ за
нас, наружу идёт сырая строка, и весь путь «разбор → валидация → лечение»
принадлежит приложению.
"""
import json

from agents import Agent, ModelSettings

from app.core.config import settings
from app.schemas import CardDraft, CritiqueReport, SupplierFacts

_MODEL = settings.llm_model

# Reasoning-модели (gemma-4 и т.п.) тратят токены на «размышления» до ответа:
# без запаса max_tokens бюджет кончается раньше content, и LM Studio
# обрывает stream по таймауту. 4096 хватает на размышления + JSON-ответ.
_MODEL_SETTINGS = ModelSettings(max_tokens=4096, temperature=0.4)


def _schema_text(model) -> str:
    """JSON-схема модели — то, что мы передаём модели текстом."""
    return json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2)


extractor_agent = Agent(
    name="Extractor",
    instructions=(
        "Ты — извлекатель фактов. Из текста поставщика выдели структурированные факты.\n"
        "Правила:\n"
        "1. Бери ТОЛЬКО то, что явно написано в тексте. Ничего не выдумывай.\n"
        "2. Чего в тексте нет — положи имя поля в missing_fields "
        "(например: гарантия, цвет, страна-производитель).\n"
        "3. Никакого markdown и пояснений: только валидный JSON.\n\n"
        "Схема ответа:\n" + _schema_text(SupplierFacts)
    ),
    model=_MODEL,
    model_settings=_MODEL_SETTINGS,
)

generator_agent = Agent(
    name="Generator",
    instructions=(
        "Ты — копирайтер маркетплейса. Из фактов о товаре сделай черновик карточки.\n"
        "Правила:\n"
        "1. Используй только предоставленные факты. Если данных нет — не выдумывай: "
        "имя поля должно быть в missing_fields, значение — не появляться в characteristics.\n"
        "2. title короче 60 символов; description — 3-4 предложения без воды.\n"
        "3. Поле не может быть одновременно в characteristics и в missing_fields.\n"
        "4. characteristics — только пары ключ-значение, без пустых значений.\n"
        "5. confidence — честная уверенность от 0 до 1: мало данных — низкая.\n"
        "6. seo — вложенный объект: title, description, keywords.\n"
        "7. sources оставь пустым списком.\n"
        "8. Если есть замечания критика (feedback) — учти их.\n"
        "Никакого markdown и пояснений: только валидный JSON.\n\n"
        "Схема ответа:\n" + _schema_text(CardDraft)
    ),
    model=_MODEL,
    model_settings=_MODEL_SETTINGS,
)

critic_agent = Agent(
    name="Critic",
    instructions=(
        "Ты — строгий редактор карточек маркетплейса. Проверь черновик по правилам:\n"
        "1. title не длиннее 60 символов\n"
        "2. Нет характеристик, которых нет в фактах (выдуманные)\n"
        "3. description и benefits не пустые\n"
        "4. Нет воды («высокое качество», «лучшая цена») без конкретики\n"
        "5. Нет поля одновременно в characteristics и missing_fields\n"
        "Верни СТРОГО JSON:\n"
        '- verdict (string): "approve" если всё ок, иначе "regenerate"\n'
        "- issues (array of string): список проблем; при approve — пустой\n"
        "Никакого markdown, только валидный JSON.\n\n"
        "Схема ответа:\n" + _schema_text(CritiqueReport)
    ),
    model=_MODEL,
    model_settings=_MODEL_SETTINGS,
)
