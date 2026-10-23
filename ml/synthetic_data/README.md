# Синтетические данные ММБ

Рабочая структура: `financials.py` генерирует финансовый блок существующих профилей,
`validation.py` проверяет согласованность исходных данных, `tests/fixtures/` содержит
**неизменяемые** тестовые JSON, а `data/` — генерируемые результаты.

## Команды из корня репозитория (PowerShell, uv-проект в `backend/`)

```powershell
uv run --project backend python -m unittest discover -s ml/synthetic_data/tests -t ml/synthetic_data -p "test_*.py" -v

uv run --project backend python ml/synthetic_data/financials.py `
  --profiles ml/synthetic_data/tests/fixtures/profiles.json `
  --out ml/synthetic_data/data/profiles_generated.json `
  --seed 42

uv run --project backend python ml/synthetic_data/validation.py `
  --profiles ml/synthetic_data/data/profiles_generated.json `
  --applications ml/synthetic_data/tests/fixtures/applications.json `
  --report ml/synthetic_data/data/quality_report.json
```

В PowerShell символ `` ` `` — перенос команды. Команды можно вводить и в одну строку.

## Команды из `ml/synthetic_data/`

```powershell
uv run --project ..\..\backend python -m unittest discover -s tests -t . -p "test_*.py" -v
uv run --project ..\..\backend python financials.py --profiles tests\fixtures\profiles.json --out data\profiles_generated.json --seed 42
uv run --project ..\..\backend python validation.py --profiles data\profiles_generated.json --applications tests\fixtures\applications.json --report data\quality_report.json
```

`assessments.json` используется только в unit-тестах полной кредитной оценки.
Не передавайте его при валидации **перегенерированного** финансового профиля:
эта эталонная оценка содержит входные данные, относящиеся к исходному профилю.

`financials.py` пока не создает компании с нуля. `company.py` и его тесты
будут добавлены позднее. Проверка `passed: true` означает отсутствие ошибок
по реализованным правилам, а не доказанную статистическую реалистичность.

## Новое: генерация компаний (`company.py`)

Модуль `company.py` создаёт **полные Borrower Profile**, включая блок
`financials` посредством существующей функции `generate_financials()`.
`financials.py` не переписан. Компания и её финансовые данные создаются
согласованно; фикстуры в `tests/fixtures/` не изменяются.

Из корня Git-репозитория (PowerShell, зависимости через `backend/pyproject.toml`):

```powershell
uv run --project backend python ml/synthetic_data/company.py `
  --count 1200 --seed 42 --as-of 2026-09-30 --mix population `
  --out ml/synthetic_data/data/profiles_generated.json `
  --summary-out ml/synthetic_data/data/company_summary.json

uv run --project backend python ml/synthetic_data/validation.py `
  --profiles ml/synthetic_data/data/profiles_generated.json `
  --applications ml/synthetic_data/tests/fixtures/empty_applications.json `
  --report ml/synthetic_data/data/quality_report.json

uv run --project backend python -m unittest discover `
  -s ml/synthetic_data/tests -t ml/synthetic_data `
  -p "test_*.py" -v
```

`empty_applications.json` содержит `[]`, поскольку модуль компаний не
генерирует кредитные заявки. Использовать `tests/fixtures/applications.json`
с новыми профилями пока нельзя: эта фикстура содержит другой borrower_id.

Для сценарного набора, намеренно смещённого к ООО и малому бизнесу, используй
`--mix demo` и **другой** `--out`. Это не репрезентативная выборка клиентов банка.

### Наши распределения

- **Тип компании × категория МСП:** категориальное распределение.
  `population` взят из агрегированных численностей ФНС на 10.09.2026;
  юридические лица в MVP считаются ООО. `demo` использует заранее заданные
  веса 55% микро-ООО, 20% микро-ИП, 22% малые ООО, 3% малые ИП.
- **Регион и ОКВЭД:** категориальные распределения с *произвольными*
  демонстрационными весами по 12 регионам и 7 отраслям.
- **Возраст компании:** сдвинутое Gamma(k=2, scale=30 месяцев)
  +25 месяцев, обрезка до 240. Молодые (<24 полных месяцев) исключены
  ввиду ограничений `financials.py`.
- **Численность микро:** с заданной вероятностью ноль сотрудников,
  иначе геометрическое распределение Geometric(p=0.34) с ограничением в 15.
- **Численность малых:** 16 + LogNormal(mu=2.2, sigma=0.8) с ограничением
  в 100. Это упрощение: реальная категория может также определяться доходом.
- **Финансовые показатели:** условные распределения из `financials.py`;
  по величине оборота вводится дополнительный отбор по сегменту. Этот отбор
  может искажать распределение у правого хвоста.
- **ФНС, комплаенс и БКИ:** нейтральные заглушки (все active/clean,
  долгов и просрочек нет). Эти блоки нельзя использовать для обучения
  кредитного риска или для проверки долей отказов. Позже будут отдельные
  генераторы для ФНС/БКИ и инъекция негативных кейсов.

В `company_summary.json` сохраняются статистики выхода генератора,
но **не** утверждение о совпадении распределений с реальными клиентами.
ИНН/ОГРН проходят контрольные цифры, но не проверены на отсутствие
совпадений с реальными организациями. Адреса, имена, телефон и счета
вымышлены; не используйте их для настоящих запросов во внешние сервисы.
