.PHONY: help infra migrate api worker temporal-worker test lint

help:
	@echo "make infra           - поднять postgres + temporal + rabbitmq (docker compose)"
	@echo "make migrate         - применить миграции из db/migrations/"
	@echo "make api             - FastAPI на :8000"
	@echo "make worker          - celery-воркер (очереди card.generate + card.critique)"
	@echo "make temporal-worker - temporal-воркер (workflow + activities)"
	@echo "make test            - pytest"
	@echo "make lint            - ruff"

infra:
	docker compose up -d

migrate:
	python -m app.core.migrate

api:
	uvicorn app.main:app --reload --port 8000

worker:
	celery -A app.workers.celery_app worker -Q card.generate,card.critique --concurrency=1 -l info

temporal-worker:
	python -m app.temporal_worker

test:
	pytest

lint:
	ruff check app tests
