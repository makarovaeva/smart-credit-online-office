#!/bin/sh
# Миграции -> демо-данные (идемпотентно) -> API
set -e

alembic upgrade head

if [ "${SEED_DEMO_DATA:-true}" = "true" ]; then
    python -m scripts.seed
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
