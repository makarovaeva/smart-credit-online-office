# Кредитный кабинет — frontend

Next.js App Router + TypeScript. Основа оформления перенесена из согласованных
HTML-прототипов. Данные и доступные операции загружаются из FastAPI.

## Запуск

Из корня: `docker compose up --build -d`.
Для разработки: оставить БД и backend в Docker, из этой папки выполнить
`npm ci`, затем `npm run dev`. Не запускать Docker frontend и dev на одном порту.
Локальный кабинет: http://localhost:3000.

При необходимости скопировать `.env.example` в `.env.local`.
`API_URL` — серверный адрес FastAPI, по умолчанию `http://127.0.0.1:8000/api/v1`;
в Compose — `http://backend:8000/api/v1`. Токен не передаётся через NEXT_PUBLIC.

## Основные адреса

- `/login`, `/applications`, `/chat`, `/documents`, `/credits`, `/profile`.
- `/staff/login?role=analyst`, `/staff/analyst`.
- `/staff/login?role=underwriter`, `/staff/underwriter`.
- `/staff/login?role=admin`, `/staff/admin`.
- `/staff/admin/applications/{UUID}` — настоящая выбранная заявка.

Старые `.dc.html`-адреса нормализуются в браузере; новых ссылок на них в UI нет.
Этапы определяются API, окна и вкладки — внутренним React-состоянием.
Демо-номера и учётки сотрудников находятся в корневом README.

## Состав

- `src/prototype/routes.ts` — соответствие экранов и публичных маршрутов.
- `screen-view.tsx` — навигация, история браузера и обработка UI-действий.
- `use-bank.ts` — реальные запросы, команды и опрос состояния.
- `bind-bank.ts` — подстановка серверных данных в согласованную разметку.
- `src/app/api` — серверный BFF; JWT хранится в HttpOnly cookie.
- `screens.json` — 82 исходных шаблона семи сценариев, без внешних скриптов.

Tailwind/shadcn установлены; исходный CSS сохранён, чтобы не менять согласованный
вид. API-данные подставляются только через DOM textContent/атрибуты, не исполняются
как HTML. Native таблицы восстановлены из экспортных sc-raw-тегов.

Статус интеграции и доказательства: `../docs/frontend-api-status.md`.
Недостающие серверные методы: `../docs/backend-integration-requests.md`.
Чат и часть методов документов/дозапросов пока не готовы на backend: интерфейс
показывает ограничение, не имитирует успех.

## Проверка

`npm run build` — production build с TypeScript.
`node scripts/check-motion.mjs` — покадровая проверка геометрии клиентских
переходов и снимки desktop/mobile в `.qa/motion`; `--baseline` только фиксирует
исходное состояние. Нужны запущенные frontend/backend и Chrome CDP на 9223.

`node scripts/check-navigation.mjs` — проверка сайдбара клиента и вкладок трёх
кабинетов сотрудников с задержкой API; проверяет отсутствие загрузочного экрана
при переходах и навигации назад/вперёд. Нужен Chrome с CDP на порту 9223.
Заявки не создаёт. Данные кабинета и черновик сохраняются в общем React provider
до выхода; API обновляет их в фоне. При первом открытии остаётся красный индикатор.

`node scripts/check-connected.mjs` — сквозная проверка с отдельным Chrome на
порту 9223. **Создаёт синтетические заявки в локальном backend.**
`--branches` проверяет автоотказ/аналитика с использованием ранее созданного
успешного отчёта. Артефакты сохраняются в `.qa/connected` и не коммитятся.

`scripts/import-prototype.py` и `check-scenario.mjs` относятся к этапу сравнения
исходных UI-шаблонов; старые визуальные снимки описаны в `docs/scenario-N-ui.md`.
Точная фиксация зависимостей: package.json, package-lock.json, .nvmrc, Dockerfile.
