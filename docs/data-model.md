# Модель данных

PostgreSQL 16. Источник правды — ORM-модели в `backend/app/models/`, схема разворачивается миграциями Alembic (`backend/migrations/`).

```mermaid
erDiagram
    users ||--o{ company_members : ""
    companies ||--o{ company_members : ""
    companies ||--o{ company_owners : ""
    companies ||--o{ applications : ""
    users ||--o{ applications : "applicant / assignee"
    credit_products ||--o{ applications : ""
    applications ||--o{ application_consents : ""
    companies ||--o{ chat_messages : "диалог с ИИ-агентом"
    applications ||--o{ internal_requests : "запрос экспертизы"
    applications ||--o{ pre_approvals : ""
    applications ||--o{ application_status_history : ""
    applications ||--o{ info_requests : ""
    applications ||--o{ documents : ""
    info_requests ||--o{ documents : "ответ на дозапрос"
    applications ||--o{ external_checks : ""
    applications ||--o{ scoring_results : ""
    scoring_results ||--o{ credit_memos : ""
    applications ||--o{ credit_memos : ""
    credit_memos ||--o{ credit_decisions : ""
    applications ||--o{ credit_decisions : ""
    users ||--o{ notifications : ""
    applications ||--o{ notifications : ""
    applications ||--o| loan_contracts : ""
    credit_decisions ||--o| loan_contracts : "принятый оффер"
    loan_contracts ||--o{ payment_schedule_items : ""

    users {
        uuid id PK
        string email UK
        string full_name
        string role "client | credit_analyst | underwriter | admin"
    }
    companies {
        uuid id PK
        string inn UK
        string ogrn
        string legal_form "ip | ooo"
        string okved_main
        string tax_system
        date registration_date
        string actual_address
        string head_full_name
        string settlement_account_number
    }
    company_members {
        uuid company_id FK
        uuid user_id FK
        string role "owner | director | accountant | ..."
    }
    company_owners {
        uuid company_id FK
        string full_name
        numeric share_percent
        bool is_beneficiary
        bool has_signing_authority
    }
    credit_products {
        uuid id PK
        string code UK
        string credit_format "loan | credit_line | overdraft"
        array purposes
        numeric min_amount
        numeric max_amount
        numeric base_rate
    }
    applications {
        uuid id PK
        string number UK "CR-2026-000123"
        string status "20 статусов"
        numeric requested_amount
        int requested_term_months
        numeric annual_revenue
        numeric annual_ebitda
        numeric monthly_debt_payments
        string collateral_type
        numeric collateral_market_value
        string collateral_address
        text collateral_encumbrances
        string close_reason "pre_approval_declined | auto_declined | underwriter_declined | offer_rejected"
        int version "optimistic lock"
    }
    application_consents {
        string type "bki | fns | digital_profile"
        uuid granted_by_id FK
    }
    pre_approvals {
        numeric approval_probability
        numeric amount_min
        numeric amount_max
        numeric estimated_rate
        bool collateral_required
        jsonb recommendations
    }
    application_status_history {
        string from_status
        string to_status
        string actor_type "client | system | credit_analyst | underwriter"
    }
    info_requests {
        string requested_by "system | credit_analyst | underwriter"
        string message
        array requested_document_types
        string status "open | answered | cancelled"
    }
    documents {
        string type
        string storage_key UK
        string verification_status "uploaded | verified | rejected"
    }
    external_checks {
        string source "egrul | fns | bki | fssp | bank_turnover | digital_profile"
        string status "pending | success | failed"
        jsonb result
    }
    scoring_results {
        numeric dscr
        numeric debt_burden
        numeric ltv
        int score
        string risk_grade "A..E"
        string risk_zone "green | yellow | red"
        numeric confidence
        numeric fraud_score
        jsonb stop_factors
        jsonb escalation_reasons
    }
    credit_memos {
        text summary
        string ai_recommendation "approve | counter_offer | decline | request_more_info"
        numeric recommended_amount
        jsonb recommended_conditions
        jsonb counter_offer_adjustments
        jsonb alternative_offers
        string analyst_recommendation
        uuid analyst_id FK
        text analyst_conclusion
    }
    credit_decisions {
        string decision_type "approved | conditional_approval | declined | more_information_required"
        uuid decided_by_id FK "андеррайтер"
        string more_info_target "client | credit_analyst"
        numeric approved_amount
        numeric interest_rate
        jsonb conditions
        string client_response "accepted | rejected"
    }
    loan_contracts {
        string contract_number UK "КД-2026-000045"
        string status "awaiting_signature | signed | active | overdue | closed"
        numeric principal_amount
        int term_months
        numeric interest_rate
        numeric monthly_payment
        date maturity_date
        string loan_account_number UK
        string settlement_account_number
        timestamp disbursed_at
    }
    payment_schedule_items {
        int installment_no
        date due_date
        numeric principal_amount
        numeric interest_amount
        numeric balance_after
        string status "scheduled | paid | overdue"
    }
    internal_requests {
        uuid from_user_id FK
        string status "open | accepted | completed | returned | cancelled"
        text message
        text response_comment
    }
    chat_messages {
        string sender_type "client | ai_agent"
        string message_type "text | confirmation_card | document_request | status_notification | rejection_notice"
        jsonb card_payload
        string client_message_id
        string generated_by "rules | llm:<модель>"
    }
    notifications {
        string type
        string title
        timestamp read_at
    }
```

## Ключевые решения

| Решение | Почему |
|---|---|
| UUID в качестве PK + отдельный человекочитаемый `applications.number` из sequence | UUID не раскрывает объём заявок и безопасен для API; номер нужен клиенту и сотруднику для общения |
| Enum как `varchar + CHECK`, а не нативный `ENUM` Postgres | Добавление статуса/типа не требует `ALTER TYPE` и не блокирует таблицу; целостность сохраняется на уровне БД |
| Деньги — `numeric(15,2)`, в API — строка | Без потерь точности float |
| `scoring_results` → `credit_memos` → `credit_decisions` | По политике рекомендация ИИ отделена от финального решения: скоринг даёт метрики и зону, Credit Memo — рекомендацию ИИ и вывод аналитика, решение всегда за андеррайтером |
| DSCR, Debt Burden, LTV, зона и confidence — отдельные колонки (Debt Burden только аналитический) | По ним работает маршрутизация и фильтрация очереди бэкофиса; остальные метрики — в `metrics` (JSONB) |
| `stop_factors`, `escalation_reasons`, `factors` в JSONB | Объяснимость: андеррайтер видит, почему заявка ушла к аналитику или в автоотказ и что повлияло на оценку |
| `credit_memos.counter_offer_adjustments` | Контр-предложение ИИ по сценариям политики (лимит, срок, LTV, риск-надбавка): что и почему изменилось относительно запроса |
| `credit_memos.analyst_recommendation` отдельно от `ai_recommendation` | Андеррайтер видит и вывод ИИ, и вывод аналитика; скорректированные аналитиком условия пишутся в `recommended_*` |
| `created_at` / `updated_at` ставятся в Python (`server_default` — запасной) | Значение доступно сразу после flush без повторного запроса (в async ленивая загрузка невозможна); переходы одной транзакции упорядочены в истории |
| `info_requests.requested_by` | После ответа клиента заявка возвращается к инициатору дозапроса: ИИ, аналитику или андеррайтеру |
| `documents.verification_status`, файлы вне БД | Проверенный ИИ документ клиент удалить не может; содержимое — в файловом хранилище (`DOCUMENT_STORAGE_DIR`), ключ формирует backend |
| `credit_decisions.more_info_target` | У «нужны данные» два возвратных маршрута: документы от клиента или экспертиза аналитика |
| `applications.close_reason` — enum | Четыре пути к финалу «Закрыто без выдачи» с доски; клиенту показывается причина |
| `collateral_address`, `collateral_encumbrances`, `pre_approvals.collateral_required` | Консультация с залогом уточняет адрес и обременения; предварительный расчёт показывает необходимость обеспечения |
| `collateral_type` + `collateral_market_value` | Дисконт для LTV зависит от типа залога (коммерческая недвижимость 0,2–0,3 … товар в обороте 0,5–0,7) |
| `annual_ebitda` | Входит в DSCR = EBITDA / Debt Service и Debt Burden |
| `application_consents` | Без согласий на БКИ/ФНС/цифровой профиль ИИ не начинает сбор данных (этап Draft) |
| `pre_approvals` | Клиент видит шансы и диапазон до подачи — ключевой запрос персоны «новый заёмщик» |
| `company_owners` | Проверка собственников по санкционным спискам и основание эскалации «сложная структура владения» |
| Сырые ответы внешних источников в `external_checks.result` (JSONB) | Контракты моков могут меняться; сохраняется доказательная база для решения |
| Профиль компании — снимок в `companies` / `company_owners` (`services/companies.sync_company`) | Реквизиты, руководитель и учредители — из (мока) ЕГРЮЛ, контакты и расчётный счёт — данные клиента банка; снимок обновляется при привязке и запуске сида, фактический адрес и число сотрудников от клиента не затираются. `company_owners.has_signing_authority` + `head_has_signing_authority` дают список подписантов |
| `chat_messages` у компании, `application_id` — необязательный | Диалог начинается до заявки (подбор параметров); при создании черновика сообщения без заявки привязываются к нему. Уникальный `(company_id, client_message_id)` защищает от дублей при повторе запроса; `generated_by` показывает, кто сформулировал ответ — шаблоны или LLM |
| `internal_requests` отдельно от `info_requests` | Запрос экспертизы андеррайтера у аналитика — внутренний, клиент его не видит; у него свой цикл (принят, закрыт заключением, возвращён, отозван) и он разделяет вкладки очереди аналитика |
| `users.phone` уникален | Клиент входит по номеру телефона |
| `applications.assignee_id` ставится при входе на этап | Аналитик и андеррайтер работают со своими заявками; назначение — в `services/assignment.py`, вызывается из `transition()` |
| `application_status_history` | Аудит (кто, когда, почему изменил статус) и таймлайн в кабинете клиента |
| `applications.version` | Оптимистичная блокировка: клиент и сотрудники банка не перезаписывают изменения друг друга |
| Файлы — только метаданные в БД, содержимое в объектном хранилище (`storage_key`) | БД не раздувается бинарными данными |
| `loan_contracts` уникален по заявке и по решению андеррайтера | Договор — снимок условий принятого оффера; уникальность делает подготовку договора и выдачу идемпотентными |
| `payment_schedule_items` отдельной таблицей | Строки графика с плановыми и фактическими статусами платежей; остаток и ближайший платёж считаются из них |
| `notifications` | Сценарий по условиям кейса проходит внутри продукта, без email/SMS |
