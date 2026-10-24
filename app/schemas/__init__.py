"""Контракты приложения: карточка, задачи, служебные вердикты."""
from app.schemas.cards import (
    SEO_DESCRIPTION_MAX_LENGTH,
    SEO_TITLE_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    CardDraft,
    CritiqueReport,
    InjectionVerdict,
    JudgeVerdict,
    Seo,
    SeoBlock,
    SourceRef,
    SupplierFacts,
)
from app.schemas.jobs import DocumentOut, GenerateIn, JobIn, JobOut

Citation = SourceRef

__all__ = [
    "SEO_DESCRIPTION_MAX_LENGTH",
    "SEO_TITLE_MAX_LENGTH",
    "TITLE_MAX_LENGTH",
    "CardDraft",
    "Citation",
    "CritiqueReport",
    "DocumentOut",
    "GenerateIn",
    "InjectionVerdict",
    "JobIn",
    "JobOut",
    "JudgeVerdict",
    "Seo",
    "SeoBlock",
    "SourceRef",
    "SupplierFacts",
]
