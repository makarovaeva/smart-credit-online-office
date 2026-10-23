# Итоговая модель данных MVP: кредитование ММБ

Документ содержит ER-модель, JSON-примеры всех сущностей и техническую документацию по полям.

Сущностей 11:
- **основные:** Borrower Profile, Loan Application, Credit Assessment, Offer, Loan Contract;
- **служебные:** User, Chat History, Approval History, Internal Request, Application Event, Notification.

**Условные обозначения для таблиц**
- **Этап:** номер из статусной модели (1 Draft, 2 Data Collection, 3 Pre-Approved, 4 Application Submitted, 5 AI Verification, 6 Need Additional Data, 7 AI Risk Scoring, 8 Decision Routing, 9 AI Financial Analysis, 10 Analyst Escalation, 11 Analyst Completed, 12 Underwriter Review, 13 Offer Generated, 14 Offer Accepted, 15 Offer Rejected, 16 Contract Generation, 17 E-Sign, 18 Disbursement, Ф финал).
- **Роль:** К клиент, ИИ ИИ-агент, А аналитик, У андеррайтер, Б банк/система, АДМ администратор.
- **Связь:** СФ стоп-фактор, ЭСК передача аналитику, GZ Green Zone, КП контр-предложение, ОФ оффер, КД кредитный договор, АН аналитический показатель (не участвует в решении).
- **Именование:**
  - идентификаторы: `*_id`, префикс и ULID;
  - ссылки на сотрудников: `*_user_id`;
  - деньги: рубли, число;
  - проценты: `*_pct`;
  - коэффициенты без суффикса;
  - даты: ISO 8601 UTC;
  - перечисления: `snake_case`, роли сотрудников заглавными (`ANALYST`, `UNDERWRITER`, `ADMIN`).

---

# 1. ER-модель

```text
Borrower Profile
    1:N   Loan Application
              1:N   Credit Assessment
                        1:N   Offer
                                  0..1:1   Loan Contract
                        1:N   Approval History
              1:N   Offer                      (offer.application_id)
              1:N   Approval History
              1:N   Internal Request
              1:N   Chat History
              1:N   Application Event
              1:N   Notification

Borrower Profile
    1:N   Chat History           (чат до появления заявки, application_id = null)

User (сотрудник: ANALYST / UNDERWRITER / ADMIN)
    1:N   Loan Application       (assignment.analyst_user_id, assignment.underwriter_user_id)
    1:N   Credit Assessment      (analyst_conclusion.analyst_user_id)
    1:N   Offer                  (created_by.user_id)
    1:N   Approval History       (decided_by_user_id)
    1:N   Internal Request       (from_user_id, to_user_id)
    1:N   Application Event      (actor_user_id)
    1:N   Notification           (recipient_id при recipient_type = employee)
```

| Связь | Ключ | Кратность | Правило |
|---|---|---|---|
| Профиль → Заявка | `loan_application.borrower_id` | 1:N | Профиль существует без заявок. Одновременно допустима одна заявка в статусах 1–18 (проверка на уровне процесса). |
| Заявка → Оценка | `credit_assessment.application_id` | 1:N | Новая версия создаётся при каждом скоринге (этап 7), в том числе после возврата с этапа 6. Актуальная указана в `loan_application.current_assessment_id`. |
| Оценка → Оффер | `offer.assessment_id` | 1:N | Каждый оффер строится на конкретной версии оценки. |
| Заявка → Оффер | `offer.application_id` | 1:N | Единственная намеренная денормализация, для выборки «все офферы заявки». Значение должно совпадать с `assessment.application_id`. |
| Оффер → Оффер | `offer.parent_offer_id` | N:1 | Цепочка версий: ИИ → аналитик → контр-предложение андеррайтера → финальный. |
| Оффер → Договор | `loan_contract.offer_id` (UNIQUE) | 0..1:1 | Договор создаётся только из `final_offer` в статусе `accepted`. |
| Заявка → Approval History | `approval_history.application_id` | 1:N | Каждое решение андеррайтера — отдельная запись. Решение «нужна информация» и повторное «одобрено» хранятся вместе. |
| Оценка → Approval History | `approval_history.assessment_id` | 1:N | Решение фиксируется по конкретной версии оценки. |
| Заявка → Internal Request | `internal_request.application_id` | 1:N | Запросы между аналитиком, андеррайтером и ИИ-агентом. |
| Заявка → Chat History | `chat_history.application_id` | 1:N | Сообщения диалога с ИИ-агентом. До создания заявки `application_id = null`, связь через `borrower_id`. |
| Заявка → Application Event | `application_event.application_id` | 1:N | Журнал всех действий и смен статусов с привязкой к исполнителю. |
| Заявка → Notification | `notification.application_id` | 1:N | Системные уведомления. |
| User → заявки, решения, запросы, события | `*_user_id` | 1:N | Любое действие сотрудника привязано к `user_id`. |
| Заявка → Профиль.documents | `document_requirements[].document_id` | N:M | Файлы хранятся один раз в профиле. |

Договор не хранит `application_id` и `borrower_id`: они берутся по цепочке договор → оффер → заявка → профиль.

**Правило решений.** Автоматические решения (маршрут, Green Zone, контр-предложения, оффер) принимаются только по стоп-факторам, основаниям передачи аналитику и показателям: сумма, DSCR, LTV, риск не выше среднего. Debt Burden рассчитывается и сохраняется как аналитический показатель для аналитика и андеррайтера.

---

# 2. JSON: Borrower Profile

```json
{
  "borrower_id": "brw_01J9Z3K4M2",
  "status": "active",
  "customer_since": "2026-10-19",
  "company": {
    "legal_form": "ooo",
    "full_name": "Общество с ограниченной ответственностью «Вектор»",
    "short_name": "ООО «Вектор»",
    "inn": "7701234567",
    "kpp": "770101001",
    "ogrn": "1157746123456",
    "registration_date": "2021-04-12",
    "legal_address": "[юридический адрес]",
    "actual_address": "[фактический адрес]",
    "okved_main": { "code": "46.90", "name": "Торговля оптовая неспециализированная" },
    "tax_system": "usn_income_expense",
    "employees_count": 24,
    "region_code": "77"
  },
  "head": {
    "full_name": "Иванов Иван Иванович",
    "position": "Генеральный директор",
    "inn_individual": "771234567890",
    "birth_date": "1985-03-14",
    "in_position_since": "2021-04-12",
    "has_signing_authority": true
  },
  "owners": [
    { "owner_id": "own_01J9Z3K5A1", "owner_type": "individual", "name": "Иванов Иван Иванович", "inn": "771234567890", "ownership_share_pct": 60.0, "is_beneficiary": true, "has_signing_authority": true },
    { "owner_id": "own_01J9Z3K5A2", "owner_type": "individual", "name": "Сидорова Мария Петровна", "inn": "771234567891", "ownership_share_pct": 40.0, "is_beneficiary": true, "has_signing_authority": false }
  ],
  "contacts": {
    "phone": "+79991234567",
    "email": "finance@vector.example",
    "contact_person": { "full_name": "Петрова Анна Сергеевна", "position": "Финансовый директор", "phone": "+79990000000" }
  },
  "fns_data": {
    "retrieved_at": "2026-10-20T10:07:12Z",
    "egrul_status": "active",
    "bankruptcy_status": "none",
    "has_account_block_115fz": false,
    "is_mass_address": false,
    "is_mass_director": false,
    "has_tax_activity": true,
    "tax_arrears_amount": 0
  },
  "compliance": {
    "checked_at": "2026-10-20T10:07:40Z",
    "source": "internal_screening",
    "sanctions_hit": false,
    "is_prohibited_activity": false
  },
  "bki_data": {
    "retrieved_at": "2026-10-20T10:08:05Z",
    "bureau": "[название БКИ]",
    "credit_history_quality": "good",
    "active_loans_count": 1,
    "total_debt_amount": 900000,
    "monthly_debt_service": 40000,
    "overdue_amount": 0,
    "max_overdue_days_12m": 0
  },
  "financials": {
    "as_of_date": "2026-09-30",
    "annual_turnover": 18000000,
    "revenue_change_pct": -4.2,
    "ebitda": 5000000,
    "cash_flow_period_end": "2026-09",
    "cash_flow_last_12m": [210000, 180000, 240000, 150000, 320000, 275000, 190000, 260000, 305000, 230000, 280000, 295000],
    "source": "documents"
  },
  "bank_account": {
    "account_number": "40702810000000000001",
    "bik": "044525000",
    "bank_name": "[наименование банка]",
    "currency": "RUB",
    "opened_at": "2021-05-01",
    "status": "active"
  },
  "documents": [
    { "document_id": "doc_01J9Z4A001", "document_type": "financial_statements", "period_from": "2025-01-01", "period_to": "2025-12-31", "file_name": "bukh_otchetnost_2025.pdf", "file_uri": "storage://borrowers/brw_01J9Z3K4M2/doc_01J9Z4A001.pdf", "uploaded_by": "client", "uploaded_at": "2026-10-20T10:40:00Z", "verification_status": "verified", "source_application_id": "app_01JC0A7Q5R" },
    { "document_id": "doc_01J9Z4A002", "document_type": "kudir", "period_from": "2025-10-01", "period_to": "2026-09-30", "file_name": "kudir.xlsx", "file_uri": "storage://borrowers/brw_01J9Z3K4M2/doc_01J9Z4A002.xlsx", "uploaded_by": "client", "uploaded_at": "2026-10-20T10:41:00Z", "verification_status": "verified", "source_application_id": "app_01JC0A7Q5R" },
    { "document_id": "doc_01J9Z4A003", "document_type": "bank_statement", "period_from": "2025-10-01", "period_to": "2026-09-30", "file_name": "vypiska_12m.pdf", "file_uri": "storage://borrowers/brw_01J9Z3K4M2/doc_01J9Z4A003.pdf", "uploaded_by": "client", "uploaded_at": "2026-10-20T11:08:00Z", "verification_status": "verified", "source_application_id": "app_01JC0A7Q5R" }
  ],
  "created_at": "2026-10-19T08:00:00Z",
  "updated_at": "2026-10-20T11:08:00Z"
}
```

---

# 3. JSON: Loan Application

Пример: заявка завершена (договор подписан, средства выданы). История статусов и внутренние запросы вынесены в `Application Event` и `Internal Request`.

```json
{
  "application_id": "app_01JC0A7Q5R",
  "application_number": "ММБ-2026-000123",
  "borrower_id": "brw_01J9Z3K4M2",
  "status": "completed",
  "status_changed_at": "2026-10-23T11:05:41Z",
  "routing_status": "green_zone",
  "current_assessment_id": "asm_01JC0B2X9F",
  "loan_request": { "amount": 3000000, "currency": "RUB", "term_months": 24, "repayment_type": "annuity" },
  "purpose": { "category": "working_capital", "description": "Пополнение оборотных средств" },
  "collateral": { "type": "none", "description": null, "market_value": null, "haircut_pct": null, "valuation_source": null },
  "pre_approval": { "max_amount": 3600000, "indicative_rate_pct": 22.0, "calculated_at": "2026-10-20T10:20:00Z" },
  "consents": {
    "data_processing_at": "2026-10-20T10:05:00Z",
    "credit_history_check_at": "2026-10-20T10:06:00Z",
    "submit_confirmed_at": "2026-10-20T10:31:00Z"
  },
  "document_requirements": [
    { "requirement_id": "req_01JC0A8A01", "document_type": "financial_statements", "period_from": "2025-01-01", "period_to": "2025-12-31", "status": "verified", "document_id": "doc_01J9Z4A001", "requested_by": "ai_agent", "requested_at": "2026-10-20T10:32:00Z", "fulfilled_at": "2026-10-20T10:40:00Z", "comment": null },
    { "requirement_id": "req_01JC0A8A02", "document_type": "kudir", "period_from": "2025-10-01", "period_to": "2026-09-30", "status": "verified", "document_id": "doc_01J9Z4A002", "requested_by": "ai_agent", "requested_at": "2026-10-20T10:32:00Z", "fulfilled_at": "2026-10-20T10:41:00Z", "comment": null },
    { "requirement_id": "req_01JC0A8A03", "document_type": "bank_statement", "period_from": "2025-10-01", "period_to": "2026-09-30", "status": "verified", "document_id": "doc_01J9Z4A003", "requested_by": "ai_agent", "requested_at": "2026-10-20T10:33:00Z", "fulfilled_at": "2026-10-20T11:08:00Z", "comment": "Первая выписка была неполной, загружена повторно" }
  ],
  "assignment": { "analyst_user_id": null, "underwriter_user_id": "usr_01J8UW0017" },
  "closure": null,
  "created_at": "2026-10-20T10:05:00Z",
  "updated_at": "2026-10-23T11:05:41Z"
}
```

---

# 4. JSON: Credit Assessment

Пример: зелёная зона, оценка № 2 (после дозапроса андеррайтера).

Расчёт для примера:
- платёж по новому кредиту: 155 635 ₽/мес., за 12 месяцев 1 867 620 ₽;
- существующие обязательства: 480 000 ₽ в год;
- Total Future Debt Service = 2 347 620 ₽;
- DSCR = 5 000 000 / 2 347 620 = 2,13;
- Debt Burden (аналитический) = 46,95 %.

```json
{
  "assessment_id": "asm_01JC0B2X9F",
  "application_id": "app_01JC0A7Q5R",
  "sequence": 2,
  "status": "completed",
  "trigger": "more_information_received",
  "policy_version": "2026.10",
  "model_version": "risk-llm-1.4.2",
  "calculated_at": "2026-10-21T12:17:00Z",
  "inputs": {
    "loan_amount": 3000000,
    "term_months": 24,
    "rate_pct": 22.0,
    "annual_turnover": 18000000,
    "ebitda": 5000000,
    "existing_debt_service_12m": 480000,
    "new_debt_service_12m": 1867620,
    "total_future_debt_service": 2347620,
    "collateral_market_value": null,
    "collateral_haircut_pct": null,
    "business_age_months": 54,
    "revenue_change_pct": -4.2,
    "cash_flow_negative_months": 0,
    "credit_history_quality": "good"
  },
  "metrics": { "dscr": 2.13, "ltv_pct": null, "debt_burden_pct": 46.95 },
  "ai_scoring": { "risk_grade": "B", "risk_score": 72, "model_confidence_pct": 91.0 },
  "stop_factor_checks": [
    { "code": "bankruptcy", "group": "legal", "triggered": false, "actual": "none", "source": "fns_data.bankruptcy_status" },
    { "code": "observation_procedure", "group": "legal", "triggered": false, "actual": "none", "source": "fns_data.bankruptcy_status" },
    { "code": "account_blocked_115fz", "group": "legal", "triggered": false, "actual": false, "source": "fns_data.has_account_block_115fz" },
    { "code": "sanctions", "group": "legal", "triggered": false, "actual": false, "source": "compliance.sanctions_hit" },
    { "code": "prohibited_activity", "group": "legal", "triggered": false, "actual": false, "source": "compliance.is_prohibited_activity" },
    { "code": "cash_flow_negative_over_3m", "group": "financial", "triggered": false, "actual": 0, "source": "inputs.cash_flow_negative_months" },
    { "code": "dscr_below_0_9", "group": "financial", "triggered": false, "actual": 2.13, "source": "metrics.dscr" },
    { "code": "mass_address", "group": "fictitiousness", "triggered": false, "actual": false, "source": "fns_data.is_mass_address" },
    { "code": "mass_director", "group": "fictitiousness", "triggered": false, "actual": false, "source": "fns_data.is_mass_director" },
    { "code": "no_tax_activity", "group": "fictitiousness", "triggered": false, "actual": false, "source": "fns_data.has_tax_activity" }
  ],
  "escalation_checks": [
    { "code": "business_age_lt_12m", "triggered": false, "actual": 54, "threshold": 12 },
    { "code": "model_confidence_lt_80", "triggered": false, "actual": 91.0, "threshold": 80 },
    { "code": "conflicting_sources", "triggered": false, "actual": 0, "threshold": 0 }
  ],
  "green_zone_checks": [
    { "code": "amount_limit", "actual": 3000000, "operator": "<=", "threshold": 3600000, "passed": true },
    { "code": "dscr", "actual": 2.13, "operator": ">=", "threshold": 1.1, "passed": true },
    { "code": "ltv", "actual": null, "operator": "<=", "threshold": 70, "passed": null },
    { "code": "revenue_change", "actual": -4.2, "operator": ">", "threshold": -20, "passed": true },
    { "code": "credit_history", "actual": "good", "operator": "!=", "threshold": "weak", "passed": true }
  ],
  "route": "green_zone",
  "counter_offer_triggers": [],
  "auto_decline": null,
  "ai_credit_memo": {
    "summary": "Устойчивый бизнес с положительным денежным потоком. Запрошенная сумма ниже лимита автоодобрения, DSCR выше порога.",
    "key_risks": ["Небольшое снижение выручки (-4,2 %)", "Концентрация выручки на нескольких контрагентах"],
    "recommendation": "approve",
    "generated_at": "2026-10-21T12:25:00Z"
  },
  "analyst_conclusion": null,
  "created_at": "2026-10-21T12:15:00Z"
}
```

Фрагмент для случая, когда срабатывают контр-предложения (DSCR 1,0 и LTV 82 %):

```json
"counter_offer_triggers": [
  { "code": "dscr_below_threshold", "triggered": true, "recommended_action": "extend_term", "recommended_terms": { "amount": null, "term_months": 36, "rate_delta_pp": null } },
  { "code": "ltv_exceeded", "triggered": true, "recommended_action": "reduce_amount_or_add_collateral", "recommended_terms": { "amount": 2500000, "term_months": null, "rate_delta_pp": null } }
]
```

Фрагмент для автоотказа:

```json
"route": "auto_decline",
"auto_decline": {
  "reason_codes": ["mass_address", "no_tax_activity"],
  "client_explanation": "Банк не может предоставить кредит: компания не прошла автоматическую проверку.",
  "declined_at": "2026-10-20T11:14:00Z"
}
```

Фрагмент для эскалации (заключение аналитика):

```json
"route": "analyst_escalation",
"analyst_conclusion": {
  "analyst_user_id": "usr_01J8AN0042",
  "recommendation": "counter_offer",
  "conclusion_text": "[выводы по документам, рискам и бизнесу]",
  "completed_at": "2026-10-21T10:20:00Z"
}
```

---

# 5. JSON: Offer

Пример: финальный оффер, принятый клиентом.

```json
{
  "offer_id": "ofr_01JC0C5M8T",
  "application_id": "app_01JC0A7Q5R",
  "assessment_id": "asm_01JC0B2X9F",
  "offer_type": "final_offer",
  "sequence": 2,
  "parent_offer_id": "ofr_01JC0B3A4D",
  "status": "accepted",
  "created_by": { "actor_type": "underwriter", "user_id": "usr_01J8UW0017" },
  "terms": {
    "amount": 3000000,
    "currency": "RUB",
    "term_months": 24,
    "rate_pct": 22.0,
    "repayment_type": "annuity",
    "monthly_payment": 155635.00
  },
  "collateral_requirements": { "type": "none", "guarantor_required": false, "min_collateral_value": null },
  "changes_from_parent": [],
  "decision_basis": ["green_zone_all_checks_passed"],
  "client_explanation": "Заявка одобрена на запрошенных условиях.",
  "presented_at": "2026-10-21T14:06:00Z",
  "valid_until": "2026-10-28T14:06:00Z",
  "client_decision": { "decision": "accepted", "decided_at": "2026-10-22T10:00:00Z", "rejection_reason": null },
  "created_at": "2026-10-21T14:06:00Z"
}
```

Контр-предложение андеррайтера (цепочка `ai_offer` → `underwriter_counter_offer` → `final_offer`) отличается заполненным `changes_from_parent`:

```json
"offer_type": "underwriter_counter_offer",
"terms": { "amount": 2500000, "currency": "RUB", "term_months": 24, "rate_pct": 23.0, "repayment_type": "annuity", "monthly_payment": 130935.00 },
"collateral_requirements": { "type": "guarantee", "guarantor_required": true, "min_collateral_value": null },
"changes_from_parent": [
  { "field": "terms.amount", "previous": 3000000, "new": 2500000, "reason_code": "ltv_exceeded" },
  { "field": "terms.rate_pct", "previous": 22.0, "new": 23.0, "reason_code": "above_average_risk" }
]
```

---

# 6. JSON: Loan Contract

Показаны две первые строки графика из 24.

```json
{
  "contract_id": "ctr_01JC0D1H7W",
  "contract_number": "КД-2026-000045",
  "offer_id": "ofr_01JC0C5M8T",
  "status": "active",
  "principal_amount": 3000000,
  "currency": "RUB",
  "term_months": 24,
  "interest_rate_pct": 22.0,
  "repayment_type": "annuity",
  "monthly_payment": 155635.00,
  "signed_at": "2026-10-23T11:02:10Z",
  "signature": { "method": "e_sign", "signature_id": "sig_01JC0D2K3P" },
  "disbursed_at": "2026-10-23T11:05:41Z",
  "disbursement": { "account_number": "40702810000000000001", "amount": 3000000, "transaction_id": "txn_01JC0D3Q8R" },
  "maturity_date": "2028-10-23",
  "payment_schedule": [
    { "installment_no": 1, "due_date": "2026-11-23", "principal_amount": 100635.00, "interest_amount": 55000.00, "total_amount": 155635.00, "balance_after": 2899365.00, "payment_status": "scheduled" },
    { "installment_no": 2, "due_date": "2026-12-23", "principal_amount": 102480.65, "interest_amount": 53154.35, "total_amount": 155635.00, "balance_after": 2796884.35, "payment_status": "scheduled" }
  ],
  "documents": [
    { "document_type": "loan_agreement", "file_uri": "storage://contracts/ctr_01JC0D1H7W/agreement.pdf", "signed_at": "2026-10-23T11:02:10Z" },
    { "document_type": "payment_schedule", "file_uri": "storage://contracts/ctr_01JC0D1H7W/schedule.pdf", "signed_at": "2026-10-23T11:02:10Z" }
  ],
  "created_at": "2026-10-22T10:01:00Z",
  "updated_at": "2026-10-23T11:05:41Z"
}
```

---

# 7. JSON: служебные сущности

## User

Учётные данные (пароль, сессии) хранятся в сервисе аутентификации и в модель не входят.

```json
{
  "user_id": "usr_01J8UW0017",
  "login": "uw.petrov",
  "full_name": "Петров Сергей Николаевич",
  "email": "uw.petrov@bank.example",
  "role": "UNDERWRITER",
  "status": "active",
  "last_login_at": "2026-10-23T08:55:00Z",
  "created_at": "2026-03-01T09:00:00Z",
  "updated_at": "2026-10-23T08:55:00Z"
}
```

## Chat History

```json
[
  {
    "message_id": "msg_01JC0A6001",
    "borrower_id": "brw_01J9Z3K4M2",
    "application_id": "app_01JC0A7Q5R",
    "sender_type": "client",
    "message_type": "text",
    "content": "3 млн на 2 года, пополнить оборотку",
    "card_payload": null,
    "attachment_document_ids": [],
    "requirement_ids": [],
    "created_at": "2026-10-20T10:12:00Z"
  },
  {
    "message_id": "msg_01JC0A6002",
    "borrower_id": "brw_01J9Z3K4M2",
    "application_id": "app_01JC0A7Q5R",
    "sender_type": "ai_agent",
    "message_type": "confirmation_card",
    "content": "Проверьте параметры заявки. Проверку документов начну после вашего подтверждения.",
    "card_payload": {
      "card_type": "application_summary",
      "fields": { "amount": 3000000, "term_months": 24, "purpose": "Оборотные средства", "collateral": "Без залога" },
      "action": { "action_type": "submit_application", "status": "confirmed", "resolved_at": "2026-10-20T10:31:00Z" }
    },
    "attachment_document_ids": [],
    "requirement_ids": [],
    "created_at": "2026-10-20T10:25:00Z"
  },
  {
    "message_id": "msg_01JC0A6003",
    "borrower_id": "brw_01J9Z3K4M2",
    "application_id": "app_01JC0A7Q5R",
    "sender_type": "ai_agent",
    "message_type": "document_request",
    "content": "Для проверки нужна выписка по расчётному счёту за последние 12 месяцев.",
    "card_payload": null,
    "attachment_document_ids": [],
    "requirement_ids": ["req_01JC0A8A03"],
    "created_at": "2026-10-20T10:33:00Z"
  }
]
```

## Approval History

```json
[
  {
    "approval_id": "apv_01JC0B1001",
    "application_id": "app_01JC0A7Q5R",
    "assessment_id": "asm_01JC0B0A11",
    "decision": "more_information_required",
    "decided_by_user_id": "usr_01J8UW0017",
    "reason_codes": ["incomplete_bank_statement"],
    "client_explanation": null,
    "comment": "Уточнить выписку за последние 3 месяца",
    "resulting_offer_id": null,
    "decided_at": "2026-10-21T09:40:00Z"
  },
  {
    "approval_id": "apv_01JC0B4002",
    "application_id": "app_01JC0A7Q5R",
    "assessment_id": "asm_01JC0B2X9F",
    "decision": "approved",
    "decided_by_user_id": "usr_01J8UW0017",
    "reason_codes": [],
    "client_explanation": null,
    "comment": "Подтверждаю рекомендацию ИИ",
    "resulting_offer_id": "ofr_01JC0C5M8T",
    "decided_at": "2026-10-21T14:05:00Z"
  }
]
```

## Internal Request

```json
{
  "request_id": "irq_01JC0A9C11",
  "application_id": "app_01JC0A7Q5R",
  "request_type": "document_request",
  "from_user_id": "usr_01J8UW0017",
  "to_target": "ai_agent",
  "to_user_id": null,
  "message": "Уточнить выписку за последние 3 месяца",
  "requirement_ids": ["req_01JC0A8A03"],
  "status": "completed",
  "due_at": "2026-10-22T12:00:00Z",
  "created_at": "2026-10-21T09:40:00Z",
  "accepted_at": null,
  "resolved_at": "2026-10-21T12:15:00Z",
  "response_message": null
}
```

## Application Event

```json
[
  { "event_id": "evt_01JC0A7001", "application_id": "app_01JC0A7Q5R", "event_type": "status_changed", "actor_type": "client", "actor_user_id": null, "from_status": "pre_approved", "to_status": "application_submitted", "entity_type": "application", "entity_id": "app_01JC0A7Q5R", "comment": null, "created_at": "2026-10-20T10:31:00Z" },
  { "event_id": "evt_01JC0B4003", "application_id": "app_01JC0A7Q5R", "event_type": "status_changed", "actor_type": "employee", "actor_user_id": "usr_01J8UW0017", "from_status": "underwriter_review", "to_status": "approved", "entity_type": "application", "entity_id": "app_01JC0A7Q5R", "comment": null, "created_at": "2026-10-21T14:05:00Z" },
  { "event_id": "evt_01JC0C6004", "application_id": "app_01JC0A7Q5R", "event_type": "offer_decision", "actor_type": "client", "actor_user_id": null, "from_status": "offer_generated", "to_status": "offer_accepted", "entity_type": "offer", "entity_id": "ofr_01JC0C5M8T", "comment": null, "created_at": "2026-10-22T10:00:00Z" }
]
```

## Notification

```json
{
  "notification_id": "ntf_01JC0D4005",
  "recipient_type": "borrower",
  "recipient_id": "brw_01J9Z3K4M2",
  "application_id": "app_01JC0A7Q5R",
  "notification_type": "funds_disbursed",
  "channel": "in_app",
  "title": "Средства зачислены",
  "message": "3 000 000 ₽ поступили на ваш расчётный счёт.",
  "status": "read",
  "created_at": "2026-10-23T11:05:45Z",
  "sent_at": "2026-10-23T11:05:46Z",
  "read_at": "2026-10-23T11:20:00Z"
}
```

---

# 8. Техническая документация

Колонки: **Поле (тип)**, **Назначение**, **Источник**, **Этап**, **Роль** (кто использует), **Связь**. Таблицы задают контракт схем.

## 8.1. Borrower Profile

Единый профиль компании. Создаётся при онбординге клиента (до любой заявки) и обновляется из внешних источников.

### Корень профиля

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `borrower_id` (id) | Первичный ключ | Система | 1 | Все | — |
| `status` (enum: `active`, `blocked`, `closed`) | Состояние клиента в банке | Банк | Любой | У, Б | — |
| `customer_since` (date) | Дата становления клиентом | Банк | — | Б | — |
| `created_at`, `updated_at` (timestamp) | Аудит | Система | Любой | Б | — |

### Данные компании (`company`)

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `legal_form` (enum: `ooo`, `ip`, …) | Организационно-правовая форма | ЕГРЮЛ/ЕГРИП (ФНС) | 2 | ИИ | — |
| `full_name` (string) | Полное наименование | ФНС | 2 | ИИ, К | — |
| `short_name` (string) | Краткое наименование для интерфейса | ФНС | 2 | К | — |
| `inn` (string) | ИНН, ключ запросов во внешние источники | Клиент / ФНС | 2 | ИИ | — |
| `kpp` (string, null для ИП) | КПП | ФНС | 2 | ИИ | — |
| `ogrn` (string) | ОГРН/ОГРНИП | ФНС | 2 | ИИ | — |
| `registration_date` (date) | Дата регистрации, из неё считается возраст бизнеса | ФНС | 2, 7 | ИИ | ЭСК (`business_age_lt_12m`) |
| `legal_address` (string) | Юридический адрес, проверка массового адреса | ФНС | 2, 5 | ИИ | СФ (`mass_address`) |
| `actual_address` (string) | Фактический адрес | Клиент | 2 | ИИ | — |
| `okved_main.code`, `okved_main.name` (string) | Основной вид деятельности | ФНС | 2, 7 | ИИ, А | СФ (`prohibited_activity`) |
| `tax_system` (enum: `usn_income`, `usn_income_expense`, `osno`, …) | Система налогообложения, выбор набора отчётности | ФНС / клиент | 2, 5 | ИИ | — |
| `employees_count` (int) | Численность сотрудников | ФНС / клиент | 2 | ИИ, А | — |
| `region_code` (string) | Регион ведения бизнеса | ФНС | 2 | ИИ | — |

### Данные руководителя (`head`)

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `full_name` (string) | ФИО руководителя | ЕГРЮЛ | 2 | ИИ, К | СФ (`mass_director`) |
| `position` (string) | Должность | ЕГРЮЛ | 2 | К | — |
| `inn_individual` (string) | ИНН физлица для проверок БКИ/ФНС | Клиент / ФНС | 2 | ИИ | — |
| `birth_date` (date) | Идентификация | Клиент | 2 | ИИ | — |
| `in_position_since` (date) | Стаж в должности | ЕГРЮЛ | 2 | ИИ, А | — |
| `has_signing_authority` (bool) | Право подписи договора | Клиент / ЕГРЮЛ | 16–17 | Б | КД |

### Данные владельцев (`owners[]`)

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `owner_id` (id) | Идентификатор владельца | Система | 2 | Б | — |
| `owner_type` (enum: `individual`, `legal_entity`) | Тип владельца | ЕГРЮЛ | 2 | ИИ | — |
| `name` (string) | ФИО или наименование | ЕГРЮЛ | 2 | ИИ, А | СФ (`sanctions`) |
| `inn` (string) | Идентификатор для санкционных проверок | ЕГРЮЛ | 2, 5 | ИИ | СФ (`sanctions`) |
| `ownership_share_pct` (number) | Доля владения | ЕГРЮЛ | 2 | ИИ, А | — |
| `is_beneficiary` (bool) | Бенефициарный владелец | Клиент / ЕГРЮЛ | 2 | ИИ, У | — |
| `has_signing_authority` (bool) | Право подписи (экран «Профиль») | Клиент | 16–17 | Б | КД |

### Контакты (`contacts`)

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `phone` (string) | Телефон, он же логин клиента (экран авторизации) | Клиент | 1 | К, ИИ | — |
| `email` (string) | Почта для уведомлений | Клиент | 2 | К | — |
| `contact_person.full_name`, `.position`, `.phone` (string) | Контактное лицо по кредиту | Клиент | 2 | ИИ, А, У | — |

### Данные ФНС (`fns_data`)

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `retrieved_at` (timestamp) | Актуальность выгрузки | ФНС | 2, 5 | ИИ | — |
| `egrul_status` (enum: `active`, `liquidating`, `liquidated`) | Статус юрлица | ФНС | 5 | ИИ | СФ |
| `bankruptcy_status` (enum: `none`, `observation`, `bankruptcy`) | Банкротство или наблюдение | ФНС | 5, 7 | ИИ | СФ (`bankruptcy`, `observation_procedure`) |
| `has_account_block_115fz` (bool) | Блокировка счёта по 115-ФЗ | ФНС / комплаенс | 5, 7 | ИИ | СФ (`account_blocked_115fz`) |
| `is_mass_address` (bool) | Признак массового адреса | ФНС | 5, 7 | ИИ | СФ (`mass_address`) |
| `is_mass_director` (bool) | Признак массового директора | ФНС | 5, 7 | ИИ | СФ (`mass_director`) |
| `has_tax_activity` (bool) | Наличие налоговой активности | ФНС | 5, 7 | ИИ | СФ (`no_tax_activity`) |
| `tax_arrears_amount` (number) | Налоговая задолженность | ФНС | 7 | ИИ, А | Риск-скоринг |

### Комплаенс (`compliance`)

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `checked_at` (timestamp) | Дата проверки | Комплаенс | 5 | ИИ | — |
| `source` (string) | Система проверки | Комплаенс | 5 | Б | — |
| `sanctions_hit` (bool) | Совпадение с санкционными списками (компания, руководитель, собственники) | Комплаенс | 5, 7 | ИИ | СФ (`sanctions`) |
| `is_prohibited_activity` (bool) | Запрещённая деятельность по ОКВЭД и политике | Комплаенс | 5, 7 | ИИ | СФ (`prohibited_activity`) |

### Данные БКИ (`bki_data`)

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `retrieved_at` (timestamp) | Актуальность отчёта | БКИ | 5 | ИИ | — |
| `bureau` (string) | Бюро кредитных историй | БКИ | 5 | Б | — |
| `credit_history_quality` (enum: `good`, `weak`, `none`) | Качество истории | БКИ, расчёт ИИ | 7 | ИИ, А | GZ (`credit_history`), КП (риск выше среднего) |
| `active_loans_count` (int) | Число действующих кредитов | БКИ | 7 | ИИ | — |
| `total_debt_amount` (number) | Совокупный долг | БКИ | 7, 9 | ИИ | — |
| `monthly_debt_service` (number) | Ежемесячное обслуживание действующих долгов | БКИ | 9 | ИИ | GZ (DSCR), АН (Debt Burden) |
| `overdue_amount` (number) | Текущая просрочка | БКИ | 7 | ИИ | Риск-скоринг |
| `max_overdue_days_12m` (int) | Максимальная просрочка за 12 мес. | БКИ | 7 | ИИ, А | GZ (`credit_history`) |

### Финансовые показатели (`financials`)

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `as_of_date` (date) | Дата актуальности | ИИ-обработка документов | 9 | ИИ | — |
| `annual_turnover` (number) | Годовой оборот | Выписки, КУДИР, отчётность | 9 | ИИ, А | GZ (лимит 20 % оборота) |
| `revenue_change_pct` (number) | Динамика выручки | Отчётность, выписки | 9 | ИИ | GZ (`revenue_change`), КП |
| `ebitda` (number) | EBITDA | Отчётность | 9 | ИИ, А | GZ (DSCR), АН |
| `cash_flow_period_end` (string `YYYY-MM`) | Последний месяц ряда | Выписки | 9 | ИИ | — |
| `cash_flow_last_12m` (number[12]) | Чистый денежный поток по месяцам | Выписки | 9 | ИИ | СФ (`cash_flow_negative_over_3m`) |
| `source` (enum: `documents`, `bank_statements`, `fns`) | Откуда рассчитаны показатели | ИИ | 9 | А | ЭСК (`conflicting_sources`) |

### Расчётный счёт (`bank_account`)

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `account_number` (string) | Счёт зачисления кредита | Банк | 18 | Б | КД (`disbursement`) |
| `bik` (string) | БИК банка | Банк | 18 | Б | КД |
| `bank_name` (string) | Название банка | Банк | 18 | Б | — |
| `currency` (string) | Валюта счёта | Банк | 18 | Б | — |
| `opened_at` (date) | Дата открытия, оценка «возраста» счёта | Банк | 7 | ИИ | — |
| `status` (enum: `active`, `blocked`, `closed`) | Состояние счёта | Банк | 17–18 | Б | КД |

### Документы клиента (`documents[]`)

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `document_id` (id) | Идентификатор документа | Система | 5–6 | Все | — |
| `document_type` (enum: `financial_statements`, `kudir`, `bank_statement`, `tax_declaration`, `counterparty_contract`, `charter`, `other`) | Тип документа | ИИ-классификация | 5 | ИИ, А | — |
| `period_from`, `period_to` (date) | Отчётный период | Документ | 5, 9 | ИИ | Контроль комплектности |
| `file_name`, `file_uri` (string) | Файл и его адрес в хранилище | Клиент / система | 5 | ИИ, А, У | — |
| `uploaded_by` (enum: `client`, `ai_agent`, `bank_staff`) | Кто загрузил | Система | 5, 6 | Б | — |
| `uploaded_at` (timestamp) | Время загрузки | Система | 5, 6 | Б | — |
| `verification_status` (enum: `uploaded`, `verified`, `rejected`) | Результат проверки комплектности и подлинности | ИИ | 5 | ИИ, А | Переход 5 → 6 |
| `source_application_id` (id, null) | Заявка, по которой документ запрошен впервые | Система | 5 | Б | — |

## 8.2. Loan Application

Заявка на кредит. Одна компания может иметь несколько заявок. Заявка хранит запрос клиента и состояние процесса, а результаты анализа, решения, запросы, диалог и журнал действий вынесены в отдельные сущности.

### Идентификация и статус

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `application_id` (id) | Первичный ключ | Система | 1 | Все | — |
| `application_number` (string) | Номер заявки для клиента и сотрудников | Система | 4 | К, А, У | — |
| `borrower_id` (id → Borrower Profile) | Владелец заявки | Система | 1 | Все | — |
| `status` (enum, см. ниже) | Текущий статус (экран «Главная», рабочая зона) | Система | 1–Ф | Все | — |
| `status_changed_at` (timestamp) | Время последней смены статуса (полная история в Application Event) | Система | 1–Ф | К, А, У | — |
| `routing_status` (enum: `not_routed`, `auto_declined`, `green_zone`, `analyst_escalation`, `analyst_completed`) | Состояние маршрутизации процесса | ИИ | 8–11 | ИИ, А, У | ЭСК, GZ, СФ |
| `current_assessment_id` (id → Credit Assessment, null) | Актуальная версия анализа | Система | 7–12 | ИИ, А, У | — |
| `created_at`, `updated_at` (timestamp) | Аудит | Система | Любой | Б | — |

Значения `status` (в скобках номер этапа):
- процесс: `draft` (1), `data_collection` (2), `pre_approved` (3), `application_submitted` (4), `ai_verification` (5), `need_additional_data` (6), `ai_risk_scoring` (7), `decision_routing` (8), `ai_financial_analysis` (9), `analyst_escalation` (10), `analyst_completed` (11), `underwriter_review` (12), `offer_generated` (13), `offer_accepted` (14), `offer_rejected` (15), `contract_generation` (16), `e_sign` (17), `disbursement` (18);
- решения: `approved`, `conditional_approval`, `declined`, `more_information_required`, `auto_declined`;
- финалы: `completed`, `closed`.

### Параметры кредита и цель

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `loan_request.amount` (number) | Запрошенная сумма | Клиент через ИИ-агента | 2–4 | К, ИИ, У | GZ (лимит суммы), КП, ОФ |
| `loan_request.currency` (string) | Валюта | Клиент | 2 | Б | КД |
| `loan_request.term_months` (int) | Запрошенный срок | Клиент | 2–4 | К, ИИ, У | GZ (DSCR), КП (изменение срока) |
| `loan_request.repayment_type` (enum: `annuity`, `differentiated`) | Схема погашения | Клиент / ИИ | 2 | ИИ | Расчёт платежа |
| `purpose.category` (enum: `working_capital`, `equipment`, `real_estate`, `other`) | Категория цели | Клиент | 2 | ИИ, У | Риск-скоринг |
| `purpose.description` (string) | Описание цели (экран «Детали заявки») | Клиент | 2 | К, А, У | — |

### Залог

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `collateral.type` (enum: `none`, `real_estate`, `equipment`, `vehicle`, `guarantee`, `other`) | Вид обеспечения | Клиент | 2 | ИИ, У | GZ (LTV), КП |
| `collateral.description` (string, null) | Описание предмета залога | Клиент | 2 | А, У | — |
| `collateral.market_value` (number, null) | Рыночная стоимость | Клиент / оценка | 2, 9 | ИИ, А | GZ (LTV) |
| `collateral.haircut_pct` (number, null) | Дисконт стоимости по политике | ИИ по таблице политики | 9 | ИИ | GZ (LTV) |
| `collateral.valuation_source` (enum: `client`, `ai_agent`, `appraiser`, null) | Кто оценил | Система | 9 | А, У | — |

### Предварительный расчёт (`pre_approval`)

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `max_amount` (number) | Предварительный лимит | ИИ | 3 | К, ИИ | ОФ (ориентир) |
| `indicative_rate_pct` (number) | Ориентировочная ставка | ИИ | 3 | К, ИИ | ОФ |
| `calculated_at` (timestamp) | Время расчёта | ИИ | 3 | Б | — |

### Согласия (`consents`)

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `data_processing_at` (timestamp) | Согласие на обработку данных | Клиент | 1 | Б | Основание для запросов в ФНС |
| `credit_history_check_at` (timestamp) | Согласие на запрос БКИ | Клиент | 2 | Б | Основание для запроса БКИ |
| `submit_confirmed_at` (timestamp, null) | Клиент подтвердил отправку; с этого момента начинается проверка документов | Клиент в чате | 4 | ИИ, Б | Переход 4 → 5 |

### Документы по заявке (`document_requirements[]`)

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `requirement_id` (id) | Идентификатор требования | Система | 5–6 | Б | — |
| `document_type` (enum, как `documents[].document_type`) | Какой документ требуется | ИИ / А / У | 5–12 | ИИ, А, У | Переход 5 → 6 |
| `period_from`, `period_to` (date) | Требуемый период | ИИ | 5 | К, ИИ | — |
| `status` (enum: `requested`, `received`, `verified`, `rejected`) | Состояние требования | ИИ | 5–6 | К, ИИ | Цикл 6 → 5 |
| `document_id` (id → Borrower Profile.documents, null) | Закрывающий документ | Система | 5–6 | ИИ | — |
| `requested_by` (enum: `ai_agent`, `analyst`, `underwriter`) | Инициатор запроса | Система | 5–12 | А, У | — |
| `requested_at`, `fulfilled_at` (timestamp) | Время запроса и закрытия | Система | 5–12 | Б | — |
| `comment` (string, null) | Что именно не так, текст для клиента в чате | ИИ | 6 | К, ИИ | — |

### Исполнители (`assignment`)

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `assignment.analyst_user_id` (id → User, null) | Назначенный аналитик (вкладки «Мои», «Новые эскалации») | Система | 10 | А | ЭСК |
| `assignment.underwriter_user_id` (id → User, null) | Назначенный андеррайтер (вкладки «Мои», «Ждут решения») | Система | 12 | У | — |

### Закрытие (`closure`)

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `closure.closed_at` (timestamp, null) | Время закрытия без выдачи | Система | Ф | К, Б | — |
| `closure.reason` (enum: `auto_declined`, `underwriter_declined`, `offer_rejected`, `client_abandoned`) | Причина закрытия, определяет вид главной у клиента | Система | Ф | К, Б | СФ, ОФ |

## 8.3. Credit Assessment

Результат анализа заявки, одна версия на один расчёт. После завершения (`status = completed`) не меняется. Решения андеррайтера хранятся в Approval History.

### Идентификация и контекст

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `assessment_id` (id) | Первичный ключ | Система | 7 | Все | — |
| `application_id` (id → Loan Application) | Родительская заявка | Система | 7 | Все | — |
| `sequence` (int) | Номер версии в рамках заявки | Система | 7 | Б | — |
| `status` (enum: `in_progress`, `completed`, `superseded`) | Состояние расчёта | Система | 7–9 | ИИ | — |
| `trigger` (enum: `initial`, `more_information_received`, `analyst_request`) | Причина новой версии | Система | 7 | Б | Цикл 6 → 7 |
| `policy_version` (string) | Версия кредитной политики, по ней пороги можно восстановить | Система | 7 | Б | Все пороги |
| `model_version` (string) | Версия ИИ-модели | Система | 7 | Б | ЭСК |
| `calculated_at`, `created_at` (timestamp) | Время расчёта и создания | Система | 7 | Б | — |

### Входные данные расчёта (`inputs`)

Неизменяемый снимок значений на момент расчёта. Профиль и заявка меняются, без снимка результат нельзя воспроизвести.

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `loan_amount`, `term_months`, `rate_pct` | Параметры, по которым считались показатели | Заявка, `pre_approval` | 7–9 | ИИ | GZ, КП |
| `annual_turnover` (number) | Годовой оборот | Профиль → `financials` | 9 | ИИ, А | GZ (лимит суммы) |
| `ebitda` (number) | EBITDA | Профиль → `financials` | 9 | ИИ, А | GZ (DSCR), АН |
| `existing_debt_service_12m` (number) | Платежи по действующим долгам за 12 мес. | Профиль → `bki_data` × 12 | 9 | ИИ | GZ (DSCR) |
| `new_debt_service_12m` (number) | Платежи по новому кредиту за 12 мес. | Расчёт | 9 | ИИ | GZ (DSCR) |
| `total_future_debt_service` (number) | Сумма двух предыдущих | Расчёт | 9 | ИИ | GZ, СФ (DSCR < 0,9), АН |
| `collateral_market_value`, `collateral_haircut_pct` (number, null) | Параметры залога | Заявка → `collateral` | 9 | ИИ | GZ (LTV) |
| `business_age_months` (int) | Возраст бизнеса | Расчёт от `registration_date` | 7 | ИИ | ЭСК |
| `revenue_change_pct` (number) | Динамика выручки | Профиль → `financials` | 9 | ИИ | GZ, КП |
| `cash_flow_negative_months` (int) | Число месяцев подряд с Cash Flow < 0 | Расчёт по `cash_flow_last_12m` | 9 | ИИ | СФ |
| `credit_history_quality` (enum) | Качество кредитной истории | Профиль → `bki_data` | 7 | ИИ | GZ, КП |

### Расчётные показатели (`metrics`)

| Поле | Формула | Порог (политика) | Роль показателя |
|---|---|---|---|
| `dscr` (number) | `EBITDA / Total Future Debt Service` | Стоп-фактор < 0,9. Green Zone ≥ 1,1 | Участвует в решении: СФ, GZ, КП |
| `ltv_pct` (number, null) | `Loan Amount / (Market Value × (1 − Haircut)) × 100`, без залога `null` | Green Zone ≤ 70 % | Участвует в решении: GZ, КП |
| `debt_burden_pct` (number) | `Total Future Debt Service / EBITDA × 100` (`= 100 / DSCR`) | Порога нет | АН: показывается аналитику и андеррайтеру, в решение не входит |

Источник данных: расчёт ИИ на этапе 9 из блока `inputs`. Роль: ИИ считает, А и У читают. Debt Burden не используется в маршрутизации, Green Zone, контр-предложениях и формировании оффера, потому что полностью выражается через DSCR.

### Скоринг ИИ (`ai_scoring`)

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `risk_grade` (enum: `A`, `B`, `C`, `D`, `E`) | Риск-грейд (часть, не окончательное решение) | ИИ-модель | 7 | ИИ, А, У | GZ, маршрутизация |
| `risk_score` (number 0–100) | Числовой скоринг | ИИ-модель | 7 | ИИ | — |
| `model_confidence_pct` (number) | Уверенность модели | ИИ-модель | 7 | ИИ | ЭСК (< 80 %) |

### Стоп-факторы (`stop_factor_checks[]`)

Поля элемента: `code`, `group` (`legal`, `financial`, `fictitiousness`), `triggered` (bool), `actual`, `source` (путь к полю-источнику). Любой сработавший стоп-фактор ведёт к `route = auto_decline`.

| Код | Назначение | Правило кредитной политики | Источник |
|---|---|---|---|
| `bankruptcy` | Банкротство | Действующее банкротство → автоотказ | `fns_data.bankruptcy_status = bankruptcy` |
| `observation_procedure` | Процедура наблюдения | Процедура наблюдения → автоотказ | `fns_data.bankruptcy_status = observation` |
| `account_blocked_115fz` | Блокировка счёта | Заблокированные счета по 115-ФЗ → автоотказ | `fns_data.has_account_block_115fz` |
| `sanctions` | Санкционные ограничения | Собственность в санкционных списках → автоотказ | `compliance.sanctions_hit` |
| `prohibited_activity` | Запрещённая деятельность | Запрещённый вид деятельности → автоотказ | `compliance.is_prohibited_activity` |
| `cash_flow_negative_over_3m` | Отрицательный денежный поток | Cash Flow < 0 более 3 месяцев → автоотказ | `inputs.cash_flow_negative_months` |
| `dscr_below_0_9` | Низкий DSCR | DSCR < 0,9 → автоотказ | `metrics.dscr` |
| `mass_address` | Массовый адрес | Признак фиктивности → автоотказ | `fns_data.is_mass_address` |
| `mass_director` | Массовый директор | Признак фиктивности → автоотказ | `fns_data.is_mass_director` |
| `no_tax_activity` | Нет налоговой активности | Признак фиктивности → автоотказ | `fns_data.has_tax_activity = false` |

Этап: 5, 7, 8. Роль: проверяет ИИ. Результат видят клиент (причина) и сотрудники.

### Основания передачи аналитику (`escalation_checks[]`)

Поля элемента: `code`, `triggered`, `actual`, `threshold`. Любое сработавшее основание ведёт к `route = analyst_escalation`.

| Код | Условие | Порог |
|---|---|---|
| `business_age_lt_12m` | Возраст бизнеса меньше порога | 12 месяцев |
| `model_confidence_lt_80` | Уверенность модели меньше порога | 80 % |
| `conflicting_sources` | Число конфликтов между данными ФНС, БКИ, документов и выписок | 0 (любой конфликт) |

Этап: 8–10. Роль: ИИ определяет, А принимает случай.

### Green Zone (`green_zone_checks[]`)

Поля элемента: `code`, `actual`, `operator`, `threshold`, `passed` (`true`, `false`, `null` если проверка неприменима). Зелёная зона: все применимые проверки пройдены, стоп-факторов и оснований передачи нет.

| Код | Формула | Порог | При нарушении |
|---|---|---|---|
| `amount_limit` | `loan_amount` | ≤ min(5 000 000 ₽, 20 % годового оборота), см. вопрос 1 | КП `amount_limit_exceeded` |
| `dscr` | `EBITDA / Total Future Debt Service` | ≥ 1,1 | КП `dscr_below_threshold` |
| `ltv` | `Loan Amount / (Market Value × (1 − Haircut)) × 100` | ≤ 70 %. Без залога `null` | КП `ltv_exceeded` |
| `revenue_change` | `revenue_change_pct` | Падение выручки 20–30 % = риск выше среднего | КП `above_average_risk` |
| `credit_history` | `credit_history_quality` | `weak` = риск выше среднего | КП `above_average_risk`, при слабой КИ передача аналитику |

Этап: 8–9. Роль: ИИ.

### Маршрут (`route`)

`route` (enum: `auto_decline`, `green_zone`, `analyst_escalation`) — результат маршрутизации на этапе 8. Приоритет: стоп-факторы → основания передачи → Green Zone. Роль: ИИ определяет, значение попадает в `loan_application.routing_status`.

### Контр-предложения (`counter_offer_triggers[]`)

Поля элемента: `code`, `triggered`, `recommended_action`, `recommended_terms` (`amount`, `term_months`, `rate_delta_pp`). В массив попадают только сработавшие.

| Код | Условие | Действие (`recommended_action`) |
|---|---|---|
| `amount_limit_exceeded` | Сумма больше лимита автоодобрения | `reduce_amount_to_limit`: одобрить меньшую из величин (5 млн ₽ или 20 % оборота) |
| `dscr_below_threshold` | DSCR < 1,1 | `extend_term`: увеличить срок, пересчитать платёж и DSCR до ≥ 1,1 |
| `ltv_exceeded` | LTV > 70 % | `reduce_amount_or_add_collateral`: снизить сумму до LTV ≤ 70 %, при отказе клиента — добавить залог или поручительство, иначе аналитик |
| `above_average_risk` | Падение выручки 20–30 % или слабая КИ | `raise_rate`: базовая ставка + 1–3 п. п. |

Этап: 9–13. Роль: ИИ предлагает, А и У корректируют. Связь: ОФ.

### Автоотказ (`auto_decline`)

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `reason_codes` (string[]) | Коды сработавших стоп-факторов | ИИ | 8 | К, А, У | СФ |
| `client_explanation` (string) | Текст причины для клиента (в чате и на главной) | ИИ | 8 | К | СФ |
| `declined_at` (timestamp) | Время отказа | Система | 8 | Б | — |

`null`, если автоотказа нет.

### AI Credit Memo (`ai_credit_memo`)

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `summary` (string) | Краткое заключение | ИИ | 9 | А, У | — |
| `key_risks` (string[]) | Ключевые риски | ИИ | 9 | А, У | ЭСК, КП |
| `recommendation` (enum: `approve`, `counter_offer`, `decline`) | Рекомендация ИИ | ИИ | 9 | У | ОФ |
| `generated_at` (timestamp) | Время формирования | ИИ | 9 | Б | — |

### Заключение аналитика (`analyst_conclusion`)

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `analyst_user_id` (id → User) | Автор | Система | 10–11 | А | ЭСК |
| `recommendation` (enum: `approve`, `counter_offer`, `decline`) | Рекомендация аналитика | А | 11 | У | ОФ |
| `conclusion_text` (string) | Заключение (кнопка «Отправить заключение андеррайтеру») | А | 11 | А, У | — |
| `completed_at` (timestamp) | Время передачи андеррайтеру | А | 11 | Б | — |

`null`, если эскалации не было.

## 8.4. Offer

Версия предложения клиенту. По одной заявке их может быть несколько.

### Идентификация и жизненный цикл

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `offer_id` (id) | Первичный ключ | Система | 9–13 | Все | — |
| `application_id` (id) | Заявка (см. правило денормализации в разделе 1) | Система | 9–13 | Все | — |
| `assessment_id` (id) | Версия оценки, на которой построен оффер | Система | 9–13 | А, У | ОФ |
| `offer_type` (enum: `ai_offer`, `analyst_offer`, `underwriter_counter_offer`, `final_offer`) | Происхождение оффера | Система | 9–13 | А, У | ОФ, КП |
| `sequence` (int) | Номер оффера в заявке | Система | 9–13 | Б | — |
| `parent_offer_id` (id, null) | Предыдущая версия в цепочке | Система | 11–13 | А, У | КП |
| `status` (enum: `draft`, `presented`, `accepted`, `rejected`, `expired`, `superseded`) | Состояние оффера | Система | 13–15 | К, У | ОФ |
| `created_by.actor_type` (enum: `ai_agent`, `analyst`, `underwriter`) | Тип автора | Система | 9–13 | А, У | — |
| `created_by.user_id` (id → User, null для ИИ) | Сотрудник-автор | Система | 9–13 | А, У, АДМ | — |
| `created_at` (timestamp) | Время создания | Система | 9–13 | Б | — |

Только `final_offer` в статусе `presented` показывается клиенту. Остальные версии служебные.

### Условия

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `terms.amount` (number) | Сумма | ИИ / А / У | 13 | К, А, У | ОФ, КП |
| `terms.currency` (string) | Валюта | Система | 13 | Б | КД |
| `terms.term_months` (int) | Срок | ИИ / А / У | 13 | К, А, У | ОФ, КП |
| `terms.rate_pct` (number) | Годовая ставка | ИИ / А / У | 13 | К, А, У | ОФ, КП (`raise_rate`) |
| `terms.repayment_type` (enum: `annuity`, `differentiated`) | Схема погашения | ИИ / У | 13 | К | КД |
| `terms.monthly_payment` (number) | Ежемесячный платёж | Расчёт | 13 | К | КД |
| `collateral_requirements.type` (enum, как `collateral.type`) | Требуемое обеспечение | У | 12–13 | К, У | КП (`ltv_exceeded`) |
| `collateral_requirements.guarantor_required` (bool) | Нужно ли поручительство | У | 12–13 | К, У | КП |
| `collateral_requirements.min_collateral_value` (number, null) | Минимальная стоимость залога | ИИ / У | 12–13 | У | КП |

### Основания и изменения

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `changes_from_parent[]` (`field`, `previous`, `new`, `reason_code`) | Что изменилось относительно предыдущей версии (подсветка «Было» в контр-предложении); `reason_code` — код контр-предложения | Система | 11–13 | К, А, У | КП |
| `decision_basis` (string[]) | Коды оснований оффера | ИИ / А / У | 9–13 | А, У | ОФ |
| `client_explanation` (string) | Текст для клиента | ИИ / У | 13 | К | ОФ |

### Показ клиенту и решение клиента

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `presented_at` (timestamp, null) | Когда оффер показан | Система | 13 | К | — |
| `valid_until` (timestamp, null) | Срок действия | Система | 13 | К | — |
| `client_decision.decision` (enum: `accepted`, `rejected`, null) | Решение клиента (кнопки «Принять»/«Отклонить») | К | 14–15 | К | КД, закрытие |
| `client_decision.decided_at` (timestamp, null) | Время решения | Система | 14–15 | Б | — |
| `client_decision.rejection_reason` (string, null) | Причина отказа клиента | К | 15 | У | — |

## 8.5. Loan Contract

Договор создаётся только после акцепта `final_offer`. Условия копируются из оффера как неизменяемый снимок.

### Идентификация и статус

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `contract_id` (id) | Первичный ключ | Система | 16 | Все | — |
| `contract_number` (string) | Номер договора | Система | 16 | К, У | КД |
| `offer_id` (id, UNIQUE) | Принятый оффер, единственная связь с заявкой и профилем | Система | 16 | Б | ОФ |
| `status` (enum: `draft`, `awaiting_signature`, `signed`, `active`, `overdue`, `closed`) | Статус кредита (раздел «Кредиты») | Система | 16–Ф | К, Б | КД |
| `created_at`, `updated_at` (timestamp) | Аудит | Система | 16–Ф | Б | — |

### Условия кредита

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `principal_amount` (number) | Сумма кредита | Оффер | 16 | К, Б | КД |
| `currency` (string) | Валюта | Оффер | 16 | Б | КД |
| `term_months` (int) | Срок | Оффер | 16 | К, Б | КД |
| `interest_rate_pct` (number) | Ставка | Оффер | 16 | К, Б | КД |
| `repayment_type` (enum) | Схема погашения | Оффер | 16 | К, Б | КД |
| `monthly_payment` (number) | Ежемесячный платёж | Оффер | 16 | К, Б | КД |
| `maturity_date` (date) | Дата окончания | Расчёт | 18 | К, Б | КД |

### Подписание и выдача

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `signed_at` (timestamp, null) | Дата подписания | Система ЭП | 17 | К, Б | КД |
| `signature.method` (enum: `e_sign`), `signature.signature_id` (string) | Способ и идентификатор подписи | Система ЭП | 17 | Б | КД |
| `disbursed_at` (timestamp, null) | Дата выдачи | Банк | 18 | К, Б | КД |
| `disbursement.account_number` (string) | Счёт зачисления (из профиля на момент выдачи) | Профиль | 18 | К, Б | КД |
| `disbursement.amount` (number) | Выданная сумма | Банк | 18 | К, Б | КД |
| `disbursement.transaction_id` (string) | Идентификатор проводки | Банк | 18 | Б | КД |

### График платежей (`payment_schedule[]`)

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `installment_no` (int) | Номер платежа | Расчёт | 16 | К | КД |
| `due_date` (date) | Дата платежа | Расчёт | 16 | К | КД |
| `principal_amount`, `interest_amount`, `total_amount` (number) | Основной долг, проценты, итого | Расчёт | 16 | К | КД |
| `balance_after` (number) | Остаток долга после платежа | Расчёт | 16 | К | КД |
| `payment_status` (enum: `scheduled`, `paid`, `overdue`) | Состояние платежа | Банк | 18–Ф | К, Б | КД |

Остаток долга и ближайший платёж на экране «Кредиты» вычисляются из графика и отдельно не хранятся.

### Документы договора (`documents[]`)

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `document_type` (enum: `loan_agreement`, `payment_schedule`, `consent`) | Тип документа | Система | 16–17 | К | КД |
| `file_uri` (string) | Адрес файла | Система | 16 | К | КД |
| `signed_at` (timestamp, null) | Время подписания (раздел «Документы») | Система ЭП | 17 | К | КД |

---

## 8.6. User

Сотрудник банка. Обеспечивает вход по логину и паролю, права доступа к рабочим зонам и привязку каждого действия к исполнителю. Учётные данные (пароль, сессии) хранятся в сервисе аутентификации и в модель не входят.

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `user_id` (id) | Первичный ключ, значение для всех ссылок на сотрудника | Система | Любой | Все | Привязка действий |
| `login` (string, UNIQUE) | Логин для входа в рабочую зону сотрудников | АДМ | Любой | А, У, АДМ | — |
| `full_name` (string) | ФИО (шапка рабочей зоны, «Исполнитель») | АДМ | Любой | А, У, АДМ | — |
| `email` (string) | Почта для уведомлений | АДМ | Любой | А, У | Notification |
| `role` (enum: `ANALYST`, `UNDERWRITER`, `ADMIN`) | Роль и набор доступных экранов и действий | АДМ | Любой | АДМ, Б | ЭСК (аналитик), решения (андеррайтер) |
| `status` (enum: `active`, `inactive`, `blocked`) | Возможность входа и получения заявок | АДМ | Любой | АДМ | — |
| `last_login_at` (timestamp, null) | Последний вход | Система | Любой | АДМ | — |
| `created_at`, `updated_at` (timestamp) | Аудит | Система | Любой | АДМ | — |

Права по ролям:
- `ANALYST`: видит эскалации и запросы на экспертизу, запрашивает документы через ИИ, принимает запросы на экспертизу, отправляет заключения;
- `UNDERWRITER`: принимает решения (`approved`, `conditional_approval`, `declined`, `more_information_required`), запрашивает документы и экспертизу, формирует контр-предложения;
- `ADMIN`: управляет пользователями, решений по заявкам не принимает.

## 8.7. Chat History

Журнал диалога клиента с ИИ-кредитным агентом. Именно из него строятся экраны чата и подтверждения действий. Сообщения не редактируются и не удаляются. Статус заявки в чате берётся из `loan_application.status`, а не хранится в сообщениях.

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `message_id` (id) | Первичный ключ | Система | 1–Ф | Все | — |
| `borrower_id` (id → Borrower Profile) | Владелец диалога | Система | 1–Ф | К, ИИ | — |
| `application_id` (id → Loan Application, null) | Заявка, к которой относится сообщение; `null` до создания заявки | Система | 1–Ф | К, ИИ, А, У | — |
| `sender_type` (enum: `client`, `ai_agent`, `analyst`, `underwriter`, `system`) | Автор сообщения | Система | 1–Ф | ИИ | — |
| `message_type` (enum: `text`, `confirmation_card`, `document_request`, `document_upload`, `status_notification`, `rejection_notice`) | Вид сообщения; определяет отображение (карточка подтверждения, загрузка файлов, уведомление о статусе или отказе) | ИИ | 1–Ф | К, ИИ | СФ (`auto_decline`), ОФ |
| `content` (string) | Текст сообщения | Клиент / ИИ | 1–Ф | К, А, У | — |
| `card_payload` (object, null) | Структура карточки: `card_type`, `fields`, `action` (`action_type`, `status`, `resolved_at`) | ИИ | 2–4 | К, ИИ | Подтверждение отправки (переход 4 → 5) |
| `attachment_document_ids` (id[] → Borrower Profile.documents) | Загруженные в чате документы | Система | 5–6 | К, ИИ, А | Проверка комплектности |
| `requirement_ids` (id[]) | Требования документов, о которых говорит сообщение | ИИ | 5–12 | К, ИИ | Цикл 6 → 5 |
| `created_at` (timestamp) | Время сообщения | Система | 1–Ф | Все | — |

## 8.8. Approval History

История решений андеррайтера по заявке. Финальное решение всегда принимает андеррайтер, поэтому здесь хранятся только его решения. Актуальное решение — запись с максимальным `decided_at`.

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `approval_id` (id) | Первичный ключ | Система | 12 | У, Б | — |
| `application_id` (id → Loan Application) | Заявка | Система | 12 | У, Б | — |
| `assessment_id` (id → Credit Assessment) | Версия оценки, на основании которой принято решение | Система | 12 | А, У | — |
| `decision` (enum: `approved`, `conditional_approval`, `declined`, `more_information_required`) | Решение; определяет следующий статус заявки | У | 12 | У, К | ОФ, КП, закрытие |
| `decided_by_user_id` (id → User) | Андеррайтер, принявший решение | Система | 12 | У, АДМ | Привязка к сотруднику |
| `reason_codes` (string[]) | Основание решения (коды стоп-причин, отказа, условий) | У | 12 | У, К | КП, СФ |
| `client_explanation` (string, null) | Причина для клиента при отказе или изменении условий | У | 12 | К | ОФ |
| `comment` (string, null) | Внутренний комментарий | У | 12 | А, У | — |
| `resulting_offer_id` (id → Offer, null) | Оффер, созданный по решению (для `approved` и `conditional_approval`) | Система | 12–13 | У, А | ОФ |
| `decided_at` (timestamp) | Дата решения | Система | 12 | Все | — |

## 8.9. Internal Request

Запросы между участниками процесса: экспертиза андеррайтера у аналитика и запросы документов, которые передаются ИИ-агенту для связи с клиентом. Питает вкладки «Запросы» и «Запросы от андеррайтера» в рабочих зонах.

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `request_id` (id) | Первичный ключ | Система | 10–12 | А, У | — |
| `application_id` (id → Loan Application) | Заявка | Система | 10–12 | А, У | — |
| `request_type` (enum: `expertise`, `document_request`) | Тип запроса | А / У | 10–12 | А, У | ЭСК |
| `from_user_id` (id → User) | Инициатор | Система | 10–12 | А, У | Привязка к сотруднику |
| `to_target` (enum: `analyst`, `underwriter`, `ai_agent`) | Тип адресата; документы всегда уходят `ai_agent` | Система | 10–12 | А, У, ИИ | — |
| `to_user_id` (id → User, null) | Конкретный сотрудник-адресат, если назначен | Система | 10–12 | А, У | — |
| `message` (string) | Вопрос для экспертизы или формулировка запроса документов | А / У | 10–12 | А, У, ИИ | — |
| `requirement_ids` (id[]) | Требования документов, созданные по запросу | Система | 10–12 | ИИ | Цикл 6 → 5 |
| `status` (enum: `created`, `accepted`, `completed`, `returned`) | Состояние: создан, принят в работу, выполнен, возвращён с комментарием | А / У | 10–12 | А, У | — |
| `due_at` (timestamp, null) | Срок выполнения (окно «Запрос на экспертизу») | У | 10–12 | А | — |
| `created_at`, `accepted_at`, `resolved_at` (timestamp, null кроме `created_at`) | Хронология | Система | 10–12 | Б | — |
| `response_message` (string, null) | Ответ или комментарий возврата | А / У | 10–12 | А, У | — |

## 8.10. Application Event

Журнал действий по заявке. Единственное место, где хранится история статусов и привязка каждого действия к исполнителю.

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `event_id` (id) | Первичный ключ | Система | 1–Ф | Б, АДМ | — |
| `application_id` (id → Loan Application) | Заявка | Система | 1–Ф | Все | — |
| `event_type` (enum: `status_changed`, `assignment_changed`, `decision_recorded`, `request_created`, `request_accepted`, `request_completed`, `request_returned`, `offer_created`, `offer_decision`, `document_uploaded`, `comment_added`) | Вид действия | Система | 1–Ф | А, У, АДМ | — |
| `actor_type` (enum: `client`, `employee`, `ai_agent`, `system`) | Кто выполнил действие | Система | 1–Ф | А, У, АДМ | — |
| `actor_user_id` (id → User, null) | Сотрудник-исполнитель; заполняется при `actor_type = employee` | Система | 1–Ф | А, У, АДМ | Привязка к сотруднику |
| `from_status`, `to_status` (enum статусов заявки, null) | Смена статуса (для `status_changed` и связанных событий) | Система | 1–Ф | Все | — |
| `entity_type` (enum: `application`, `assessment`, `offer`, `contract`, `request`, `document`) | Тип объекта действия | Система | 1–Ф | Б | — |
| `entity_id` (id) | Идентификатор объекта действия | Система | 1–Ф | Б | — |
| `comment` (string, null) | Пояснение (например, причина возврата) | Система / сотрудник | 1–Ф | А, У | — |
| `created_at` (timestamp) | Время действия | Система | 1–Ф | Все | — |

Правило: любое изменение статуса, назначение, решение, запрос или создание оффера сотрудником записывается событием с `actor_user_id`. Записи не изменяются.

## 8.11. Notification

Системные уведомления клиентам и сотрудникам (статус заявки, запрос документов, готовность оффера, договор на подписание, зачисление средств, входящий запрос аналитику или андеррайтеру).

| Поле | Назначение | Источник | Этап | Роль | Связь |
|---|---|---|---|---|---|
| `notification_id` (id) | Первичный ключ | Система | 1–Ф | Б | — |
| `recipient_type` (enum: `borrower`, `employee`) | Тип получателя | Система | 1–Ф | Б | — |
| `recipient_id` (id → Borrower Profile или User) | Получатель | Система | 1–Ф | Б | — |
| `application_id` (id → Loan Application, null) | Заявка, к которой относится уведомление | Система | 1–Ф | К, А, У | — |
| `notification_type` (enum: `status_changed`, `document_request`, `offer_ready`, `contract_to_sign`, `funds_disbursed`, `expertise_request`, `underwriter_request`, `decision_updated`) | Тип события; определяет шаблон | Система | 1–Ф | К, А, У | ОФ, КД, СФ |
| `channel` (enum: `in_app`, `email`, `sms`) | Канал доставки | Система | 1–Ф | Б | — |
| `title`, `message` (string) | Заголовок и текст | Система / ИИ | 1–Ф | К, А, У | — |
| `status` (enum: `pending`, `sent`, `delivered`, `read`) | Состояние доставки | Система | 1–Ф | Б | — |
| `created_at`, `sent_at`, `read_at` (timestamp, null кроме `created_at`) | Хронология | Система | 1–Ф | Б | — |
