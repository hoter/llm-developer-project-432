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
