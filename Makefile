.PHONY: help install infra migrate reindex api temporal-worker test lint eval costs

help:
	@echo "make install         - зависимости из requirements.lock"
	@echo "make infra           - поднять postgres + temporal (docker compose)"
	@echo "make migrate         - применить миграции из db/migrations/"
	@echo "make reindex         - досчитать эмбеддинги фрагментам"
	@echo "make api             - FastAPI на :8000"
	@echo "make temporal-worker - temporal-воркер (workflow + activities)"
	@echo "make test            - pytest"
	@echo "make eval            - метрики на подмножестве (ALL=1 — весь набор)"
	@echo "make costs           - разбивка вызовов модели по моделям"

install:
	pip install -r requirements.lock

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

eval:
	python -m evals.run $(if $(ALL),--all,)

costs:
	python -m app.llm.cost
