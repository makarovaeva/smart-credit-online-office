"""Batch inference for saved SME scoring experiments (educational demo only).

Loads a trusted saved estimator and optional Platt/isotonic calibrator, derives
exactly the same 28 PRE-decision features as training, and emits probabilities.
It does NOT approve/decline a loan. No actual borrower default outcomes were
used when the training run had SIMULATED_DEMO_DEFAULTS labels.

Only load local experiment artifacts you created yourself: joblib uses pickle.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from calibrate_scoring import apply_calibrator
from train_scoring import CATEGORICAL, FEATURES, NUMERICAL, _read_array, extract_features

MODELS = ("logistic", "catboost", "lightgbm")
CALIBRATIONS = ("raw", "platt", "isotonic")


def load_contract(path: Path) -> dict[str, Any]:
    """Require the feature definitions to match the currently installed extractor."""
    contract = json.loads(path.read_text(encoding="utf-8"))
    if contract.get("features_order") != FEATURES:
        raise ValueError("Feature contract order does not match train_scoring.FEATURES")
    if contract.get("categorical_features") != list(CATEGORICAL):
        raise ValueError("Feature contract categorical columns have changed")
    if contract.get("numerical_features") != list(NUMERICAL):
        raise ValueError("Feature contract numerical columns have changed")
    fields = contract.get("features")
    if not isinstance(fields, list) or [f.get("name") for f in fields] != FEATURES:
        raise ValueError("Feature contract definitions do not match trainer")
    if any(field.get("nullable") is not False for field in fields):
        raise ValueError("Unsupported nullable feature in contract")
    if not isinstance(contract.get("contract_version"), str):
        raise ValueError("Missing feature contract version")
    return contract


def resolve_scoring_dir(run_dir: Path) -> Path:
    """Accept either experiment_43/ or experiment_43/scoring/."""
    root = run_dir.resolve()
    if (root / "models").is_dir():
        return root
    if (root / "scoring" / "models").is_dir():
        return root / "scoring"
    raise FileNotFoundError(
        f"Models not found in {root}. Expected models/ or scoring/models/"
    )


def load_model(scoring_dir: Path, model_name: str):
    if model_name not in MODELS:
        raise ValueError(f"Choose model from {MODELS}")
    folder = scoring_dir / "models" / model_name
    if model_name == "logistic":
        path = folder / "model.joblib"
        if not path.is_file():
            raise FileNotFoundError(path)
        model = joblib.load(path)  # ONLY locally created, trusted artifact
        names = list(model.feature_names_in_) if hasattr(model, "feature_names_in_") else None
    elif model_name == "catboost":
        from catboost import CatBoostClassifier
        path = folder / "model.cbm"
        if not path.is_file():
            raise FileNotFoundError(path)
        model = CatBoostClassifier()
        model.load_model(str(path))
        names = list(model.feature_names_)
    else:
        import lightgbm as lgb
        path = folder / "model.lgb.txt"
        if not path.is_file():
            raise FileNotFoundError(path)
        model = lgb.Booster(model_file=str(path))
        names = list(model.feature_name())
    if names != FEATURES:
        raise ValueError(
            f"Saved {model_name} model expects different feature names or order. "
            "Do not use it with this feature contract."
        )
    return model


def load_calibrator(scoring_dir: Path, model_name: str, method: str):
    if method not in CALIBRATIONS:
        raise ValueError(f"Choose calibration from {CALIBRATIONS}")
    if method == "raw":
        return None
    path = scoring_dir / "models" / model_name / f"{method}_calibrator.joblib"
    if not path.is_file():
        raise FileNotFoundError(path)
    return joblib.load(path)  # ONLY locally created, trusted artifact


def raw_probabilities(model: Any, name: str, features: pd.DataFrame) -> np.ndarray:
    X = features.loc[:, FEATURES].copy()
    if name == "lightgbm":
        # Serialized LightGBM Booster retains its training category lists and
        # realigns the incoming pandas Categorical columns accordingly.
        for col in CATEGORICAL:
            X[col] = X[col].astype("category")
        predictions = model.predict(X)
    else:
        for col in CATEGORICAL:
            X[col] = X[col].astype(str)
        predictions = model.predict_proba(X)[:, 1]
    result = np.asarray(predictions, dtype=float).reshape(-1)
    if len(result) != len(X) or not np.isfinite(result).all():
        raise ValueError("Invalid model predictions")
    if ((result < 0) | (result > 1)).any():
        raise ValueError("Predicted probabilities outside [0, 1]")
    return result


def predict_applications(
    profiles: list[dict[str, Any]],
    applications: list[dict[str, Any]],
    *,
    run_dir: Path,
    model_name: str = "catboost",
    calibration: str = "platt",
    contract_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Reusable function for a future backend adapter. No training or data writes."""
    if model_name not in MODELS or calibration not in CALIBRATIONS:
        raise ValueError("Unsupported model or calibration method")
    contract_file = (contract_path if contract_path is not None
                     else Path(__file__).resolve().parent / "feature_contract.json")
    contract = load_contract(contract_file)
    features = extract_features(profiles, applications)  # all pre-decision checks
    scoring_dir = resolve_scoring_dir(Path(run_dir))
    model = load_model(scoring_dir, model_name)
    base = raw_probabilities(model, model_name, features)
    calibrator = load_calibrator(scoring_dir, model_name, calibration)
    adjusted = base if calibrator is None else apply_calibrator(calibration, calibrator, base)
    if len(adjusted) != len(features) or not np.isfinite(adjusted).all():
        raise ValueError("Invalid calibrated predictions")
    report_file = scoring_dir / "calibration_comparison.json"
    if not report_file.is_file():
        raise FileNotFoundError(
            f"Missing label provenance: {report_file}. Refusing unlabelled artifact"
        )
    report = json.loads(report_file.read_text(encoding="utf-8"))
    label_source = report.get("label_source")
    if label_source not in ("SIMULATED_DEMO_DEFAULTS", "EXTERNAL_LABELS"):
        raise ValueError(f"Unknown training-label provenance: {label_source!r}")
    is_demo = label_source == "SIMULATED_DEMO_DEFAULTS"
    output: list[dict[str, Any]] = []
    for i, row in features.iterrows():
        output.append({
            "application_id": str(row["application_id"]),
            "borrower_id": str(row["borrower_id"]),
            "model": model_name,
            "calibration": calibration,
            "feature_contract_version": contract["contract_version"],
            "target": "default_12m",
            "label_source": label_source,
            "raw_probability": round(float(base[i]), 8),
            "calibrated_probability": round(float(adjusted[i]), 8),
            "decision": None,  # Decisions belong to bank policy, NEVER ML alone.
            "warning": (
                "DEMO: synthetic default labels; not validated probability of default"
                if is_demo else
                "External labels supplied: independent real-world validation still required"
            ),
        })
    return output


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Predict demo credit risk from saved trained artifacts")
    parser.add_argument("--profiles", type=Path, required=True,
                        help="Pre-decision Borrower Profile JSON array")
    parser.add_argument("--applications", type=Path, required=True,
                        help="Original applications_generated.json (not assessed)")
    parser.add_argument("--run-dir", type=Path, required=True,
                        help="Experiment root or its scoring/ directory")
    parser.add_argument("--model", choices=MODELS, default="catboost")
    parser.add_argument("--calibration", choices=CALIBRATIONS, default="platt")
    parser.add_argument("--out", type=Path, help="Output JSON; otherwise prints to stdout")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    if args.out is not None:
        out = args.out.resolve()
        if out in (args.profiles.resolve(), args.applications.resolve()):
            parser.error("Output must not overwrite input JSON")
        if out.exists() and not args.overwrite:
            parser.error(f"Output exists: {out}. Choose a new filename or --overwrite")
    predictions = predict_applications(
        _read_array(args.profiles), _read_array(args.applications),
        run_dir=args.run_dir, model_name=args.model,
        calibration=args.calibration,
    )
    serialized = json.dumps(predictions, ensure_ascii=False, indent=2) + "\n"
    if args.out is None:
        print(serialized, end="")
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(serialized, encoding="utf-8")
        print(f"Wrote {len(predictions)} predictions to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
