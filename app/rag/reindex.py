"""Досчёт векторов фрагментам.

Команда ``python -m app.rag.reindex`` (или ``make reindex``) и шаг после
разбора документа. Работает пачками: берёт фрагменты без вектора, считает
пачку, пишет её и берёт следующую. Соединение не держится, пока считается
модель.

Повторный запуск — пустая работа: фрагментов без вектора не остаётся.
"""
from app.core import db
from app.core.config import settings
from app.core.logging import get_logger
from app.rag.embedder import check_dimension, embed_documents
from app.repositories import chunks as chunks_repo

log = get_logger(__name__)


def index_pending(*, document_id: str | None = None, batch_size: int | None = None) -> int:
    """Досчитать векторы. Возвращает число проиндексированных фрагментов."""
    size = batch_size or settings.embedding_batch_size
    indexed = 0

    while True:
        with db.connection() as conn:
            rows = chunks_repo.chunks_without_embedding(
                conn, limit=size, document_id=document_id
            )
        if not rows:
            break

        vectors = embed_documents([row["text"] for row in rows])
        for vector in vectors:
            check_dimension(vector)

        with db.connection() as conn:
            chunks_repo.set_embeddings(
                conn,
                [(vector, row["id"]) for vector, row in zip(vectors, rows)],
            )

        indexed += len(rows)
        log.info("embeddings_indexed", batch=len(rows), total=indexed)

    return indexed


def index_document(document_id: str) -> int:
    """Индексация сразу после разбора — продолжение цепочки."""
    return index_pending(document_id=document_id)


def main() -> None:
    total = index_pending()
    if total:
        print(f"проиндексировано фрагментов: {total}")
    else:
        print("фрагментов без векторов нет — индексировать нечего")


if __name__ == "__main__":
    main()
