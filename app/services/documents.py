"""Сервис документа: разбор → нормализация → резка → сохранение.

Соединение берём на операцию: разбор файла и вызовы модели не должны
держать коннект из пула. Состояние документа переключается по ходу дела,
а неудачный разбор — это статус failed с причиной, не тихий пустой результат.
"""
from pathlib import Path

from app.core import db
from app.core.logging import get_logger
from app.parsers import ParseError, parse_document
from app.parsers.chunker import chunk_blocks
from app.parsers.normalizer import normalize_blocks
from app.repositories import chunks as chunks_repo
from app.repositories import documents as documents_repo

log = get_logger(__name__)


def ingest_document(document_id: str) -> str:
    """Разобрать документ и сохранить фрагменты. Возвращает новый статус.

    Синхронная функция: её запускает Temporal-activity в пуле потоков.
    """
    with db.connection() as conn:
        document = documents_repo.get_document(conn, document_id)
    if not document:
        raise ValueError(f"документ {document_id} не найден")

    _set_status(document_id, "parsing")

    try:
        blocks = parse_document(Path(document["stored_path"]))
        blocks = normalize_blocks(blocks, document_name=document["filename"])
        chunks = chunk_blocks(blocks, document=document["filename"])
        if not chunks:
            raise ParseError("документ не дал ни одного фрагмента")
    except Exception as exc:
        log.warning("document_parse_failed", document_id=document_id, error=str(exc))
        _set_status(document_id, "failed", error=str(exc))
        return "failed"

    # Сохранение — вне try: сбой базы должен дойти до движка и повториться,
    # а не превратиться в «документ плохой».
    with db.connection() as conn:
        chunks_repo.replace_chunks(conn, document_id, chunks)
        documents_repo.set_status(
            conn, document_id, "indexed", chunks_count=len(chunks)
        )
    log.info("document_indexed", document_id=document_id, chunks=len(chunks))
    return "indexed"


def _set_status(document_id: str, status: str, *, error: str | None = None) -> None:
    with db.connection() as conn:
        documents_repo.set_status(conn, document_id, status, error=error)
