# Сервис инференса скоринга. Модель обучается при сборке образа на синтетических
# данных генератора (ml/synthetic_data) с фиксированным seed - результат воспроизводим.
FROM python:3.12.15-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    ML_MODEL_DIR=/models/run

# LightGBM и CatBoost используют OpenMP
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/ml
# Все версии и хеши зафиксированы в lock-файле
COPY service/requirements.lock service/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r service/requirements.lock

COPY synthetic_data synthetic_data
COPY scoring scoring
RUN python scoring/main.py --generate --count 3000 --seed 43 --scenario baseline \
        --simulate-outcomes --model catboost --out-dir /models/run

COPY service service

RUN useradd --create-home --uid 1000 app && chown -R app /models
USER app
EXPOSE 8000

CMD ["uvicorn", "service.app:app", "--host", "0.0.0.0", "--port", "8000"]
