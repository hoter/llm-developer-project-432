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


@dataclass
class ContextSource:
    source_id: str
    chunk_id: str
    text: str


@dataclass
class DocumentContext:
    text: str
    sources: list[ContextSource] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "text": self.text,
                "sources": [
                    {
                        "source_id": source.source_id,
                        "chunk_id": source.chunk_id,
                        "text": source.text,
                    }
                    for source in self.sources
                ],
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str) -> "DocumentContext":
        data = json.loads(raw)
        return cls(
            text=data["text"],
            sources=[ContextSource(**source) for source in data["sources"]],
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

    for chunk in chunks:
        text = (chunk.get("text") or "").strip()
        if not text:
            continue
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
        sources.append(ContextSource(source_id=source_id, chunk_id=str(chunk["id"]), text=text))
        total += len(block) + 2

    return DocumentContext(text="\n\n".join(blocks), sources=sources)


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
