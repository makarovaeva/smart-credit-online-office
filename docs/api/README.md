# API v1 (черновик)

Спецификация: [`openapi.json`](openapi.json). Swagger UI — http://localhost:8000/docs.

Реализованы:
- вход клиента и сотрудника;
- каталог продуктов;
- CRUD заявок и все команды смены статуса;
- очереди, карточка и назначение в бэкофисе;
- `/companies/lookup` на моке ЕГРЮЛ (демо-ИНН — в [`../external-sources.md`](../external-sources.md)).

Остальные эндпоинты пока заглушки (`501`), но контракт зафиксирован: `/products/match`, привязка компаний, документы и ответы на дозапросы, `/notifications`.

Этапы конвейера ИИ запускаются сразу после команд клиента. `/consents` возвращает заявку уже в `pre_approved`. `/submit` возвращает её в `underwriter_review`, `analyst_escalation`, `need_additional_data` или `closed` (автоотказ). Подробно — [`../application-lifecycle.md`](../application-lifecycle.md#кредитный-конвейер).

Спека генерируется из кода (Pydantic-схемы + роутеры FastAPI). После изменения API:

```bash
cd backend && uv run python -m scripts.export_openapi
```

Тест `tests/test_openapi.py` падает, если `openapi.json` отстал от кода.

## Соглашения

- Префикс `/api/v1`, авторизация `Authorization: Bearer <JWT>`. Токен HS256, секрет `JWT_SECRET`, срок жизни 12 часов. Регистрации нет, демо-учётки — в корневом README.
  - Клиент получает токен через `POST /auth/login/phone`: только номер телефона, без пароля и SMS, потому что по условиям кейса он уже клиент банка. Номер нормализуется: `8 (999) 123-45-67` = `+79991234567`.
  - Сотрудник — через `POST /auth/login`: логин (email) и пароль. Клиентам этот вход недоступен.
- `/applications/*` доступны только роли `client`, остальным — `403`. Клиент видит заявки только тех компаний, в которых состоит.
- Бэкофис: заявка назначается автоматически при входе на этап.
  - На `analyst_escalation` — аналитику, на `underwriter_review` — андеррайтеру.
  - Сначала тому, кто уже работал с заявкой, иначе — наименее загруженному сотруднику роли.
  - Сотрудник видит «свои» заявки: назначенные на него и те, где есть его действие в истории. Чужие — `404`.
  - Решение по заявке принимает только её исполнитель, иначе `403`.
  - Администратор видит все заявки.
- Ошибки бизнес-правил: `422` — данные не проходят правила (лимиты продукта, не все согласия, нет данных залога, у решения андеррайтера не хватает полей), `409` — действие недопустимо в текущем статусе.
- `PATCH /applications/{id}`: сумма, срок, цель и продукт меняются только в `draft` / `pre_approved`; финансовые показатели и залог — ещё и в `need_additional_data`. Нужна текущая `version`, иначе `409`. Если `has_collateral=false`, поля залога очищаются.
- Принятие оффера, подписание и выдача — симуляция.
  - `offer/accept` готовит договор с графиком и доводит заявку до `e_sign`.
  - `sign` подписывает, открывает ссудный счёт, зачисляет средства и доводит заявку до `completed`. Код подтверждения не сверяется.
  - Повторные вызовы идемпотентны и возвращают текущее состояние. Прерванную выдачу доводит повторный `sign`.
  - Подробно — [`../application-lifecycle.md`](../application-lifecycle.md#договор-и-выдача-симуляция).
- Ошибки: `{"detail": "..."}`. `404` — нет объекта или нет доступа к нему (не раскрываем существование чужих заявок), `409` — действие недопустимо в текущем статусе или устарела `version`, `422` — ошибка валидации.
- Деньги — строкой (`"1500000.00"`), даты — ISO 8601 с таймзоной.
- Списки — `limit`/`offset`, ответ `{items, total, limit, offset}`.
- Смена статуса — отдельными командами (`/consents`, `/submit`, `/offer/accept`, ...), а не `PATCH status`: так каждое действие валидируется машиной состояний и попадает в аудит. Статусы описаны в [`../application-lifecycle.md`](../application-lifecycle.md).
- `ApplicationRead.available_actions` — что клиенту можно сделать сейчас; фронт не дублирует логику статусов.
- `ApplicationRead.client_status` — статус глазами клиента («Заявка создана», «Идет рассмотрение», «Контр-предложение», ...); внутренние этапы банка клиенту не показываются.

## Эндпоинты

### Клиент

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/auth/login/phone` | Вход клиента по номеру телефона |
| GET | `/me` | Пользователь и его компании |
| GET | `/products` | Каталог продуктов |
| POST | `/products/match` | Подбор продукта под цель, сумму и срок |
| GET | `/companies/lookup?inn=` | Реквизиты и учредители из ЕГРЮЛ/ЕГРИП (мок) для предзаполнения |
| POST/GET | `/companies` | Привязать компанию / мои компании |
| POST/GET | `/applications` | Создать черновик / мои заявки |
| GET/PATCH | `/applications/{id}` | Заявка / редактирование черновика |
| POST/GET | `/applications/{id}/consents` | Согласия на получение данных: `draft → data_collection` |
| GET | `/applications/{id}/pre-approval` | Предварительный лимит |
| POST | `/applications/{id}/pre-approval/decline` | Не продолжать: `pre_approved → closed` |
| POST | `/applications/{id}/submit` | Подать заявку: `pre_approved → submitted` |
| GET | `/applications/{id}/history` | Таймлайн статусов |
| POST/GET/DELETE | `/applications/{id}/documents[...]` | Документы |
| GET | `/applications/{id}/info-requests` | Дозапросы (от ИИ или андеррайтера) |
| POST | `/applications/{id}/info-requests/{rid}/answer` | Ответить: `need_additional_data → ai_verification` (дозапрос ИИ) или `→ underwriter_review` (дозапрос андеррайтера) |
| GET | `/applications/{id}/offer` | Оффер или контр-предложение (`decision_type=conditional_approval`) |
| POST | `/applications/{id}/offer/accept`, `/reject` | Принять / отказаться от оффера |
| POST | `/applications/{id}/sign` | Подписание и выдача (симуляция): `e_sign → disbursement → completed` |
| GET | `/applications/{id}/contract` | Кредитный договор и график платежей (после принятия оффера) |
| GET | `/loans`, `/loans/{id}` | Раздел «Кредиты»: договоры с остатком долга, ближайшим платежом и графиком |
| GET | `/notifications`, POST `/notifications/{id}/read` | Уведомления в кабинете |

### Банк

| Метод | Путь | Роль | Назначение |
|---|---|---|---|
| POST | `/auth/login` | аналитик, андеррайтер, админ | Вход по логину и паролю |
| GET | `/backoffice/applications` | аналитик, андеррайтер, админ | Свои заявки, старые первыми; фильтры `status` (несколько значений) и `risk_zone` |
| GET | `/backoffice/applications/{id}` | аналитик, андеррайтер, админ | Карточка своей заявки: компания, учредители, проверки, метрики, скоринг, AI Credit Memo, решения, история |
| POST | `/backoffice/applications/{id}/assign` | сотрудник этапа, админ | Передать заявку другому сотруднику той же роли |
| POST | `/backoffice/applications/{id}/analyst-conclusion` | аналитик | Заключение: `analyst_escalation → analyst_completed → underwriter_review` |
| POST | `/backoffice/applications/{id}/decision` | андеррайтер | Одно из 4 решений. `more_information_required` с `more_info_target`: `client` — дозапрос документов, `credit_analyst` — запрос экспертизы. `conditional_approval` с `alternative_offer` берёт условия варианта из AI Credit Memo |

Этапы `data_collection`, `ai_*`, `decision_routing` (включая автоотказ по стоп-фактору), `contract_generation`, `disbursement` двигает конвейер, публичных эндпоинтов для них нет. Внешние источники (ЕГРЮЛ, ФНС, БКИ, комплаенс) — внутренние модули-моки на профилях заёмщиков (формат Borrower Profile из [`../credit_mmb_data_model_updated.md`](../credit_mmb_data_model_updated.md)) в `app/integrations/`, описаны в [`../external-sources.md`](../external-sources.md).

## Открытые вопросы

Пороги, не заданные в кредитной политике на доске:

1. Числовой порог кредитного рейтинга.
2. Лимит исполнительных производств.
3. Срок действия оффера (`valid_until`).
4. Расхождения на доске, по которым принято решение (см. [`../application-lifecycle.md`](../application-lifecycle.md#допущения-и-неопределённости)): лимит автоодобрения «ИЛИ» против «меньшая из величин», минимальный DSCR 1,1 против 1,2, Debt Burden = 1 / DSCR.
