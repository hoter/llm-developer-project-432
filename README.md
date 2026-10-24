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
- Temporal — фоновые процессы и ожидание подтверждения
- OpenAI Agents SDK как LLM-клиент
- pypdf, python-docx, openpyxl — разбор документов поставщиков

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

`docker compose` поднимает два сервиса:

- `postgres` — образ `pgvector/pgvector`, расширение `vector` уже собрано
  внутри, миграция его только активирует;
- `temporal` — dev-сервер одним контейнером, состояние процессов лежит в
  SQLite на volume `temporal-data`.

```bash
make infra            # docker compose up -d
docker compose ps     # postgres и temporal должны быть running (healthy)
```

| Сервис | Адрес |
|---|---|
| PostgreSQL | `localhost:5432` |
| Temporal gRPC | `localhost:7233` |
| Temporal Web UI | http://localhost:8233 |

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
make temporal-worker  # Temporal-воркер (терминал 2)
```

## API

| Метод | Путь | Что делает |
|---|---|---|
| `POST` | `/cards` | синхронно: текст → карточка (весь пайплайн в запросе) |
| `POST` | `/jobs` | создаёт задачу, отвечает `202` и `id`; учитывает `Idempotency-Key` |
| `GET` | `/jobs/{id}` | статус задачи из базы и готовый черновик |
| `POST` | `/jobs/{id}/approve` | сигнал подтверждения |
| `POST` | `/jobs/{id}/request-changes` | сигнал отказа |
| `POST` | `/documents` | загрузка файла поставщика, `202` и `id`; `pdf`, `docx`, `xlsx` |
| `GET` | `/documents/{id}` | состояние документа и число фрагментов |
| `GET` | `/workflows/{id}` | состояние процесса в Temporal (`run_status` + query) |
| `GET` | `/workflows/{id}/result` | результат завершённого процесса |

```bash
curl -X POST localhost:8000/cards -H 'Content-Type: application/json' \
  -d '{"supplier_text": "..."}'

curl -X POST localhost:8000/jobs -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-1' -d '{"supplier_text": "..."}'
# {"id":"9fb442b9c16e","status":"pending"}

curl localhost:8000/jobs/9fb442b9c16e
curl -X POST localhost:8000/jobs/9fb442b9c16e/approve

curl -X POST localhost:8000/documents -F "file=@data/kettle_spec.xlsx"
# {"id":"3f0e5ae94c4f","status":"new"}

curl localhost:8000/documents/3f0e5ae94c4f
# {"id":"...","filename":"kettle_spec.xlsx","status":"indexed","chunks_count":3,"error":null}
```

### Как идёт процесс

```
pending → extracting → generating → critiquing → (regenerating → …)
        → awaiting_approval | needs_review → approved | rejected
                                           ↘ failed
```

- `POST /jobs` создаёт строку в `jobs` и запускает `CardWorkflow` с
  `id = id задачи`. Повтор с тем же `Idempotency-Key` возвращает ту же задачу
  и не запускает второй прогон (`REJECT_DUPLICATE`), поэтому двойной клик не
  даёт двойной счёт за токены.
- Извлечение, генерация и проверка — отдельные activities; у каждой свой
  `RetryPolicy`. Внутри шага клиент модели повторяет сам вызов, движок
  повторяет шаг — это разные уровни.
- Статус предметной области пишется в базу отдельной activity, а не изнутри
  пайплайна: пока идёт вызов модели, соединение уже вернулось в пул.
- Петля переделки — не больше трёх кругов, после чего черновик уходит человеку.
- `confidence` ниже `CONFIDENCE_THRESHOLD` переводит задачу в `needs_review`:
  черновик есть, но «готово» он не считается — решает человек.
- `awaiting_approval` и `needs_review` — ожидание сигнала. Процесс при этом
  не занимает ни потока, ни соединения и переживает рестарт воркера.
- Если воркер убили посреди шага, новый воркер продолжит процесс: выполненные
  шаги заново не прогоняются, а прерванный шаг повторяется по `heartbeat_timeout`
  (воркер шлёт heartbeat каждые 10 секунд).

История каждого процесса — http://localhost:8233.

## Контракт результата

Карточка — не «текст, который вернула модель», а модель данных с
ограничениями (`app/schemas/cards.py`):

- `title` — не длиннее 60 символов, пробелы по краям срезаются;
- `confidence` — строго от 0 до 1;
- `characteristics` — пустые значения отбрасываются при валидации;
- одно и то же поле не может быть одновременно в `characteristics`
  и `missing_fields`;
- `seo` — вложенный блок (`title`, `description`, `keywords`);
- `sources` — ссылки на фрагменты документов (`SourceRef`), пока пустые.

Ответ модели проходит три уровня (`app/services/structured.py`):

1. **Разбор** — чистый JSON, JSON в markdown-заборе, JSON с текстом до и
   после; мусор и пустой ответ дают понятную ошибку (`json_utils.py`).
2. **Валидация с лечением** — невалидный ответ уходит обратно модели вместе
   с текстом ошибки; попыток не больше `LLM_STRUCTURED_ATTEMPTS`.
3. **Точечная переделка** — если сломалось одно поле, модель получает текущий
   черновик и просит исправить только его: описание и остальные поля не
   перегенерируются.

Схема ответа генерируется из Pydantic-модели и передаётся модели текстом в
инструкции агента: LM Studio не поддерживает строгий `json_schema`-режим,
поэтому форму ответа проверяет приложение, а не сервер модели.

Промпты прямо требуют отказа вместо догадки: данных нет — имя поля уходит в
`missing_fields`, а не в выдуманное значение; низкая уверенность честно
пишется в `confidence`.

## Документы поставщиков

Загрузка (`POST /documents`) проверяет расширение (`pdf`, `docx`, `xlsx`) и
размер (`MAX_UPLOAD_BYTES`), считает `sha256` и запускает `DocumentWorkflow`.
Повторная загрузка того же файла возвращает существующий документ — дублей
нет. Состояния: `new → parsing → indexed | failed`.

| Формат | Что достаём |
|---|---|
| `pdf` | текст постранично; таблицы — бонусная ветка, не входит в базовый путь |
| `docx` | параграфы и таблицы в порядке документа, заголовок — граница секции |
| `xlsx` | первая строка — заголовки колонок, каждая строка — «артикул: параметр значение» |

Разбор (`app/parsers/`):

- **нормализация** — перенос через дефис склеивается, лигатуры и лишние
  пробелы схлопываются; колонтитулы ищутся только на документах от трёх
  страниц и только в первых/последних строках страницы (правило «большинство
  страниц» на двухстраничном документе вымело бы весь текст);
- **резка** — текст окном с перекрытием, таблица по строкам: строка не
  рвётся, и каждая часть несёт строку заголовков колонок;
- **метаданные фрагмента** — документ, страница, секция, артикул, бренд.

Скан без текстового слоя (`data/boiler_scan.pdf`) получает `failed` с
причиной: «в PDF нет текстового слоя…». Молча пустого результата не бывает.

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

Модель тестам не нужна: `run_agent` подменяется в тестах. Покрыто:

- разбор ответа — чистый JSON, markdown-забор, текст до и после, мусор,
  пустой ответ, незакрытый JSON;
- схемы — длина заголовка, диапазон уверенности, пустые характеристики,
  поле в двух списках одновременно;
- лечение — невалидный JSON уходит обратно с текстом ошибки, пустой ответ
  даёт ошибку;
- точечная переделка — длинный заголовок правится без переделки описания;
- пайплайн — успех, переделка, исчерпанная петля, низкая уверенность;
- парсеры — страницы pdf, секции docx, строки xlsx, отказ скану;
- нормализация — переносы, лигатуры, ловушка с двухстраничным колонтитулом;
- резка — перекрытие, неразрывные строки таблицы, заголовки в каждой части;
- сервис документов — индексация выданных файлов, отказ скану, отсутствие
  дублей при повторной загрузке и повторном разборе.

Тесты репозиториев работают на живой базе и пропускаются, если Postgres
недоступен.

## Структура

```
app/
├── main.py
├── core/          config.py, db.py, logging.py, migrate.py
├── routers/       health.py, cards.py, jobs.py, documents.py, workflows.py
├── services/      pipeline.py, structured.py, json_utils.py, documents.py
├── agents/        prompts.py
├── llm/           client.py
├── parsers/       pdf.py, docx.py, xlsx.py, normalizer.py, chunker.py
├── repositories/  jobs.py, documents.py, chunks.py
├── schemas/       cards.py, jobs.py
├── temporal/      workflows.py, activities.py, client.py
└── temporal_worker.py
db/migrations/     SQL-миграции
data/              документы поставщиков
docs/decisions.md  архитектурные решения
tests/
```

## Набор документов

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
