"""Модели данных карточки и служебных вердиктов."""
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

TITLE_MAX_LENGTH = 60
SEO_TITLE_MAX_LENGTH = 60
SEO_DESCRIPTION_MAX_LENGTH = 160


class SourceRef(BaseModel):
    """Ссылка на фрагмент документа.

    ``field`` — необязательная привязка к полю карточки для RAG-пайплайна;
    обязательными остаются только существование фрагмента и присутствие в
    поданном контексте.
    """

    chunk_id: str = Field(min_length=1, description="Идентификатор фрагмента")
    doc_id: str = Field(default="", description="Документ-источник")
    page: int | None = Field(default=None, description="Страница фрагмента")
    score: float | None = Field(default=None, description="Оценка релевантности")
    field: str = Field(default="", description="Поле карточки, если известно")


class Seo(BaseModel):
    """SEO-поля карточки."""

    title: str = Field(default="", max_length=SEO_TITLE_MAX_LENGTH)
    description: str = Field(default="", max_length=SEO_DESCRIPTION_MAX_LENGTH)
    keywords: list[str] = Field(default_factory=list)


# Прежнее имя модуля; оставлено для совместимости импортов.
SeoBlock = Seo


class SupplierFacts(BaseModel):
    """Результат extractor-агента: факты из текста поставщика."""

    product_name: str = Field(min_length=1, description="Название товара")
    characteristics: dict[str, str] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)


class CardDraft(BaseModel):
    """Черновик карточки товара — контракт результата генерации."""

    title: str = Field(
        min_length=1,
        max_length=TITLE_MAX_LENGTH,
        description=f"Заголовок карточки, не длиннее {TITLE_MAX_LENGTH} символов",
    )
    description: str = Field(default="", description="Описание на 3-4 предложения")
    characteristics: dict[str, str] = Field(default_factory=dict)
    benefits: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    seo: Seo = Field(default_factory=Seo)
    sources: list[SourceRef] = Field(default_factory=list)

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
        if not isinstance(value, dict):
            return value
        return {k: v for k, v in value.items() if isinstance(v, str) and v.strip()}

    @model_validator(mode="after")
    def _no_field_in_two_lists(self) -> "CardDraft":
        overlap = set(self.characteristics) & set(self.missing_fields)
        if overlap:
            raise ValueError(
                "поля не могут быть одновременно в characteristics и missing_fields: "
                + ", ".join(sorted(overlap))
            )
        return self


class CritiqueReport(BaseModel):
    """Вердикт критика."""

    verdict: Literal["approve", "regenerate"] = Field(
        description="approve — карточка годится; regenerate — переделать"
    )
    issues: list[str] = Field(default_factory=list)


class JudgeVerdict(BaseModel):
    """Вердикт модели-судьи."""

    supported: bool = Field(description="Все утверждения подтверждены источниками")
    unsupported_claims: list[str] = Field(default_factory=list)


class InjectionVerdict(BaseModel):
    """Вердикт точного детектора инъекций."""

    suspicious: bool = Field(description="Фрагмент пытается управлять моделью")
    reason: str = Field(default="")
