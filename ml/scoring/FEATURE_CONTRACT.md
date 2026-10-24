# Feature Contract v1.0.0 — SME credit scoring

**Зачем нужен:** гарантировать, что при обучении и при инференсе модель получает **одинаковые признаки в одинаковом формате и с одинаковым смыслом**. Это описание соответствуют функции `train_scoring.extract_features` в поставляемой версии.

## Базовые правила

- Цель: `default_12m ∈ {0,1}` — **не входной признак**. При `--simulate-outcomes` это выдуманная метка, а не реальный банковский дефолт.
- Схема: **6 категориальных + 22 числовых** признака, с указанным ниже порядком. `application_id` и `borrower_id` используются только для связывания записей/разбиений.
- Для обучения нужны `profiles_compliance.json` и **исходные** `applications_generated.json`. `applications_assessed.json` и результаты решения банка запрещены из-за утечки целевого сигнала.
- `financials.as_of_date` и `company.registration_date` должны быть не позже `application.created_at`.
- Численные значения должны быть конечными; текущий препроцессинг не допускает `null`/`NaN` в итоговых признаках. При нулевом/отрицательном обороте извлечение признаков прекращается с ошибкой.
- Точки фиксации БКИ/ФНС/комплаенса тоже должны предшествовать заявке; **в текущем `train_scoring.py` нет полного автоматического контроля всех таких timestamp-полей**. Проверку надо добавить до production deployment.
- Отдельный `feature_contract.json` является машинно-читаемым каталогом и проверяется unit-тестом на соответствие константам `CATEGORICAL`, `NUMERICAL`, `FEATURES`.

## Категориальные признаки

| Feature | Источник | Значение |
|---|---|---|
| `legal_form` | `company.legal_form` | ООО / ИП |
| `okved_section` | `company.okved_main.code` | Первые две цифры кода ОКВЭД |
| `credit_history_quality` | `bki_data.credit_history_quality` | Категория качества БКИ |
| `loan_purpose` | `application.purpose.category` | Цель кредита |
| `collateral_type` | `application.collateral.type` | Тип залога |
| `repayment_type` | `application.loan_request.repayment_type` | Тип графика погашения |

## Числовые признаки

| Feature | Источник | Значение/единица |
|---|---|---|
| `age_months` | `company.registration_date, application.created_at` | Полных месяцев со дня регистрации до заявки |
| `employees_count` | `company.employees_count` | Количество сотрудников, человек |
| `log_annual_turnover` | `financials.annual_turnover` | log1p(годового оборота в ₽) |
| `ebitda_margin_pct` | `financials.ebitda, financials.annual_turnover` | 100 × EBITDA / годовой оборот; проценты |
| `revenue_change_pct` | `financials.revenue_change_pct` | Изменение выручки, процентные пункты |
| `negative_cf_months` | `financials.cash_flow_last_12m` | Число отрицательных месяцев из последних 12 |
| `negative_cf_streak` | `financials.cash_flow_last_12m` | Максимум отрицательных месяцев подряд |
| `cf_net_to_turnover` | `financials.cash_flow_last_12m, annual_turnover` | Сумма денежных потоков за 12 месяцев / оборот |
| `active_loans_count` | `bki_data.active_loans_count` | Количество действующих кредитов |
| `debt_to_turnover` | `bki_data.total_debt_amount, annual_turnover` | Остаток долга / оборот |
| `debt_service_to_turnover` | `bki_data.monthly_debt_service, annual_turnover` | 12 × ежемесячное обслуживание текущего долга / оборот |
| `overdue_to_turnover` | `bki_data.overdue_amount, annual_turnover` | Просроченная сумма / оборот |
| `max_overdue_days_12m` | `bki_data.max_overdue_days_12m` | Максимальная просрочка за год, дней |
| `tax_arrears_to_turnover` | `fns_data.tax_arrears_amount, annual_turnover` | Налоговая задолженность / оборот |
| `has_tax_activity` | `fns_data.has_tax_activity` | 1 при налоговой активности, иначе 0 |
| `loan_to_turnover` | `application.loan_request.amount, annual_turnover` | Сумма заявки / оборот |
| `loan_amount_log` | `application.loan_request.amount` | log1p(суммы кредита в ₽) |
| `term_months` | `application.loan_request.term_months` | Срок запрошенного кредита, месяцев |
| `indicative_rate_pct` | `application.pre_approval.indicative_rate_pct` | Индикативная ставка в процентах годовых |
| `has_collateral` | `application.collateral.market_value` | 1, если известна рыночная стоимость залога, иначе 0 |
| `collateral_coverage` | `application.collateral.market_value, loan_request.amount` | Рыночная стоимость залога / сумма заявки, 0 если нет залога |
| `requested_payment_to_turnover` | `loan_request, pre_approval, annual_turnover` | 12 × расчётный платёж по заявке / оборот |

## Важные ограничения

- Название `indicative_rate_pct` означает **проценты**, а не долю: например, `15` = 15%, не `0.15`.
- `ebitda_margin_pct` также выражена в **процентах**, не в долях единицы.
- Оборот и сумма кредита перед логарифмированием измеряются в **рублях**.
- Нулевая `collateral_coverage` при отсутствующем залоге — **специальная конвенция**, связанная с `has_collateral`.
- В дальнейшем inference должен использовать **те же функции преобразования и сохранённый препроцессор**, что и обучение, а не независимо переписанную формулу.
- Любая смена семантики, типов, состава или порядка признаков требует новой версии контракта и переобучения/проверки совместимости моделей.
