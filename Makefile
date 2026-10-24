.PHONY: help infra migrate reindex api temporal-worker test lint

help:
	@echo "make infra           - поднять postgres + temporal (docker compose)"
	@echo "make migrate         - применить миграции из db/migrations/"
	@echo "make reindex         - досчитать эмбеддинги фрагментам"
	@echo "make api             - FastAPI на :8000"
	@echo "make temporal-worker - temporal-воркер (workflow + activities)"
	@echo "make test            - pytest"
	@echo "make lint            - ruff"

infra:
	docker compose up -d

migrate:
	python -m app.core.migrate

reindex:
	python -m app.rag.reindex

api:
	uvicorn app.main:app --reload --port 8000

temporal-worker:
	python -m app.temporal_worker

test:
	pytest

lint:
	ruff check app tests
