"""Локальные эмбеддинги: fastembed на CPU, модель грузится один раз.

Векторы считаются пачкой; для запроса и документов — отдельные вызовы,
чтобы модель могла применить свои задачные префиксы.
"""
from functools import lru_cache
from typing import Any

from app.core.config import settings


@lru_cache(maxsize=1)
def _model() -> Any:
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=settings.embedding_model)


def embed_documents(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    vectors = _model().embed(texts, batch_size=settings.embedding_batch_size)
    return [[float(value) for value in vector] for vector in vectors]


def embed_query(text: str) -> list[float]:
    vectors = _model().embed([text])
    return [float(value) for value in next(iter(vectors))]


def check_dimension(vector: list[float]) -> None:
    if len(vector) != settings.embed_dim:
        raise RuntimeError(
            f"модель вернула вектор размерности {len(vector)}, "
            f"а в настройках EMBED_DIM={settings.embed_dim}"
        )
