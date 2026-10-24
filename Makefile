.PHONY: help install setup infra migrate reindex api temporal-worker test lint eval costs

help:
	@echo "make install         - зависимости из uv.lock"
	@echo "make setup           - install + миграции"
	@echo "make infra           - поднять postgres + temporal (docker compose)"
	@echo "make migrate         - применить миграции из db/migrations/"
	@echo "make reindex         - досчитать эмбеддинги фрагментам"
	@echo "make api             - FastAPI на :8000"
	@echo "make temporal-worker - temporal-воркер (workflow + activities)"
	@echo "make test            - pytest"
	@echo "make lint            - ruff"
	@echo "make eval            - метрики на подмножестве (ALL=1 — весь набор)"
	@echo "make costs           - разбивка вызовов модели по моделям"

install:
	uv sync --frozen

setup: install migrate

infra:
	docker compose up -d

migrate:
	uv run python -m app.core.migrate

reindex:
	uv run python -m app.rag.reindex

api:
	uv run uvicorn app.main:app --reload --port 8000

temporal-worker:
	uv run python -m app.temporal_worker

test:
	uv run pytest -q

lint:
	uv run ruff check app tests evals

eval:
	uv run python -m evals.run $(if $(ALL),--all,)

costs:
	uv run python -m app.llm.cost
