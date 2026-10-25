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
    integrations/  моки внешних сервисов (ЕГРЮЛ/ЕГРИП, ФНС, БКИ, комплаенс)
  migrations/      миграции Alembic
  scripts/         демо-данные, запуск контейнера, экспорт OpenAPI
  tests/
frontend/   веб-клиент
data/       датасет профилей заёмщиков от ML (монтируется в backend)
docs/       архитектура, API, диаграмма состояний, модель данных
docker-compose.yml, .env.example   единый запуск решения
```

## Запуск

Нужен только Docker с Compose v2. Из корня репозитория:

```bash
cp .env.example .env    # необязательно: без .env работают значения по умолчанию
docker compose up --build
```

- API: http://localhost:8000, Swagger: http://localhost:8000/docs
- Клиентский кабинет: http://localhost:3000 (вход — `/login`)
- PostgreSQL: `localhost:5432` (`credit` / `credit`)

Если порты заняты, поменяйте `BACKEND_PORT` и `POSTGRES_PORT` в `.env`.

При старте backend накатывает миграции и загружает демо-данные (`scripts/seed.py`, идемпотентно; отключается `SEED_DEMO_DATA=false`). Данные БД хранятся в volume `postgres_data`. Начать с чистой базы: `docker compose down -v`.

Датасет профилей заёмщиков от ML кладётся в `data/` и подключается переменной `BORROWER_DATASET_PATH` (см. [`data/README.md`](data/README.md)).

**Фиксация версий:**
- зависимости backend — `backend/uv.lock`; образ собирается с `uv sync --locked`, поэтому сборка падает, если lock отстал от `pyproject.toml`;
- базовые образы — точные теги: `python:3.12.15-slim`, `postgres:16.15-alpine`;
- `uv` — `0.13.5`.

Frontend включён в Docker Compose. ML-сервис пока представлен шаблоном в комментариях.

## Разработка frontend

Стек: Next.js App Router, TypeScript, Tailwind CSS, shadcn/ui. Версии зависимостей
зафиксированы в `frontend/package.json` и `frontend/package-lock.json`; Node — в `.nvmrc` и Dockerfile.

Для разработки с горячим обновлением остановите Docker-сервис frontend, если он запущен.
БД и API можно оставить через `docker compose up --build -d backend`, затем:

```bash
cd frontend
npm ci
npm run dev
```

Откройте http://localhost:3000/login. Разделы клиента: `/applications`, `/chat`,
`/documents`, `/credits`, `/profile`. Входы сотрудников: `/staff/login?role=analyst`,
`/staff/login?role=underwriter`, `/staff/login?role=admin`. Кабинеты:
`/staff/analyst`, `/staff/underwriter`, `/staff/admin`.

Frontend подключён к API: реальные входы, заявки, согласия, подача, статусы,
очереди сотрудников, заключение аналитика, решения андеррайтера, офферы, подпись,
договор и график. JWT хранится в HttpOnly cookie; данные запрашиваются через
Next BFF. Статусы опрашиваются с backend, демонстрационных таймеров больше нет.
Старые HTML-имена нормализуются в браузере, в ссылках интерфейса их нет.

Чат и часть методов документов, дозапросов и профиля ещё не реализованы на backend.
Они показаны как недоступные, без симуляции успеха. Доработки выполняет backend-команда.
Точный статус и проверенные цепочки: `docs/frontend-api-status.md`.
Список для команды: `docs/backend-integration-requests.md`.
Расхождения макета и API перечислены в `docs/frontend-backend-gaps.md`.

Проверки: `npm run typecheck` и `npm run build` из `frontend/`.
Подробнее — `frontend/README.md`.

## Демо-доступ

Регистрации нет: по условиям кейса пользователь уже клиент банка, а учётные записи сотрудников заведены заранее.

**Клиенты** входят по номеру телефона, без пароля и SMS: `POST /api/v1/auth/login/phone`.

| Телефон | Компания (ИНН) | Что произойдёт с заявкой на оборотный кредит |
|---|---|---|
| `+7 999 000-00-01` | `7701000001` | Здоровая компания: андеррайтеру, одобрение |
| `+7 999 000-00-02` | `7701000018` | 5 млн — пограничный риск: контр-предложение с вариантами |
| `+7 999 000-00-03` | `7701000002` | Действующее банкротство: автоотказ |
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
