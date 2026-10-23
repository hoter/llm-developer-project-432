"""Celery-приложение: брокер — RabbitMQ, result backend не нужен.

Статус работы живёт в таблице jobs (Postgres), а не в result backend Celery —
нам важно бизнес-состояние, а не возвращаемое значение таски.
"""
from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "card",
    broker=settings.rabbitmq_url,
    backend=None,
)

celery_app.conf.update(
    task_acks_late=True,          # ack после выполнения, не при получении
    task_reject_on_worker_lost=True,  # упал воркер → сообщение вернётся в очередь
    broker_transport_options={"confirm_timeout": 10},
)

# Регистрация задач: воркер стартует по -A app.workers.celery_app,
# без этого импорта модуль tasks не загрузится и задачи будут «unregistered».
import app.workers.tasks  # noqa: E402,F401  (циклический импорт разорван: tasks -> celery_app)
