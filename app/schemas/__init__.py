"""Контракты приложения.

`app.schemas` — пакет: карточка и её части в cards.py, задачи в jobs.py.
Реэкспорт оставлен, чтобы код мог писать `from app.schemas import CardDraft`.
"""
from app.schemas.cards import (
    SEO_DESCRIPTION_MAX_LENGTH,
    SEO_TITLE_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    CardDraft,
    CritiqueReport,
    SeoBlock,
    SourceRef,
    SupplierFacts,
)
from app.schemas.jobs import JobIn, JobOut

__all__ = [
    "SEO_DESCRIPTION_MAX_LENGTH",
    "SEO_TITLE_MAX_LENGTH",
    "TITLE_MAX_LENGTH",
    "CardDraft",
    "CritiqueReport",
    "JobIn",
    "JobOut",
    "SeoBlock",
    "SourceRef",
    "SupplierFacts",
]
