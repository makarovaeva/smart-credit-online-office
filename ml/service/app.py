"""HTTP-сервис инференса скоринга поверх ml/scoring.

Логика модели не дублируется: признаки, вероятность и SHAP-факторы считают
predict.py и explain.py. Сервис только принимает профиль заёмщика и заявку
в формате docs/credit_mmb_data_model_updated.md и отдаёт результат бэкенду.
Решение по заявке модель не принимает - это делает кредитная политика бэкенда.
"""

import os
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

SCORING_DIR = Path(__file__).resolve().parents[1] / "scoring"
sys.path.insert(0, str(SCORING_DIR))

from explain import explain_applications  # noqa: E402
from predict import predict_applications, resolve_scoring_dir  # noqa: E402

MODEL_DIR = Path(os.getenv("ML_MODEL_DIR", "/models/run"))
MODEL_NAME = os.getenv("ML_MODEL_NAME", "catboost")
CALIBRATION = os.getenv("ML_CALIBRATION", "platt")

app = FastAPI(title="Smart Credit ML scoring", version="1.0.0")


class ScoreRequest(BaseModel):
    profile: dict[str, Any]
    application: dict[str, Any]


def _scoring_dir() -> Path:
    return resolve_scoring_dir(MODEL_DIR)


@app.get("/health")
def health() -> dict[str, str]:
    try:
        _scoring_dir()
    except FileNotFoundError as exc:
        raise HTTPException(503, "model artifacts not found") from exc
    return {"status": "ok", "model": MODEL_NAME, "calibration": CALIBRATION}


@app.post("/score")
def score(body: ScoreRequest) -> dict[str, Any]:
    """Вероятность дефолта и SHAP-факторы. Если объяснение не посчиталось,
    вероятность всё равно возвращается (без факторов)."""
    profiles, applications = [body.profile], [body.application]
    try:
        try:
            [result] = explain_applications(
                profiles,
                applications,
                run_dir=_scoring_dir(),
                model_name=MODEL_NAME,
                calibration=CALIBRATION,
                top_n=4,
                limit=1,
            )
        except (ImportError, RuntimeError):
            [result] = predict_applications(
                profiles,
                applications,
                run_dir=_scoring_dir(),
                model_name=MODEL_NAME,
                calibration=CALIBRATION,
            )
    except ValueError as exc:
        # Данные не проходят контракт признаков (например, нет 12 месяцев Cash Flow)
        raise HTTPException(422, str(exc)) from exc
    return result
