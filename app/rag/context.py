"""Сборка контекста для генерации из найденных фрагментов.

Требования к контексту:
- каждый фрагмент опознаваем: модель видит метку [S1], [S2], … и может на
  неё сослаться, а приложение — проверить ссылку;
- предел размера: контекст не растёт бесконечно;
- повторы убраны: одинаковый текст из разных документов попадает один раз.
"""
import json
from dataclasses import dataclass, field

from app.core.config import settings
from app.guardrails import pii


@dataclass
class ContextSource:
    source_id: str
    chunk_id: str
    text: str
    filename: str | None = None
    page: int | None = None
    section: str | None = None


@dataclass
class DocumentContext:
    text: str
    sources: list[ContextSource] = field(default_factory=list)
    masked: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "text": self.text,
                "sources": [
                    {
                        "source_id": source.source_id,
                        "chunk_id": source.chunk_id,
                        "text": source.text,
                        "filename": source.filename,
                        "page": source.page,
                        "section": source.section,
                    }
                    for source in self.sources
                ],
                "masked": self.masked,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str) -> "DocumentContext":
        data = json.loads(raw)
        return cls(
            text=data["text"],
            sources=[ContextSource(**source) for source in data["sources"]],
            masked=data.get("masked", {}),
        )

    def chunk_ids(self) -> set[str]:
        return {source.chunk_id for source in self.sources}


def build_context(
    chunks: list[dict], *, max_chars: int | None = None
) -> DocumentContext:
    """Собрать контекст: метки, дедупликация, предел размера."""
    limit = max_chars or settings.rag_context_max_chars
    seen: set[str] = set()
    blocks: list[str] = []
    sources: list[ContextSource] = []
    total = 0
    masked_total: dict[str, int] = {}

    for chunk in chunks:
        raw_text = (chunk.get("text") or "").strip()
        if not raw_text:
            continue
        # Маскирование — часть сборки контекста: до промпта и до логов.
        masked = pii.mask(raw_text)
        text = masked.text
        for kind, count in masked.counts.items():
            masked_total[kind] = masked_total.get(kind, 0) + count
        key = " ".join(text.split())
        if key in seen:
            continue

        source_id = f"S{len(sources) + 1}"
        block = _format_block(source_id, chunk, text)
        remaining = limit - total
        if remaining <= 0:
            break
        if len(block) > remaining:
            block = block[: max(remaining - 3, 0)].rstrip() + "..."

        seen.add(key)
        blocks.append(block)
        sources.append(
            ContextSource(
                source_id=source_id,
                chunk_id=str(chunk["id"]),
                text=text,
                filename=chunk.get("filename"),
                page=chunk.get("page"),
                section=chunk.get("section"),
            )
        )
        total += len(block) + 2

    return DocumentContext(
        text="\n\n".join(blocks), sources=sources, masked=masked_total
    )


def _format_block(source_id: str, chunk: dict, text: str) -> str:
    lines = [
        f"[{source_id}]",
        f"документ: {chunk.get('filename') or chunk.get('document_id')}",
        f"страница: {chunk.get('page')}",
        f"секция: {chunk.get('section')}",
    ]
    if chunk.get("article"):
        lines.append(f"артикул: {chunk['article']}")
    if chunk.get("brand"):
        lines.append(f"бренд: {chunk['brand']}")
    lines.append(f"текст: {text}")
    return "\n".join(lines)
