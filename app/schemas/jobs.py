"""Модели задач: вход асинхронного и синхронного обработчиков, ответ статуса."""
from pydantic import BaseModel, Field

from app.schemas.cards import CardDraft


class JobIn(BaseModel):
    supplier_text: str = Field(min_length=1, description="Текст поставщика")


class JobOut(BaseModel):
    id: str
    status: str
    attempts: int
    result: CardDraft | None = None
    error: str | None = None
    guard_report: dict | None = None


class DocumentOut(BaseModel):
    id: str
    filename: str
    status: str
    chunks_count: int
    error: str | None = None


class GenerateIn(BaseModel):
    """Запрос сквозной генерации: выбранные документы + подсказка."""

    document_ids: list[str] = Field(min_length=1, description="Документы поставщика")
    hint: str | None = Field(default=None, description="Что это за товар")
