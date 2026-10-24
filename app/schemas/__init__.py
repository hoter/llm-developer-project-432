"""Контракты приложения.

`app.schemas` — пакет: карточка и её части в cards.py, задачи в jobs.py.
Реэкспорт оставлен, чтобы код мог писать `from app.schemas import CardDraft`.
"""
from app.schemas.cards import (
    SEO_DESCRIPTION_MAX_LENGTH,
    SEO_TITLE_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    CardDraft,
    Citation,
    CritiqueReport,
    SeoBlock,
    SupplierFacts,
)
from app.schemas.jobs import DocumentOut, GenerateIn, JobIn, JobOut

__all__ = [
    "SEO_DESCRIPTION_MAX_LENGTH",
    "SEO_TITLE_MAX_LENGTH",
    "TITLE_MAX_LENGTH",
    "CardDraft",
    "Citation",
    "CritiqueReport",
    "DocumentOut",
    "GenerateIn",
    "JobIn",
    "JobOut",
    "SeoBlock",
    "SupplierFacts",
]
