"""Единый клиент Temporal.

Подключение — ресурс уровня приложения: один Client на процесс, создаётся
при первом обращении и переиспользуется роутерами. Провайдер движка знают
только routers/workflows.py, routers/jobs.py и сам воркер.
"""
from temporalio.client import Client

from app.core.config import settings

_client: Client | None = None


async def get_client() -> Client:
    global _client
    if _client is None:
        _client = await Client.connect(settings.temporal_host)
    return _client
