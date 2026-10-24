"""Локальные эмбеддинги: E5 на CPU, модель загружается один раз.

E5 обучена с задачными префиксами: документы кодируются с ``passage: ``,
запросы — с ``query: ``. Без префиксов близость релевантных пар проседает
так, что нормальный порог отсечения начинает выметать верные результаты.
Префиксы — часть контракта модели (карточка intfloat/multilingual-e5-large),
а не вкусовая настройка.

Модель грузится лениво и один раз на процесс; векторы считаются пачкой.
"""
from functools import lru_cache
from typing import Any

from app.core.config import settings

QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "


@lru_cache(maxsize=1)
def _model() -> Any:
    """Загрузить модель один раз на процесс.

    Импорт внутри функции: fastembed тянет onnxruntime, и на старте API он
    нужен только тем обработчикам, которые действительно ищут.
    """
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=settings.embedding_model)


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Векторы фрагментов документов — пачкой, с префиксом пассажа."""
    if not texts:
        return []
    vectors = _model().embed(
        [PASSAGE_PREFIX + text for text in texts],
        batch_size=settings.embedding_batch_size,
    )
    return [[float(value) for value in vector] for vector in vectors]


def embed_query(text: str) -> list[float]:
    """Вектор запроса — с префиксом запроса."""
    vectors = _model().embed([QUERY_PREFIX + text])
    return [float(value) for value in next(iter(vectors))]


def check_dimension(vector: list[float]) -> None:
    """Размерность из настроек должна совпадать с колонкой в базе."""
    if len(vector) != settings.embedding_dimension:
        raise RuntimeError(
            f"модель вернула вектор размерности {len(vector)}, "
            f"а в настройках EMBEDDING_DIMENSION={settings.embedding_dimension}"
        )
