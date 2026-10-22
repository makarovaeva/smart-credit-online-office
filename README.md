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

При старте контейнер накатывает миграции и загружает демо-данные (`python -m scripts.seed`, идемпотентно).

## Демо-доступ

Регистрации нет: по условиям кейса пользователь уже клиент банка, а учётные записи сотрудников заведены заранее.

**Клиенты** входят по номеру телефона, без пароля и SMS: `POST /api/v1/auth/login/phone`.

| Телефон | Компания (ИНН) | Что произойдёт с заявкой на оборотный кредит |
|---|---|---|
| `+7 999 000-00-01` | `7701000001` | Здоровая компания: андеррайтеру, одобрение |
| `+7 999 000-00-02` | `7712345678` | 5 млн — долговая нагрузка выше 50%: контр-предложение с вариантами |
| `+7 999 000-00-03` | `7701000002` | Компания недействующая: автоотказ |
| `+7 999 000-00-04` | `7701000007` | Бизнесу 7 месяцев: к кредитному аналитику |
| `+7 999 000-00-05` | `770100000001` | ИП, здоровый бизнес |

**Сотрудники** входят по логину и паролю: `POST /api/v1/auth/login`, пароль у всех `demo-password`.

| Логин | Роль |
|---|---|
| `analyst1@alfa-demo.ru`, `analyst2@alfa-demo.ru` | Кредитный аналитик |
| `underwriter1@alfa-demo.ru`, `underwriter2@alfa-demo.ru` | Андеррайтер |
| `admin@alfa-demo.ru` | Администратор: видит все заявки |

Заявка назначается автоматически: в жёлтой зоне — аналитику, на рассмотрение — андеррайтеру. Каждый сотрудник видит свои заявки в `GET /api/v1/backoffice/applications` с фильтром `?status=`.

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
