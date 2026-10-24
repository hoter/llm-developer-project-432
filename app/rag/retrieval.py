"""Поиск по фрагментам: по векторам, по словам и гибридный.

Гибрид нужен потому, что режимы промахиваются по-разному: «какая мощность
у блендера» и «мотор 800 Вт» — одно и то же разными словами (векторы
находят, слова нет), а артикул «KTL-1700» надо искать буква в букву
(слова находят, векторы путают с похожими строками).

Модель эмбеддингов считается до взятия соединения: пока идёт инференс,
пул свободен.
"""
import argparse
import json
from dataclasses import asdict, dataclass

from app.core import db
from app.core.config import settings
from app.rag.embedder import embed_query
from app.repositories import chunks as chunks_repo

MODES = ("vector", "text", "hybrid")


@dataclass
class SearchFilters:
    """Фильтры по метаданным фрагмента."""

    document_id: str | None = None
    section: str | None = None
    article: str | None = None
    brand: str | None = None

    def as_kwargs(self) -> dict:
        return {key: value for key, value in asdict(self).items() if value}


def search(
    query: str,
    *,
    mode: str = "hybrid",
    limit: int | None = None,
    min_similarity: float | None = None,
    filters: SearchFilters | None = None,
) -> list[dict]:
    """Найти фрагменты. Возвращает id, текст, оценку и метаданные."""
    if mode not in MODES:
        raise ValueError(f"неизвестный режим поиска: {mode}")
    if not query.strip():
        return []

    limit = limit or settings.search_limit
    threshold = (
        settings.search_min_similarity if min_similarity is None else min_similarity
    )
    kwargs = (filters or SearchFilters()).as_kwargs()

    embedding = embed_query(query) if mode in ("vector", "hybrid") else None

    with db.connection() as conn:
        if mode == "vector":
            return chunks_repo.search_vector(
                conn, embedding, limit=limit, min_similarity=threshold, **kwargs
            )
        if mode == "text":
            return chunks_repo.search_text(conn, query, limit=limit, **kwargs)
        return chunks_repo.search_hybrid(
            conn,
            embedding,
            query,
            limit=limit,
            min_similarity=threshold,
            **kwargs,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Поиск по фрагментам документов")
    parser.add_argument("query", help="поисковый запрос")
    parser.add_argument("--mode", choices=MODES, default="hybrid")
    parser.add_argument("--limit", type=int, default=settings.search_limit)
    parser.add_argument("--min-similarity", type=float, default=None)
    parser.add_argument("--document-id", default=None)
    parser.add_argument("--section", default=None)
    parser.add_argument("--article", default=None)
    parser.add_argument("--brand", default=None)
    args = parser.parse_args()

    results = search(
        args.query,
        mode=args.mode,
        limit=args.limit,
        min_similarity=args.min_similarity,
        filters=SearchFilters(
            document_id=args.document_id,
            section=args.section,
            article=args.article,
            brand=args.brand,
        ),
    )
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
