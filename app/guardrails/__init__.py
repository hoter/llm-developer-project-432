"""Защита на границах: маскирование PII и детектор инъекций.

``guard_context`` работает до промпта: чистит фрагменты и выбрасывает
подозрительные. ``guard_output`` — последний рубеж: контакты и следы
инструкций в готовой карточке.
"""
from dataclasses import dataclass, field

from app.core.config import settings
from app.guardrails.injection import (
    InjectionVerdict,
    detect_injection_llm,
    detect_injection_regex,
)
from app.guardrails.pii import PiiEntity, contains_pii, mask_pii

__all__ = [
    "GuardReport",
    "InjectionVerdict",
    "PiiEntity",
    "contains_pii",
    "guard_context",
    "guard_output",
    "mask_pii",
]


@dataclass
class GuardReport:
    masked_pii: int = 0
    suspicious_chunks: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return len(self.suspicious_chunks) > settings.suspicious_chunk_limit


async def guard_context(chunks: list[dict]) -> tuple[list[dict], GuardReport]:
    """Очистить фрагменты перед подачей в модель.

    Порядок: PII-маскирование, быстрые правила инъекций, точная модель только
    по помеченным. Отказ детектора трактуется как подозрение (fail-closed).
    """
    report = GuardReport()
    safe: list[dict] = []

    for chunk in chunks:
        cleaned, entities = mask_pii(str(chunk.get("text", "")))
        report.masked_pii += len(entities)

        rule_verdict = detect_injection_regex(cleaned)
        if rule_verdict.suspicious:
            try:
                precise = await detect_injection_llm(cleaned)
            except Exception:
                precise = InjectionVerdict(
                    True, reason="детектор недоступен — считаем подозрительным"
                )
            if precise.suspicious:
                report.suspicious_chunks.append(str(chunk["chunk_id"]))
                continue

        safe.append({**chunk, "text": cleaned})

    return safe, report


def guard_output(card_json: str) -> tuple[str, list[str]]:
    """Проверить готовую карточку: контакты и следы инструкций."""
    cleaned, entities = mask_pii(card_json)
    issues: list[str] = []

    if entities:
        kinds = sorted({entity.kind for entity in entities})
        issues.append("в карточке остались персональные данные: " + ", ".join(kinds))

    verdict = detect_injection_regex(cleaned)
    if verdict.suspicious:
        issues.append(f"в карточке следы служебных инструкций: {verdict.reason}")

    return cleaned, issues
