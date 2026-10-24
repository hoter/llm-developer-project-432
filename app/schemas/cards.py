"""Модели данных карточки: контракт, на который опирается приложение.

Ограничения живут здесь, а не в промпте: промпт можно не выполнить, схему —
нельзя. Всё, что пришло от модели, проходит через эти валидаторы до того,
как попадёт в базу или в ответ API.
"""
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

TITLE_MAX_LENGTH = 60
SEO_TITLE_MAX_LENGTH = 60
SEO_DESCRIPTION_MAX_LENGTH = 160


class Citation(BaseModel):
    """Ссылка на фрагмент контекста, откуда взято утверждение.

    ``chunk_id`` — идентификатор фрагмента из поданного контекста. Модель
    видит короткие метки [S1], [S2]; приложение подменяет их на настоящие
    id фрагментов и проверяет, что фрагмент существует и был в контексте.
    """

    field: str = Field(
        min_length=1,
        description="Поле карточки: title, description или characteristics.<имя>",
    )
    chunk_id: str = Field(
        min_length=1, description="Идентификатор фрагмента из контекста"
    )


class SeoBlock(BaseModel):
    """SEO-поля карточки: живут вложенным объектом."""

    title: str = Field(min_length=1, max_length=SEO_TITLE_MAX_LENGTH)
    description: str = Field(min_length=1, max_length=SEO_DESCRIPTION_MAX_LENGTH)
    keywords: list[str] = Field(default_factory=list)


class SupplierFacts(BaseModel):
    """Результат extractor-агента: структурированные факты из текста поставщика."""

    product_name: str = Field(min_length=1, description="Название товара из текста поставщика")
    characteristics: dict[str, str] = Field(
        default_factory=dict, description="Характеристики: ключ-значение, только из текста"
    )
    missing_fields: list[str] = Field(
        default_factory=list,
        description="Что не найдено в тексте (например: гарантия, цвет)",
    )


class CardDraft(BaseModel):
    """Черновик карточки товара — контракт результата генерации."""

    title: str = Field(
        min_length=1,
        max_length=TITLE_MAX_LENGTH,
        description=f"Заголовок карточки, не длиннее {TITLE_MAX_LENGTH} символов",
    )
    description: str = Field(min_length=1, description="Описание на 3-4 предложения")
    characteristics: dict[str, str] = Field(
        default_factory=dict,
        description="Характеристики: ключ-значение; пустые значения отбрасываются",
    )
    benefits: list[str] = Field(default_factory=list, description="3-5 преимуществ")
    missing_fields: list[str] = Field(
        default_factory=list,
        description="Что не найдено в документах: вместо выдуманного значения",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Уверенность в карточке от 0 до 1; ниже порога — нужен человек",
    )
    seo: SeoBlock
    sources: list[Citation] = Field(
        default_factory=list,
        description="Ссылки: какое поле карточки из какого фрагмента взято",
    )

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("заголовок не может быть пустым")
        return value

    @field_validator("characteristics", mode="before")
    @classmethod
    def _drop_empty_characteristics(cls, value):
        """Характеристика с пустым значением в карточку не попадает."""
        if not isinstance(value, dict):
            return value
        return {k: v for k, v in value.items() if isinstance(v, str) and v.strip()}

    @model_validator(mode="after")
    def _no_field_in_two_lists(self) -> "CardDraft":
        """Поле не может быть одновременно характеристикой и недостающим."""
        overlap = set(self.characteristics) & set(self.missing_fields)
        if overlap:
            raise ValueError(
                "поля не могут быть одновременно в characteristics и missing_fields: "
                + ", ".join(sorted(overlap))
            )
        return self


class CritiqueReport(BaseModel):
    """Результат critic-агента: вердикт и список проблем."""

    verdict: Literal["approve", "regenerate"] = Field(
        description="approve — карточка годится; regenerate — переделать"
    )
    issues: list[str] = Field(
        default_factory=list,
        description="Список проблем: заголовок длиннее 60 символов, "
        "выдуманные характеристики, пустые поля и т.п.",
    )
