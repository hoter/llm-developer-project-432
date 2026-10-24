"""Сборка контекста из найденных фрагментов.

Каждый фрагмент опознаваем: в шапке его chunk_id, документ, страница и
секция. Одинаковые тексты схлопываются, размер ограничен. PII-маскирование
делается до этого шага (guard_context), поэтому в контекст и логи попадают
только метки.
"""
import re

from app.core.config import settings

_HEADER_ID = re.compile(r"^\[([^|\]\s]+)")


def build_context(chunks: list[dict], *, max_chars: int | None = None) -> str:
    """Собрать текст контекста с жёстким потолком размера."""
    limit = max_chars or settings.rag_context_max_chars
    seen: set[str] = set()
    blocks: list[str] = []
    total = 0

    for chunk in chunks:
        text = str(chunk.get("text", "")).strip()
        if not text:
            continue
        key = " ".join(text.split())
        if key in seen:
            continue

        metadata = chunk.get("metadata") or {}
        chunk_id = str(chunk.get("chunk_id") or metadata.get("chunk_id") or "")
        filename = str(chunk.get("filename") or metadata.get("filename") or "")
        page = metadata.get("page")
        section = str(metadata.get("section") or "")
        block = f"[{chunk_id} | {filename} | стр. {page} | {section}]\n{text}"

        remaining = limit - total
        if remaining <= 0:
            break
        if len(block) > remaining:
            block = block[: max(remaining - 3, 0)].rstrip() + "..."

        seen.add(key)
        blocks.append(block)
        total += len(block) + 2

    return "\n\n".join(blocks)


def context_chunk_ids(context: str) -> set[str]:
    """Идентификаторы фрагментов, реально поданных в контексте."""
    ids: set[str] = set()
    for line in context.splitlines():
        match = _HEADER_ID.match(line.strip())
        if match:
            ids.add(match.group(1))
    return ids
