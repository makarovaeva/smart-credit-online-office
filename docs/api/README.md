# API v1 (черновик)

Спецификация: [`openapi.json`](openapi.json) и [`openapi.yaml`](openapi.yaml) (OpenAPI 3.1). Swagger UI — http://localhost:8000/docs, ReDoc — http://localhost:8000/redoc.

Postman-коллекция с примерами запросов и сквозными сценариями — [`../postman/`](../postman/README.md).

Реализованы:
- вход клиента и сотрудника;
- каталог продуктов;
- CRUD заявок и все команды смены статуса;
- очереди, карточка и назначение в бэкофисе;
- `/companies/lookup` на моке ЕГРЮЛ (демо-ИНН — в [`../external-sources.md`](../external-sources.md)).

Все объявленные эндпоинты реализованы.

Этапы конвейера ИИ запускаются сразу после команд клиента. `/consents` возвращает заявку уже в `pre_approved`. `/submit` возвращает её в `underwriter_review`, `analyst_escalation`, `need_additional_data` или `closed` (автоотказ). Подробно — [`../application-lifecycle.md`](../application-lifecycle.md#кредитный-конвейер).

Спека генерируется из кода (Pydantic-схемы + роутеры FastAPI). После изменения API:

```bash
cd backend && uv run python -m scripts.export_openapi
```

Тест `tests/test_openapi.py` падает, если `openapi.json` или `openapi.yaml` отстали от кода, а также если спека не проходит валидацию (`openapi-spec-validator`).

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
| POST | `/products/match` | Подбор продукта под цель, сумму и срок: подходящие первыми, пояснения (`notes`), ставка и примерный платёж |
| GET | `/companies/lookup?inn=` | Реквизиты, руководитель и учредители из ЕГРЮЛ/ЕГРИП (мок) для предзаполнения |
| POST/GET | `/companies` | Привязать компанию по ИНН (реквизиты — из реестра; уже обслуживаемая компания — `409`) / мои компании с ролью |
| GET | `/companies/{id}` | Профиль компании: организация и деятельность (ОКВЭД, система налогообложения), руководитель, бенефициары с долями, право подписи (`signatories`), телефон, e-mail, расчётный счёт. Чужая — `404` |
| POST/GET | `/applications` | Создать черновик / мои заявки |
| GET/PATCH | `/applications/{id}` | Заявка / редактирование черновика |
| POST/GET | `/applications/{id}/consents` | Согласия на получение данных: `draft → data_collection` |
| GET | `/applications/{id}/pre-approval` | Предварительный лимит |
| POST | `/applications/{id}/pre-approval/decline` | Не продолжать: `pre_approved → closed` |
| POST | `/applications/{id}/submit` | Подать заявку: `pre_approved → submitted` |
| POST | `/applications/{id}/cancel` | Отменить до решения банка: `→ closed`, `close_reason=client_cancelled`. У компании одна заявка в работе: `POST /applications` при незавершённой — `409` |
| GET | `/applications/{id}/history` | Таймлайн статусов |
| POST/GET | `/applications/{id}/documents` | Загрузить (multipart: `file`, `type`, необязательный `info_request_id`) / список. Загрузка — в `draft`, `pre_approved`, `need_additional_data` |
| GET | `/applications/{id}/documents/{doc}/content` | Скачать файл |
| DELETE | `/applications/{id}/documents/{doc}` | Удалить ещё не проверенный документ на этапе загрузки |
| GET | `/applications/{id}/info-requests` | Дозапросы от ИИ, аналитика или андеррайтера (`requested_by`) |
| POST | `/applications/{id}/info-requests/{rid}/answer` | Ответить; когда закрыты все дозапросы, заявка возвращается к инициатору: `ai_verification` (конвейер продолжается), `analyst_escalation` или `underwriter_review` |
| GET | `/applications/{id}/offer` | Оффер или контр-предложение (`decision_type=conditional_approval`) |
| POST | `/applications/{id}/offer/accept`, `/reject` | Принять / отказаться от оффера |
| POST | `/applications/{id}/sign` | Подписание и выдача (симуляция): `e_sign → disbursement → completed` |
| GET | `/applications/{id}/contract` | Кредитный договор и график платежей (после принятия оффера) |
| GET | `/applications/{id}/contract/document` | Договор с графиком в PDF (до подписания — проект; документ демонстрационный) |
| GET | `/applications/{id}/contract/schedule-export?format=xlsx\|pdf` | График платежей: XLSX (числа, даты, итоги формулами) или PDF |
| GET/POST | `/chat/messages` | Диалог с ИИ-агентом (`company_id`, необязательный `application_id`). POST возвращает пару: сообщение клиента и ответ агента. Если из текста разобраны параметры кредита — `confirmation_card` с суммой, сроком, целью, залогом и продуктом. Ещё агент отвечает о статусе, документах, оффере, отказе и продуктах. `client_message_id` защищает от дублей, `generated_by`: `rules` или `llm:<модель>`. Агент сам пишет о дозапросе, оффере, отказе, договоре и зачислении |
| GET | `/loans`, `/loans/{id}` | Раздел «Кредиты»: договоры с остатком долга, ближайшим платежом и графиком |
| GET | `/notifications` | Уведомления в кабинете, новые первыми; `unread` — счётчик непрочитанных, `unread_only` — фильтр |
| POST | `/notifications/{id}/read`, `/notifications/read-all` | Отметить прочитанным |

### Банк

| Метод | Путь | Роль | Назначение |
|---|---|---|---|
| POST | `/auth/login` | аналитик, андеррайтер, админ | Вход по логину и паролю |
| GET | `/backoffice/applications` | аналитик, андеррайтер, админ | Свои заявки, старые первыми; фильтры `status` (несколько значений) и `risk_zone` |
| GET | `/backoffice/applications/{id}` | аналитик, андеррайтер, админ | Карточка своей заявки: компания, учредители, проверки, метрики, скоринг, AI Credit Memo, решения, история |
| POST | `/backoffice/applications/{id}/assign` | сотрудник этапа, админ | Передать заявку другому сотруднику той же роли |
| POST | `/backoffice/applications/{id}/analyst-conclusion` | аналитик | Заключение: `analyst_escalation → analyst_completed → underwriter_review` |
| POST | `/backoffice/applications/{id}/info-requests` | аналитик (исполнитель) | Запрос документов у клиента через ИИ: `analyst_escalation → need_additional_data`, после ответа — обратно к аналитику |
| GET | `/backoffice/applications/{id}/documents/{doc}/content` | аналитик, андеррайтер, админ | Скачать файл документа своей заявки |
| POST | `/backoffice/applications/{id}/internal-requests/{rid}/accept`, `/return` | аналитик (исполнитель) | Запрос экспертизы андеррайтера: принять в работу / вернуть с комментарием (`→ underwriter_review`) |
| POST | `/backoffice/applications/{id}/internal-requests/{rid}/cancel`, `/remind` | андеррайтер (автор) | Отозвать запрос экспертизы (`→ underwriter_review`) / напомнить аналитику |
| POST | `/backoffice/applications/{id}/info-requests/{rid}/cancel`, `/remind` | инициатор дозапроса | Отозвать дозапрос клиенту (возврат заявки к инициатору) / напомнить клиенту через ИИ-агента |
| GET | `/backoffice/applications/{id}/contract/document`, `/contract/schedule-export` | аналитик, андеррайтер, админ | Те же выгрузки по своей заявке |
| POST | `/backoffice/applications/{id}/contract` | аналитик (исполнитель) | Подготовка договора: `contract_generation → e_sign`. Нужна при `CONTRACT_PREPARATION=analyst`, в режиме `auto` договор готовится сам |
| POST | `/backoffice/applications/{id}/decision` | андеррайтер | Одно из 4 решений. `more_information_required` с `more_info_target`: `client` — дозапрос документов, `credit_analyst` — запрос экспертизы. `conditional_approval` с `alternative_offer` берёт условия варианта из AI Credit Memo |

Этапы `data_collection`, `ai_*`, `decision_routing` (включая автоотказ по стоп-фактору), `contract_generation`, `disbursement` двигает конвейер, публичных эндпоинтов для них нет. Внешние источники (ЕГРЮЛ, ФНС, БКИ, комплаенс) — внутренние модули-моки на профилях заёмщиков (формат Borrower Profile из [`../credit_mmb_data_model_updated.md`](../credit_mmb_data_model_updated.md)) в `app/integrations/`, описаны в [`../external-sources.md`](../external-sources.md).

## Открытые вопросы

Пороги, не заданные в кредитной политике на доске:

1. Числовой порог кредитного рейтинга.
2. Лимит исполнительных производств.
3. Срок действия оффера (`valid_until`).
4. Расхождения на доске, по которым принято решение (см. [`../application-lifecycle.md`](../application-lifecycle.md#допущения-и-неопределённости)): лимит автоодобрения «ИЛИ» против «меньшая из величин», минимальный DSCR 1,1 против 1,2.
