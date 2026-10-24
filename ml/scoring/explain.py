"""Local explanations for pre-decision SME scoring (educational synthetic demo).

SHAP attributions explain the *uncalibrated model log-odds*, not the calibrated
probability and NOT a bank underwriting decision. Separate, optionally supplied
Credit Assessments provide actual policy reasons for routing/rejection.

Only load trusted locally trained artifacts: sklearn/joblib uses pickle.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from predict import (
    CATEGORICAL, FEATURES, NUMERICAL, CALIBRATIONS, MODELS,
    _read_array, extract_features, load_contract, load_model,
    predict_applications, resolve_scoring_dir,
)

FEATURE_LABELS = {
    "legal_form": "Организационно-правовая форма",
    "okved_section": "Отрасль бизнеса",
    "credit_history_quality": "Качество кредитной истории",
    "loan_purpose": "Цель кредита",
    "collateral_type": "Вид залога",
    "repayment_type": "Тип погашения",
    "age_months": "Возраст бизнеса",
    "employees_count": "Количество сотрудников",
    "log_annual_turnover": "Годовой оборот",
    "ebitda_margin_pct": "Рентабельность EBITDA",
    "revenue_change_pct": "Изменение выручки",
    "negative_cf_months": "Число месяцев с отрицательным денежным потоком",
    "negative_cf_streak": "Последовательные месяцы с отрицательным денежным потоком",
    "cf_net_to_turnover": "Денежный поток относительно оборота",
    "active_loans_count": "Количество действующих кредитов",
    "debt_to_turnover": "Сумма долга относительно оборота",
    "debt_service_to_turnover": "Кредитные платежи относительно оборота",
    "overdue_to_turnover": "Просроченный долг относительно оборота",
    "max_overdue_days_12m": "Максимальная длительность просрочки",
    "tax_arrears_to_turnover": "Налоговая задолженность относительно оборота",
    "has_tax_activity": "Налоговая активность",
    "loan_to_turnover": "Запрошенная сумма относительно оборота",
    "loan_amount_log": "Запрошенная сумма кредита",
    "term_months": "Срок кредита",
    "indicative_rate_pct": "Предварительная процентная ставка",
    "has_collateral": "Наличие залога",
    "collateral_coverage": "Стоимость залога относительно суммы кредита",
    "requested_payment_to_turnover": "Платёж по новому кредиту относительно оборота",
}

POLICY_LABELS = {
    "bankruptcy": "Сведения о банкротстве",
    "observation_procedure": "Процедура наблюдения",
    "account_blocked_115fz": "Ограничение банковских операций",
    "sanctions": "Результат обязательной комплаенс-проверки",
    "prohibited_activity": "Ограничение по кредитной политике банка",
    "cash_flow_negative_over_3m": "Продолжительный отрицательный денежный поток",
    "dscr_below_0_9": "Недостаточное покрытие платежей денежным результатом бизнеса (DSCR)",
    "mass_address": "Требуется проверка регистрационного адреса",
    "mass_director": "Требуется проверка сведений о руководителе",
    "no_tax_activity": "Недостаточная налоговая активность",
    "business_age_lt_12m": "Бизнес работает менее 12 месяцев",
    "model_confidence_lt_80": "Требуется дополнительная проверка",
    "conflicting_sources": "Противоречия в данных из разных источников",
    "amount_limit": "Запрошенная сумма выше предварительного лимита",
    "dscr": "Недостаточное покрытие кредитных платежей",
    "ltv": "Недостаточная стоимость залога",
    "revenue_change": "Существенное снижение выручки",
    "credit_history": "Кредитная история требует дополнительной оценки",
}


def _binary_shap_values(values: Any, n_rows: int, n_features: int) -> np.ndarray:
    """Normalize binary SHAP output to (N, F) positive-class margins."""
    if isinstance(values, list):
        values = values[-1]
    v = np.asarray(values, dtype=float)
    if v.ndim == 3 and v.shape[-1] == 2:
        v = v[:, :, 1]
    if v.shape != (n_rows, n_features) or not np.isfinite(v).all():
        raise ValueError(f"Unexpected/non-finite SHAP shape {v.shape}; expected {(n_rows, n_features)}")
    return v


def _base_value(value: Any) -> float:
    a = np.asarray(value, dtype=float).reshape(-1)
    if len(a) == 2:
        return float(a[1])
    if len(a) != 1 or not np.isfinite(a[0]):
        raise ValueError("Unexpected SHAP expected_value")
    return float(a[0])


def _load_background(scoring_dir: Path, *, profiles_path: Path | None = None,
                     applications_path: Path | None = None, max_background: int = 100) -> pd.DataFrame:
    """Only train split may define Logistic SHAP background; never use current test data."""
    if (profiles_path is None) != (applications_path is None):
        raise ValueError("Pass BOTH background profiles and background applications")
    root = scoring_dir.parent if scoring_dir.name == "scoring" else scoring_dir
    profiles_path = profiles_path or root / "dataset" / "profiles_compliance.json"
    applications_path = applications_path or root / "dataset" / "applications_generated.json"
    manifest_path = scoring_dir / "split_manifest.csv"
    if not profiles_path.is_file() or not applications_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(
            "Logistic SHAP requires training reference data and split_manifest.csv. "
            "Use --background-profiles/--background-applications, from the original training run."
        )
    manifest = pd.read_csv(manifest_path, dtype={"application_id": str})
    if not {"application_id", "split"}.issubset(manifest.columns):
        raise ValueError("split_manifest.csv missing application_id/split")
    train_ids = set(manifest.loc[manifest["split"] == "train", "application_id"])
    if not train_ids:
        raise ValueError("No train partition in split_manifest.csv")
    profiles = _read_array(profiles_path)
    applications = [a for a in _read_array(applications_path) if a["application_id"] in train_ids]
    background = extract_features(profiles, applications)
    if not len(background) or len(background) != len(train_ids):
        raise ValueError("Training reference is incomplete; do not use test/production batch as SHAP background")
    if max_background <= 0:
        raise ValueError("max_background must be positive")
    return background.sample(n=min(max_background, len(background)), random_state=42).reset_index(drop=True)


def compute_shap(model: Any, model_name: str, frame: pd.DataFrame,
                 background: pd.DataFrame | None = None) -> tuple[float, np.ndarray, np.ndarray]:
    """Return (base logit, per-feature SHAP logits, exact model raw logits)."""
    import shap  # optional heavy dependency; only needed by explain.py

    X = frame.loc[:, FEATURES].copy()
    n = len(X)
    if model_name == "logistic":
        if background is None:
            raise ValueError("Logistic SHAP needs training-only background")
        pre = model.named_steps["preprocess"]
        clf = model.named_steps["classifier"]
        for c in CATEGORICAL:
            X[c] = X[c].astype(str)
        bg = background.loc[:, FEATURES].copy()
        for c in CATEGORICAL:
            bg[c] = bg[c].astype(str)
        transformed = np.asarray(pre.transform(X), dtype=float)
        bg_transformed = np.asarray(pre.transform(bg), dtype=float)
        explainer = shap.LinearExplainer(clf, bg_transformed)
        phi = _binary_shap_values(explainer.shap_values(transformed), n, transformed.shape[1])
        baseline = _base_value(explainer.expected_value)
        # Pipeline transforms numeric columns first, then one-hot categorical columns.
        ohe = pre.named_transformers_["categorical"]
        mapped: dict[str, np.ndarray] = {}
        for j, name in enumerate(NUMERICAL):
            mapped[name] = phi[:, j]
        offset = len(NUMERICAL)
        for name, cats in zip(CATEGORICAL, ohe.categories_):
            length = len(cats)
            mapped[name] = phi[:, offset: offset + length].sum(axis=1)
            offset += length
        if offset != phi.shape[1]:
            raise ValueError("Unexpected one-hot feature layout in Logistic Regression")
        values = np.column_stack([mapped[name] for name in FEATURES])
        logits = np.asarray(model.decision_function(X), dtype=float).reshape(-1)
    elif model_name in {"catboost", "lightgbm"}:
        for c in CATEGORICAL:
            X[c] = X[c].astype(str if model_name == "catboost" else "category")
        explainer = shap.TreeExplainer(model, model_output="raw")
        values = _binary_shap_values(explainer.shap_values(X), n, len(FEATURES))
        baseline = _base_value(explainer.expected_value)
        if model_name == "catboost":
            logits = np.asarray(model.predict(X, prediction_type="RawFormulaVal"), dtype=float).reshape(-1)
        else:
            logits = np.asarray(model.predict(X, raw_score=True), dtype=float).reshape(-1)
    else:
        raise ValueError(f"Unsupported model {model_name}")
    errors = baseline + values.sum(axis=1) - logits
    if not np.isfinite(logits).all() or np.max(np.abs(errors)) > 1e-4:
        raise ValueError("SHAP attributions do not reconstruct the saved model raw output")
    return baseline, values, logits


def summarize_factors(values: np.ndarray, *, top_n: int = 4) -> tuple[list[dict], list[dict]]:
    """Explain direction as model association, never causation or denial reason."""
    if top_n <= 0 or top_n > len(FEATURES):
        raise ValueError("top_n must be in 1..28")
    factors = []
    for key, value in zip(FEATURES, values):
        if abs(value) < 1e-8:
            continue
        direction = "increases_model_risk" if value > 0 else "decreases_model_risk"
        label = FEATURE_LABELS[key]
        factors.append({
            "feature": key, "name_ru": label,
            "direction": direction,
            "impact_log_odds": round(float(value), 6),
            "customer_text": (
                f"Признак «{label}» повысил модельную оценку риска относительно базового прогноза."
                if value > 0 else
                f"Признак «{label}» снизил модельную оценку риска относительно базового прогноза."
            ),
        })
    increasing = sorted((f for f in factors if f["impact_log_odds"] > 0),
                        key=lambda f: -f["impact_log_odds"])[:top_n]
    reducing = sorted((f for f in factors if f["impact_log_odds"] < 0),
                      key=lambda f: f["impact_log_odds"])[:top_n]
    return increasing, reducing


def policy_explanation(assessment: dict[str, Any]) -> dict[str, Any]:
    """Bank policy/underwriting logic is independent of SHAP risk factors."""
    route = assessment.get("route")
    if route not in {"auto_decline", "analyst_escalation", "green_zone"}:
        raise ValueError("Unknown credit assessment route")
    stop = [c["code"] for c in assessment.get("stop_factor_checks", []) if c.get("triggered")]
    escalations = [c["code"] for c in assessment.get("escalation_checks", []) if c.get("triggered")]
    not_green = [c["code"] for c in assessment.get("green_zone_checks", []) if c.get("passed") is False]
    if route == "auto_decline":
        explanations = list(dict.fromkeys(stop))
    elif route == "analyst_escalation":
        explanations = list(dict.fromkeys(escalations + not_green))
    else:
        explanations = []
    messages = {
        "auto_decline": "Заявка не прошла автоматические проверки кредитной политики.",
        "analyst_escalation": "Заявка направлена специалисту для дополнительной оценки.",
        "green_zone": "Заявка прошла первичные проверки; окончательное решение ещё не принято.",
    }
    return {
        "route": route,
        "assessment_id": assessment.get("assessment_id"),
        "reason_codes": explanations,
        "reason_texts_ru": [POLICY_LABELS.get(code, "Требуется дополнительная проверка") for code in explanations],
        "customer_message": messages[route],
        "note": "Причины маршрута из правил банка, НЕ SHAP-атрибуции модели.",
    }


def explain_applications(profiles: list[dict], applications: list[dict], *, run_dir: Path,
                         model_name: str = "catboost", calibration: str = "platt",
                         assessments: list[dict] | None = None,
                         contract_path: Path | None = None,
                         background_profiles_path: Path | None = None,
                         background_applications_path: Path | None = None,
                         top_n: int = 4, limit: int = 50) -> list[dict]:
    if model_name not in MODELS or calibration not in CALIBRATIONS:
        raise ValueError("Unsupported model or calibration method")
    if limit <= 0:
        raise ValueError("limit must be positive")
    # Predictions and explainers MUST use the same pre-decision rows.
    selected_apps = applications[:limit]
    if not selected_apps:
        raise ValueError("No applications to explain")
    contract_path = contract_path or Path(__file__).resolve().parent / "feature_contract.json"
    contract = load_contract(contract_path)
    scoring_dir = resolve_scoring_dir(Path(run_dir))
    rows = extract_features(profiles, selected_apps).reset_index(drop=True)
    predictions = predict_applications(profiles, selected_apps, run_dir=scoring_dir,
                                        model_name=model_name, calibration=calibration,
                                        contract_path=contract_path)
    model = load_model(scoring_dir, model_name)
    background = (_load_background(scoring_dir, profiles_path=background_profiles_path,
                                    applications_path=background_applications_path)
                  if model_name == "logistic" else None)
    base, shap_values, logits = compute_shap(model, model_name, rows, background)
    # A calibrated Platt slope <=0 would invert SHAP "increases risk" direction.
    if calibration == "platt":
        from predict import load_calibrator
        platt = load_calibrator(scoring_dir, model_name, "platt")
        if float(np.asarray(platt.coef_).reshape(-1)[0]) <= 0:
            raise ValueError("Platt calibration reverses score direction; explanations are unsafe")
    by_application = {}
    if assessments is not None:
        for item in assessments:
            aid = item["application_id"]
            if aid in by_application:
                raise ValueError("Duplicate application_id in assessments")
            by_application[aid] = item
    output = []
    for i, pred in enumerate(predictions):
        positive, negative = summarize_factors(shap_values[i], top_n=top_n)
        app_id = pred["application_id"]
        actual_policy = by_application.get(app_id)
        output.append({
            **pred,
            "explanation_method": ("Linear SHAP" if model_name == "logistic" else "Tree SHAP"),
            "attribution_space": "UNCALIBRATED_LOG_ODDS",
            "baseline_log_odds": round(float(base), 8),
            "model_raw_log_odds": round(float(logits[i]), 8),
            "shap_sum_log_odds": round(float(shap_values[i].sum()), 8),
            "max_additivity_error": round(abs(float(base + shap_values[i].sum() - logits[i])), 10),
            "risk_increasing_factors": positive,
            "risk_reducing_factors": negative,
            "credit_policy": policy_explanation(actual_policy) if actual_policy else None,
            "customer_notice": (
                "Факторы показывают вклад признаков в расчёт модели, не причины решения банка. "
                "Они не являются причинными объяснениями. Калибровка вероятности не разложена на SHAP-вклады. "
                + ("Использованы синтетические исходы, а не фактические невозвраты кредитов."
                   if pred["label_source"] == "SIMULATED_DEMO_DEFAULTS" else
                   "Даже при наличии наблюдаемых исходов необходима независимая валидация модели.")
            ),
        })
    return output


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explain synthetic SME scoring with SHAP and optional policy reason codes")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--applications", type=Path, required=True)
    parser.add_argument("--assessments", type=Path, default=None,
                        help="Optional assessments_generated.json for ACTUAL policy reasons")
    parser.add_argument("--model", choices=MODELS, default="catboost")
    parser.add_argument("--calibration", choices=CALIBRATIONS, default="platt")
    parser.add_argument("--background-profiles", type=Path,
                        help="Only needed for logistic outside experiment/dataset")
    parser.add_argument("--background-applications", type=Path,
                        help="Only needed for logistic outside experiment/dataset")
    parser.add_argument("--top-n", type=int, default=4)
    parser.add_argument("--limit", type=int, default=20,
                        help="Number of applications to explain; default 20")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    forbidden = [args.profiles.resolve(), args.applications.resolve()]
    if args.assessments is not None:
        forbidden.append(args.assessments.resolve())
    if out in forbidden:
        parser.error("Output cannot overwrite an input")
    if out.exists() and not args.overwrite:
        parser.error("Output file exists; choose a new filename or --overwrite")
    explanations = explain_applications(
        _read_array(args.profiles), _read_array(args.applications),
        run_dir=args.run_dir, model_name=args.model, calibration=args.calibration,
        assessments=_read_array(args.assessments) if args.assessments else None,
        background_profiles_path=args.background_profiles,
        background_applications_path=args.background_applications,
        top_n=args.top_n, limit=args.limit,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(explanations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Explained {len(explanations)} applications to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
