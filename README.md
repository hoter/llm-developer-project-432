# ИИ-генератор карточки товара


[![hexlet-check](https://github.com/hoter/llm-developer-project-432/actions/workflows/hexlet-check.yml/badge.svg)](https://github.com/hoter/llm-developer-project-432/actions)

Соберите бэкенд-сервис, который принимает документы поставщиков в форматах pdf, docx и
xlsx, строит по ним поисковый индекс и генерирует черновик карточки товара — с
указанием источников, списком недостающих данных и уровнем уверенности. По пути
освоите LLM-клиент с ретраями, строгий контракт результата на Pydantic, разбор
офисных документов и чанкинг, локальные эмбеддинги с pgvector и гибридный поиск,
цитирование с проверкой источников, учёт стоимости вызовов, метрики генерации и
защиту от инъекций через документы и утечек персональных данных.

Учебный проект Хекслета: https://ru.hexlet.io/programs/llm-developer


## Стек

- Python 3.12, FastAPI, Pydantic v2
- PostgreSQL 16 с расширением [pgvector](https://github.com/pgvector/pgvector)
- psycopg 3 + `psycopg_pool` (пул соединений уровня приложения)
- Temporal — устойчивое исполнение процессов (dev-сервер в Compose)
- Celery + RabbitMQ — фоновые задачи
- OpenAI Agents SDK как LLM-клиент

## Установка

```bash
git clone https://github.com/hoter/llm-developer-project-432.git
cd llm-developer-project-432

python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env
```

Затем впишите модель из `curl localhost:1234/v1/models` в `LLM_MODEL`.

## Инфраструктура

`docker compose` поднимает три сервиса:

- `postgres` — образ `pgvector/pgvector`, расширение `vector` уже собрано
  внутри, миграция его только активирует;
- `temporal` — dev-сервер одним контейнером, состояние процессов лежит в
  SQLite на volume `temporal-data`;
- `rabbitmq` — брокер для Celery.

```bash
make infra            # docker compose up -d
docker compose ps     # postgres и temporal должны быть running (healthy)
```

| Сервис | Адрес |
|---|---|
| PostgreSQL | `localhost:5432` |
| Temporal gRPC | `localhost:7233` |
| Temporal Web UI | http://localhost:8233 |
| RabbitMQ | `localhost:5672`, UI http://localhost:15672 (card/card) |

Если 5432 занят другим Postgres: `PG_PORT=5433 make infra` и такой же порт в
`DATABASE_URL`.

## Миграции

Схема накатывается SQL-файлами из `db/migrations/`, применённые версии
запоминаются в таблице `schema_migrations`. Схема при старте приложения больше
не создаётся.

```bash
make migrate
# первый запуск:  применена миграция 0001_init
#                 применена миграция 0002_jobs
# второй запуск:  новых миграций нет
```

Новая миграция — новый файл с префиксом порядка (`0003_documents.sql`),
применяется тем же `make migrate`. Почему SQL-файлы, а не Alembic —
в [docs/decisions.md](docs/decisions.md).

## Запуск

```bash
make api              # FastAPI на :8000 (терминал 1)
make worker           # Celery-воркер (терминал 2)
make temporal-worker  # Temporal-воркер (терминал 3)
```

Примеры:

```bash
curl -X POST localhost:8000/cards -H 'Content-Type: application/json' \
  -d '{"supplier_text": "..."}'

curl -X POST localhost:8000/jobs -H 'Content-Type: application/json' \
  -d '{"supplier_text": "..."}'
```

## Проверки состояния

| Эндпоинт | Что проверяет |
|---|---|
| `GET /live` (он же `GET /health`) | живость процесса, базу не трогает |
| `GET /ready` | соединение из пула и активное расширение `vector` |

```bash
curl localhost:8000/live    # {"status":"ok"}
curl localhost:8000/ready   # {"status":"ok","database":"ok","vector":"0.8.7"}
```

При остановленной базе `/live` продолжает отвечать `200`, а `/ready` —
`503` с описанием причины.

## Тесты и линтер

```bash
make test   # pytest
make lint   # ruff check app tests
```

## Структура

```
app/
├── main.py
├── core/          config.py, db.py, logging.py, migrate.py
├── routers/       health.py, cards.py, jobs.py, workflows.py
├── services/      pipeline.py
├── agents/        prompts.py
├── llm/           client.py
├── repositories/  jobs.py
├── schemas.py
├── temporal/      workflows.py, activities.py
└── workers/       celery_app.py, tasks.py
db/migrations/     SQL-миграции
data/              документы поставщиков
docs/decisions.md  архитектурные решения
tests/
```

## Документы поставщиков

Стартовый набор лежит в `data/` — как есть, без переименований:
`blender_kp.docx`, `blender_passport.pdf`, `boiler_scan.pdf`,
`kettle_manual.pdf`, `kettle_spec.xlsx`, `golden_cards.json`.

---

<details>
<summary>Автоматические тесты Хекслета</summary>

Тесты запускаются на каждый коммит. За запуск отвечает файл `.github/workflows/hexlet-check.yml` — не удаляйте и не переименовывайте ни его, ни репозиторий.

</details>

## О Хекслете

[Хекслет](https://ru.hexlet.io/) — школа программирования: авторские программы обучения с практикой, поддержкой наставников и реальными проектами, которые остаются в резюме. Этот репозиторий — один из таких проектов.
