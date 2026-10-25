# Тестовые сценарии

Сценарии проверки продукта на демо-данных: что сделать, что должно получиться и каким автотестом это покрыто. Демо-учётки создаёт `backend/scripts/seed.py` при старте backend. Список демо-ИНН — в [`external-sources.md`](external-sources.md).

## Как запускать

| Уровень | Команда | Что проверяет |
|---|---|---|
| Unit и API (pytest) | `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://… uv run pytest` | Политика, скоринг, машина состояний, все эндпоинты на реальной БД, транзакция на тест. Без `TEST_DATABASE_URL` тесты с БД пропускаются |
| API на стенде (Newman) | `docker run --rm -v "$PWD/docs/postman":/etc/newman postman/newman:6-alpine run smart-credit.postman_collection.json -e smart-credit.local.postman_environment.json --env-var baseUrl=http://host.docker.internal:8000/api/v1` | Сквозные сценарии через HTTP на поднятом `docker compose`. Повторный прогон на той же базе работает: в начале сценариев закрываются незавершённые заявки прошлых прогонов |
| UI (headless Chrome) | `node frontend/scripts/check-connected.mjs` при Chrome с `--remote-debugging-port=9223` и отдельным профилем | Клики по реальному интерфейсу против поднятого стенда |

## Учётки

| Кто | Вход | Компания (ИНН) |
|---|---|---|
| Клиент 1 | `+7 999 000-00-01` | `7701000001` — здоровая компания |
| Клиент 2 | `+7 999 000-00-02` | `7701000018` — пограничный риск по DSCR |
| Клиент 3 | `+7 999 000-00-03` | `7701000002` — действующее банкротство |
| Клиент 4 | `+7 999 000-00-04` | `7701000007` — бизнесу 7 месяцев |
| Клиент 5 | `+7 999 000-00-05` | `770100000001` — ИП |
| Клиент 6 | `+7 999 000-00-06` | `7701000019` — счёт в другом банке |
| Аналитики | `analyst1@alfa-demo.ru`, `analyst2@alfa-demo.ru` | пароль `demo-password` |
| Андеррайтеры | `underwriter1@alfa-demo.ru`, `underwriter2@alfa-demo.ru` | пароль `demo-password` |
| Администратор | `admin@alfa-demo.ru` | пароль `demo-password` |

## Клиентский путь

| № | Сценарий | Шаги | Ожидаемый результат | Автотесты |
|---|---|---|---|---|
| 1 | Одобрение и выдача | Клиент 1: чат «3 млн на 2 года на оборотку» → подтвердить → андеррайтер одобряет → принять оффер → подписать | Карточка агента с продуктом; заявка у андеррайтера (зелёная зона); оффер; договор и график из 24 платежей; `completed`, кредит в «Кредитах»; в чате и уведомлениях — оффер, договор, зачисление | Newman «1. Happy path»; UI-тест; `test_approval_to_disbursement`, `test_green_zone_goes_to_underwriter`, `test_sign_disburses_and_is_idempotent` |
| 2 | Контр-предложение | Клиент 2: 5 млн на 24 мес. → андеррайтер выбирает вариант «дольше срок» | В AI Credit Memo — контр-предложение продлением срока и альтернативы; клиент видит `counter_offer` на 5 млн | Newman «2. Контр-предложение»; `test_low_dscr_extends_term`, `test_underwriter_picks_alternative_offer` |
| 3 | Автоотказ | Клиент 3 подаёт заявку | `closed`, `auto_declined`; в `decline_reasons` — «Действующее банкротство» и совет; сообщение агента в чате | Newman «3. Автоотказ»; UI-тест; `test_stop_factor_is_auto_declined`, `test_auto_decline_is_explained` |
| 4 | Все стоп-факторы | Заявки по ИНН `7701000002`–`06`, `09`, `13`–`15`, `17` | Красная зона и автоотказ по соответствующему стоп-фактору | `test_stop_factor_scenarios`, `test_all_stop_factors_come_from_profile` |
| 5 | Эскалация аналитику | Клиент 4 подаёт заявку → аналитик пишет заключение | `analyst_escalation` → заключение → `underwriter_review` у андеррайтера | Newman «4. Эскалация»; UI-тест; `test_young_business_goes_to_analyst` |
| 6 | Дозапрос ИИ | Клиент 6 подаёт заявку → загружает выписку → отвечает | `need_additional_data`, дозапрос выписки в чате; после ответа конвейер продолжается до `underwriter_review`; андеррайтер скачивает файл | Newman «5. Документы и дозапрос»; `test_ai_requests_bank_statement_and_resumes_pipeline` |
| 7 | Документы до подачи | Клиент 6 загружает выписку до подачи, затем подаёт | Дозапроса нет, заявка сразу у андеррайтера | `test_document_uploaded_before_submit_completes_set` |
| 8 | Залог | Заявка с залогом (транспорт) | ИИ запрашивает ПТС | `test_collateral_requires_title_document` |
| 9 | Отказ от предварительного расчёта | Клиент закрывает заявку на `pre_approved` | `closed`, `pre_approval_declined` | `test_decline_pre_approval_closes` |
| 10 | Отказ от оффера | Клиент отклоняет оффер | `closed`, `offer_rejected`; подписать нельзя (409) | `test_counter_offer_rejected`, `test_sign_before_accept_and_after_reject` |
| 11 | Отмена и одна заявка в работе | Создать вторую заявку при незавершённой → отменить первую → создать снова | 409 с номером текущей; после отмены `client_cancelled`, новая создаётся; после оффера отмена — 409 | Newman «6. Ошибки»; `test_one_active_application_and_cancel`, `test_cannot_cancel_after_offer` |
| 12 | Профиль компании | Клиент 1 открывает «Профиль компании» | Реквизиты, ОКВЭД, налогообложение, руководитель, бенефициары, подписанты, контакты, расчётный счёт | Newman; UI-тест; `test_link_company_builds_profile` |
| 13 | Чат с ИИ-агентом | Вопросы «Какой статус?», «Какие документы нужны?», «Почему отказ?» | Ответы по данным заявки; при `LLM_BASE_URL` текст формулирует модель, при её недоступности — шаблон | `test_chat.py` |
| 14 | Подбор продукта | `POST /products/match` с целью, суммой и сроком | Подходящие первыми, пояснения, примерный платёж | Newman; `test_product_match` |

## Работа банка

| № | Сценарий | Шаги | Ожидаемый результат | Автотесты |
|---|---|---|---|---|
| 15 | Очереди и назначение | Несколько заявок у андеррайтеров | Назначаются наименее загруженному; сотрудник видит свои; исполнитель получает уведомление | `test_assigned_to_least_loaded_and_queues_are_separate`, `test_notifications_for_client_and_assignee` |
| 16 | Дозапрос андеррайтера | Андеррайтер: `more_information_required` → клиент → клиент загружает КУДИР и отвечает | Заявка возвращается тому же андеррайтеру | `test_underwriter_request_returns_to_underwriter` |
| 17 | Запрос документов аналитиком | Аналитик в UI «Запросить документы через ИИ-агента» → клиент загружает и отвечает | Заявка возвращается к аналитику, он скачивает файл | UI-тест; `test_analyst_request_returns_to_analyst` |
| 18 | Запрос экспертизы | Андеррайтер запрашивает экспертизу → аналитик принимает в работу → заключение или возврат с комментарием; андеррайтер может напомнить или отозвать | Вкладка «Запросы от андеррайтера»; заключение закрывает запрос; возврат и отзыв ведут в `underwriter_review` | `test_expertise_request_accept_and_return`, `test_expertise_request_cancel_remind_and_conclusion` |
| 19 | Напоминание и отзыв дозапроса | Инициатор дозапроса напоминает клиенту, затем отзывает | Сообщение агента в чате и уведомление; после отзыва заявка у инициатора | `test_info_request_remind_and_cancel` |
| 20 | Договор готовит аналитик | `CONTRACT_PREPARATION=analyst`: клиент принимает оффер → аналитик готовит договор | Заявка ждёт на `contract_generation`, после команды — `e_sign` | `test_contract_prepared_by_analyst` |
| 21 | Передача заявки | Андеррайтер передаёт заявку коллеге | Новый исполнитель видит заявку и получает уведомление | `test_reassign` |

## Надёжность и ограничения

| № | Сценарий | Ожидаемый результат | Автотесты |
|---|---|---|---|
| 22 | ML-сервис недоступен | Скоринг по правилам, пометка в `model_version`, сценарий не прерывается | `test_falls_back_to_rules`; вручную: `docker compose stop ml` |
| 23 | Не ответил внешний источник | Ответ сохранён как ошибка, эскалация аналитику | `test_unavailable_source_is_saved_and_escalated` |
| 24 | Сбой конвейера | Команда клиента сохранена, заявка на прежнем этапе | `test_pipeline_failure_keeps_client_command` |
| 25 | Повтор выдачи | Прерванная выдача доводится повторным `sign`, двойной выдачи нет | `test_failed_disbursement_can_be_retried` |
| 26 | Повтор сообщения в чате | Тот же `client_message_id` не создаёт дубль | `test_repeat_with_same_key_is_not_duplicated` |
| 27 | Доступ | Без токена 401, клиент в бэкофисе 403, чужая заявка, документ, компания или чат — 404 | Newman «6. Ошибки»; `test_foreign_application_is_hidden`, `test_documents_of_other_company_are_hidden`, `test_chat_access` |
| 28 | Файлы | Неподдерживаемый формат, подмена расширения, пустой файл, превышение размера — 422 | `test_upload_rejects_bad_files`, `test_upload_size_limit` |
| 29 | Конкурентное изменение | Устаревшая `version` при редактировании — 409 | `test_update_draft_with_optimistic_lock` |
| 30 | Контракт API | OpenAPI актуален и валиден, все запросы Postman есть в OpenAPI | `test_exported_spec_is_up_to_date`, `test_spec_is_valid_openapi`, `test_every_request_exists_in_openapi` |
