# smart-credit-online-office

Умный кредитный кабинет предпринимателя — цифровой кредитный конвейер для малого и микробизнеса (Альфа-Хак 2026).

## Структура репозитория

```
backend/    Python API (FastAPI, SQLAlchemy 2 async, Alembic, PostgreSQL)
  app/
    api/           HTTP-роутеры (версионируются: api/v1)
    core/          конфигурация
    db/            engine, сессии, Base
    models/        ORM-модели
    schemas/       Pydantic-схемы запросов/ответов
    services/      бизнес-логика (конвейер, скоринг, кредитное решение)
    integrations/  моки внешних сервисов (БКИ, ЕГРЮЛ/ЕГРИП, ФНС)
  migrations/      миграции Alembic
  tests/
frontend/   веб-клиент
infra/      docker-compose и окружение
docs/       архитектура, API, диаграмма состояний, модель данных
```

## Запуск

```bash
cd infra
cp .env.example .env
docker compose up --build
```

API: http://localhost:8000, Swagger: http://localhost:8000/docs

## Локальная разработка backend

Требуется [uv](https://docs.astral.sh/uv/), Python 3.12.

```bash
cd backend
uv sync
uv run pytest
uv run ruff check .
uv run uvicorn app.main:app --reload
```

Тесты API работают с отдельной базой Postgres: схема накатывается миграциями, каждый тест откатывается. Без `TEST_DATABASE_URL` эти тесты пропускаются.

```bash
docker run -d --rm --name sco-pg-test -e POSTGRES_USER=credit -e POSTGRES_PASSWORD=credit \
  -e POSTGRES_DB=credit_test -p 55432:5432 postgres:16-alpine
TEST_DATABASE_URL=postgresql+asyncpg://credit:credit@localhost:55432/credit_test uv run pytest
```
