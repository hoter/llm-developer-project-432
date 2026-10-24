import logging

import structlog
from structlog.contextvars import get_contextvars


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )


def get_logger(*args, **kwargs):
    return structlog.get_logger(*args, **kwargs)


def current_request_id() -> str | None:
    """Идентификатор текущего HTTP-запроса из контекста логов."""
    return get_contextvars().get("request_id")
