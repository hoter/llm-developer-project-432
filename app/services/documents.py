"""Сервис документа: разбор → нормализация → резка → сохранение."""
from pathlib import Path

from app.core import db
from app.core.logging import get_logger
from app.parsers import ParseError, UnsupportedFormat
from app.parsers.chunker import chunk_blocks
from app.parsers.docx import parse_docx
from app.parsers.normalizer import normalize
from app.parsers.pdf import parse_pdf
from app.parsers.xlsx import parse_xlsx
from app.rag.reindex import index_document
from app.repositories import chunks as chunks_repo
from app.repositories import documents as documents_repo

log = get_logger(__name__)


def parse_to_chunks(data: bytes, kind: str, doc_id: str) -> list[dict]:
    """Разобрать файл и нарезать на фрагменты с метаданными."""
    kind = kind.lower().lstrip(".")
    if kind == "pdf":
        blocks = parse_pdf(data)
    elif kind == "docx":
        blocks = parse_docx(data)
    elif kind == "xlsx":
        blocks = parse_xlsx(data)
    else:
        raise UnsupportedFormat(f"формат «{kind or 'без расширения'}» не поддерживается")
    return chunk_blocks(normalize(blocks), doc_id)


def ingest_document(document_id: str) -> str:
    """Разобрать документ и сохранить фрагменты. Возвращает новый статус."""
    with db.connection() as conn:
        document = documents_repo.get_document(conn, document_id)
    if not document:
        raise ValueError(f"документ {document_id} не найден")

    _set_status(document_id, "parsing")

    try:
        data = Path(document["stored_path"]).read_bytes()
        chunks = parse_to_chunks(data, document["kind"], document_id)
        if not chunks:
            raise ParseError("документ не дал ни одного фрагмента")
    except Exception as exc:
        log.warning("document_parse_failed", document_id=document_id, error=str(exc))
        _set_status(document_id, "failed", error=str(exc))
        return "failed"

    with db.connection() as conn:
        chunks_repo.replace_chunks(conn, document_id, chunks)

    vectors = index_document(document_id)

    with db.connection() as conn:
        documents_repo.set_status(
            conn, document_id, "indexed", chunks_count=len(chunks)
        )
    log.info(
        "document_indexed", document_id=document_id, chunks=len(chunks), vectors=vectors
    )
    return "indexed"


def _set_status(document_id: str, status: str, *, error: str | None = None) -> None:
    with db.connection() as conn:
        documents_repo.set_status(conn, document_id, status, error=error)
