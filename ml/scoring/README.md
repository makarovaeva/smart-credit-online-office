# SME Credit Scoring — полная папка модуля

**Версия пакета: 1.4 (собраны файлы из предыдущих v0.9–v1.3 и добавлен каталог feature contract).**

Это **офлайн прототип для хакатона**: генерация, сравнение Logistic Regression / CatBoost / LightGBM, вероятность дефолта на *искусственных метках*, калибровка и диагностические отчёты. Достоверность кредитного риска на реальных заёмщиках **не доказана**.

## Главные файлы

- `main.py` — **главная точка входа**, оркестратор генератора `ml/synthetic_data/main.py` и обучения с калибровкой.
- `train_scoring.py` — признаки, маркировка, Logistic / CatBoost / LightGBM, базовое сравнение.
- `calibrate_scoring.py` — четыре независимые части данных: train, validation, calibration, test; Platt / isotonic, метрики, сохранение моделей.
- `audit_predictions.py` — дополнительные sanity/leakage проверки старого эксперимента.
- `final_analysis.ipynb` — **основной итоговый ноутбук**, читает результаты `main.py` или `calibrate_scoring.py`.
- `analysis_results.ipynb` — прежний ноутбук для **некалиброванного** сравнения; можно не использовать.
- `feature_contract.json` / `FEATURE_CONTRACT.md` — точный перечень входных признаков, смысл, типы, единицы, запреты.
- `tests/` — unit-тесты. `data/` — результаты экспериментов, **не коммитим**.

**Документация по деталям:** `README_FINAL_PIPELINE.md`, `README_CALIBRATION.md`, `README_AUDIT.md`, `README_ANALYSIS.md`.

## Команда запуска (из корня репозитория, PowerShell)

```powershell
uv run --no-project --with numpy --with pandas `
  --with scikit-learn --with catboost --with lightgbm `
  --with matplotlib --with joblib `
  python ml/scoring/main.py `
  --generate --count 3000 --seed 43 --scenario baseline `
  --simulate-outcomes --model all `
  --out-dir ml/scoring/data/experiment_43
```

**Если директория уже заполнена, выбери новое имя** либо используй `--overwrite` только если сознательно заменяешь результаты.

## Ноутбук

```powershell
uv run --no-project --with jupyterlab --with ipykernel `
  --with numpy --with pandas --with matplotlib --with scikit-learn `
  jupyter lab `
  --ServerApp.root_dir="W:/Projects/smart-credit-online-office" `
  ml/scoring/final_analysis.ipynb
```

Вместо `W:/Projects/smart-credit-online-office` подставь **свою реальную корневую директорию**.
Первая кодовая ячейка ноутбука позволяет выбрать результаты через `RUN_DIR`/`SCORING_RUN_DIR`.

## Тесты

```powershell
uv run --no-project --with numpy --with pandas `
  --with scikit-learn --with catboost --with lightgbm `
  --with matplotlib --with joblib `
  python -m unittest discover -s ml/scoring/tests -t ml/scoring -p "test_*.py" -v
```

## Docker (контейнер офлайн-обучения)

**В отличие от `ml/scoring/`, файлы образа лежат на уровне `ml/`:**
`ml/Dockerfile` и `ml/Dockerfile.dockerignore`. Они включены в ZIP.

```powershell
docker build -f ml/Dockerfile -t sme-credit-ml .
docker run --rm -v "${PWD}/ml/scoring/data:/app/ml/scoring/data" `
  sme-credit-ml --generate --count 3000 --seed 43 `
  --scenario baseline --simulate-outcomes --model all `
  --out-dir /app/ml/scoring/data/docker_experiment_43
```

Dockerfile есть, но он не заменяет FastAPI inference-сервис. Образ нужно проверить локально с установленным Docker.

## Git

Коммитить скрипты, ноутбуки, README, contract и тесты, но **не** `data/`, `*.cbm`, `*.joblib`, `*.lgb.txt`, виртуальные окружения или секреты. Если у тебя уже есть `ml/scoring/`, перед копированием сравни файлы, чтобы не потерять свои изменения.
