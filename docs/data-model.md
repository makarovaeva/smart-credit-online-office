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
        date registration_date
        string actual_address
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
        string message
        array requested_document_types
        string status "open | answered | cancelled"
    }
    documents {
        string type
        string storage_key UK
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
| DSCR, Debt Burden, LTV, зона и confidence — отдельные колонки | По ним работает маршрутизация и фильтрация очереди бэкофиса; остальные метрики — в `metrics` (JSONB) |
| `stop_factors`, `escalation_reasons`, `factors` в JSONB | Объяснимость: андеррайтер видит, почему заявка ушла к аналитику или в автоотказ и что повлияло на оценку |
| `credit_memos.counter_offer_adjustments` | Контр-предложение ИИ по сценариям политики (лимит, срок, Debt Burden, LTV, риск-надбавка): что и почему изменилось относительно запроса |
| `credit_decisions.more_info_target` | У «нужны данные» два возвратных маршрута: документы от клиента или экспертиза аналитика |
| `applications.close_reason` — enum | Четыре пути к финалу «Закрыто без выдачи» с доски; клиенту показывается причина |
| `collateral_address`, `collateral_encumbrances`, `pre_approvals.collateral_required` | Консультация с залогом уточняет адрес и обременения; предварительный расчёт показывает необходимость обеспечения |
| `collateral_type` + `collateral_market_value` | Дисконт для LTV зависит от типа залога (коммерческая недвижимость 0,2–0,3 … товар в обороте 0,5–0,7) |
| `annual_ebitda` | Входит в DSCR = EBITDA / Debt Service и Debt Burden |
| `application_consents` | Без согласий на БКИ/ФНС/цифровой профиль ИИ не начинает сбор данных (этап Draft) |
| `pre_approvals` | Клиент видит шансы и диапазон до подачи — ключевой запрос персоны «новый заёмщик» |
| `company_owners` | Проверка собственников по санкционным спискам и основание эскалации «сложная структура владения» |
| Сырые ответы внешних источников в `external_checks.result` (JSONB) | Контракты моков могут меняться; сохраняется доказательная база для решения |
| `application_status_history` | Аудит (кто, когда, почему изменил статус) и таймлайн в кабинете клиента |
| `applications.version` | Оптимистичная блокировка: клиент и сотрудники банка не перезаписывают изменения друг друга |
| Файлы — только метаданные в БД, содержимое в объектном хранилище (`storage_key`) | БД не раздувается бинарными данными |
| `notifications` | Сценарий по условиям кейса проходит внутри продукта, без email/SMS |
