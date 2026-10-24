"""Educational SME credit-risk comparison (logistic / CatBoost / LightGBM).

Target is *not* included in the synthetic Borrower/Application contract.
Use --simulate-outcomes for DEMO-ONLY counterfactual 12-month default labels,
or --labels with genuinely observed post-origination default_12m outcomes.
The model never reads Credit Assessments, routing decisions or AI risk scores.
No trained model here estimates real-world probability of default (PD).
"""
from __future__ import annotations

import argparse
import csv
from datetime import date
from hashlib import blake2b
import json
from math import exp, isfinite, log1p
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.model_selection import StratifiedGroupKFold

CATEGORICAL = (
    "legal_form", "okved_section", "credit_history_quality", "loan_purpose",
    "collateral_type", "repayment_type",
)
NUMERICAL = (
    "age_months", "employees_count", "log_annual_turnover", "ebitda_margin_pct",
    "revenue_change_pct", "negative_cf_months", "negative_cf_streak",
    "cf_net_to_turnover", "active_loans_count", "debt_to_turnover",
    "debt_service_to_turnover", "overdue_to_turnover", "max_overdue_days_12m",
    "tax_arrears_to_turnover", "has_tax_activity", "loan_to_turnover",
    "loan_amount_log", "term_months", "indicative_rate_pct", "has_collateral",
    "collateral_coverage", "requested_payment_to_turnover",
)
FEATURES = list(CATEGORICAL + NUMERICAL)
LABEL = "default_12m"


def _read_array(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(d, dict) for d in data):
        raise ValueError(f"Expected a JSON array of objects: {path}")
    return data


def _streak(flows: list[int | float]) -> int:
    run = longest = 0
    for value in flows:
        run = (run + 1) if value < 0 else 0
        longest = max(longest, run)
    return longest


def _annuity(amount: float, months: int, rate_pct: float) -> float:
    if months <= 0 or amount <= 0 or not 0 <= rate_pct < 100:
        raise ValueError("Invalid proposed loan amount, term or interest rate")
    r = rate_pct / 1200
    return amount / months if r == 0 else amount * r / (1 - (1 + r) ** (-months))


def extract_features(profiles: list[dict], applications: list[dict]) -> pd.DataFrame:
    """STRICT allowlist of information known at application submission.

    Deliberately excludes post-decision route, assessment, risk_score, offer, etc.
    Identifiers remain as metadata only and are NEVER model features.
    """
    by_id = {p["borrower_id"]: p for p in profiles}
    if len(by_id) != len(profiles):
        raise ValueError("Duplicate borrower_id in Borrower Profiles")
    if len({a["application_id"] for a in applications}) != len(applications):
        raise ValueError("Duplicate application_id")
    records = []
    for app in applications:
        p = by_id.get(app["borrower_id"])
        if p is None:
            raise ValueError(f"Unknown borrower for {app['application_id']}")
        # Do not accidentally use fields that become available only after decision.
        if app["status"] != "application_submitted" or app.get("current_assessment_id") is not None:
            raise ValueError("Pass applications_generated.json, NOT applications_assessed.json")
        asof = date.fromisoformat(p["financials"]["as_of_date"])
        application_date = date.fromisoformat(app["created_at"][:10])
        registered = date.fromisoformat(p["company"]["registration_date"])
        if asof > application_date or registered > application_date:
            raise ValueError("Financial snapshot or business registration postdates application")
        f, b, t, company = (p[x] for x in ("financials", "bki_data", "fns_data", "company"))
        request, collateral = app["loan_request"], app["collateral"]
        turnover, ebitda = float(f["annual_turnover"]), float(f["ebitda"])
        if turnover <= 0 or not isfinite(turnover) or not isfinite(ebitda):
            raise ValueError("Need positive finite annual_turnover and finite EBITDA")
        flows = f["cash_flow_last_12m"]
        if not isinstance(flows, list) or len(flows) != 12 or any(not isfinite(float(v)) for v in flows):
            raise ValueError("Expected 12 numeric cash-flow observations")
        amount, months = float(request["amount"]), int(request["term_months"])
        rate = float(app["pre_approval"]["indicative_rate_pct"])
        if request["repayment_type"] not in {"annuity", "differentiated"}:
            raise ValueError("Unsupported repayment type")
        if request["repayment_type"] == "annuity":
            monthly_payment = _annuity(amount, months, rate)
        else:
            monthly_payment = amount / months + amount * rate / 1200
        market_value = collateral.get("market_value")
        records.append({
            "application_id": app["application_id"],
            "borrower_id": p["borrower_id"],
            "legal_form": str(company["legal_form"]),
            "okved_section": str(company["okved_main"]["code"]).split(".")[0][:2],
            "credit_history_quality": str(b["credit_history_quality"]),
            "loan_purpose": str(app["purpose"]["category"]),
            "collateral_type": str(collateral["type"]),
            "repayment_type": str(request["repayment_type"]),
            "age_months": max(0, (application_date.year - registered.year) * 12 + application_date.month - registered.month - (application_date.day < registered.day)),
            "employees_count": int(company["employees_count"]),
            "log_annual_turnover": log1p(turnover),
            "ebitda_margin_pct": 100 * ebitda / turnover,
            "revenue_change_pct": float(f["revenue_change_pct"]),
            "negative_cf_months": sum(v < 0 for v in flows),
            "negative_cf_streak": _streak(flows),
            "cf_net_to_turnover": sum(flows) / turnover,
            "active_loans_count": int(b["active_loans_count"]),
            "debt_to_turnover": float(b["total_debt_amount"]) / turnover,
            "debt_service_to_turnover": 12 * float(b["monthly_debt_service"]) / turnover,
            "overdue_to_turnover": float(b["overdue_amount"]) / turnover,
            "max_overdue_days_12m": int(b["max_overdue_days_12m"]),
            "tax_arrears_to_turnover": float(t["tax_arrears_amount"]) / turnover,
            "has_tax_activity": int(bool(t["has_tax_activity"])),
            "loan_to_turnover": amount / turnover,
            "loan_amount_log": log1p(amount),
            "term_months": months,
            "indicative_rate_pct": rate,
            "has_collateral": int(market_value is not None),
            "collateral_coverage": float(market_value or 0) / amount,
            "requested_payment_to_turnover": 12 * monthly_payment / turnover,
        })
    if not records:
        raise ValueError("No applications to train on")
    frame = pd.DataFrame.from_records(records)
    if frame[FEATURES].isnull().any().any():
        raise ValueError("Missing feature values")
    for col in NUMERICAL:
        if not np.isfinite(frame[col].to_numpy(dtype=float)).all():
            raise ValueError(f"Non-finite numeric feature: {col}")
    return frame


def _stable_rng(seed: int, key: str) -> np.random.Generator:
    digest = blake2b(f"{seed}|{key}".encode("utf-8"), digest_size=8).digest()
    return np.random.default_rng(int.from_bytes(digest, "big"))


def simulate_demo_labels(frame: pd.DataFrame, *, seed: int = 42) -> pd.DataFrame:
    """Hypothetical default_12m if ALL requested loans were issued.

    Fictional stochastic outcome process, NOT measured credit defaults, with
    borrower-correlated unobserved frailty and id-keyed reproducible shocks.
    DO NOT use these labels to assert production PD or AUC.
    """
    rows = []
    for r in frame.itertuples(index=False):
        # A nonlinear demo data-generating process with genuine outcome noise.
        # Both its coefficients and its base rate are completely invented.
        margin = np.clip(r.ebitda_margin_pct / 100, -0.50, 0.50)
        growth = np.clip(r.revenue_change_pct, -60.0, 100.0)
        weak = int(r.credit_history_quality == "weak")
        nohist = int(r.credit_history_quality == "none")
        stress = (
            -2.65 - 3.0 * margin - 0.012 * growth + 0.95 * weak + 0.14 * nohist
            + 0.09 * r.negative_cf_months + 0.52 * min(r.debt_to_turnover, 2.0)
            + 0.80 * min(r.debt_service_to_turnover, 1.5)
            + 0.35 * (r.tax_arrears_to_turnover > 0)
            + 0.65 * (r.max_overdue_days_12m >= 30)
            + 0.20 * min(r.loan_to_turnover, 2.0)
        )
        frailty = _stable_rng(seed + 101, r.borrower_id).normal(0, 0.50)
        probability = float(np.clip(1.0 / (1.0 + exp(-float(np.clip(stress + frailty, -25, 25)))), 0.001, 0.95))
        outcome = int(_stable_rng(seed + 202, r.application_id).random() < probability)
        rows.append({"application_id": r.application_id, LABEL: outcome,
                     "simulator_probability": round(probability, 6)})
    return pd.DataFrame(rows)


def load_observed_labels(path: Path, application_ids: list[str]) -> pd.DataFrame:
    """Real labels must be externally supplied, 0/1 and fully matched by application_id."""
    if path.suffix.lower() == ".json":
        raw = _read_array(path)
        labels = pd.DataFrame(raw)
    elif path.suffix.lower() == ".csv":
        labels = pd.read_csv(path, dtype={"application_id": str})
    else:
        raise ValueError("Labels must be a CSV or JSON array")
    if not {"application_id", LABEL}.issubset(labels.columns):
        raise ValueError(f"Labels require application_id and {LABEL} columns")
    labels = labels[["application_id", LABEL]].copy()
    if labels["application_id"].isnull().any() or labels["application_id"].duplicated().any():
        raise ValueError("Labels have missing or duplicate application_id")
    if not labels[LABEL].isin([0, 1, "0", "1"]).all():
        raise ValueError("Expected binary default_12m in {0,1}; missing outcomes forbidden")
    labels[LABEL] = labels[LABEL].astype(int)
    if set(labels["application_id"]) != set(application_ids):
        raise ValueError("Label IDs must match applications exactly (no missing or extra rows)")
    return labels


def make_splits(frame: pd.DataFrame, y: np.ndarray, *, seed: int = 42) -> dict[str, np.ndarray]:
    """Five stratified borrower-disjoint folds: train 60%, val 20%, test 20%."""
    if len(frame) < 50 or min(int(y.sum()), int(len(y) - y.sum())) < 10:
        raise ValueError("Need >=50 applications and >=10 positive/negative labels; increase --count")
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed)
    folds = [test_idx for _, test_idx in splitter.split(frame[FEATURES], y, frame["borrower_id"])]
    splits = {"train": np.concatenate(folds[2:]), "val": folds[1], "test": folds[0]}
    for name, indices in splits.items():
        if len(np.unique(y[indices])) != 2:
            raise ValueError(f"{name} split has only one class; increase dataset size")
    groups = [set(frame.iloc[indices]["borrower_id"]) for indices in splits.values()]
    if groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2]:
        raise AssertionError("Borrower leaked across splits")
    return splits


def _auc_ci(y: np.ndarray, p: np.ndarray, seed: int, bootstraps: int = 400) -> list[float] | None:
    rng = np.random.default_rng(seed + 303)
    scores = []
    for _ in range(bootstraps):
        idx = rng.integers(0, len(y), len(y))
        if len(np.unique(y[idx])) == 2:
            scores.append(float(roc_auc_score(y[idx], p[idx])))
    return [round(float(v), 5) for v in np.percentile(scores, [2.5, 97.5])] if scores else None


def _metrics(y: np.ndarray, p: np.ndarray, seed: int, with_ci: bool) -> dict[str, Any]:
    auc = float(roc_auc_score(y, p))
    return {
        "n": len(y), "events": int(y.sum()), "event_rate": round(float(y.mean()), 5),
        "roc_auc": round(auc, 5), "gini": round(2 * auc - 1, 5),
        "pr_auc_average_precision": round(float(average_precision_score(y, p)), 5),
        "brier": round(float(brier_score_loss(y, p)), 5),
        "log_loss": round(float(log_loss(y, p, labels=[0, 1])), 5),
        "roc_auc_bootstrap_95ci": _auc_ci(y, p, seed) if with_ci else None,
    }


def train(
    frame: pd.DataFrame,
    *,
    seed: int = 42,
    model_name: str = "catboost",
    parts: dict[str, np.ndarray] | None = None,
) -> tuple[Any, dict, pd.DataFrame]:
    if LABEL not in frame.columns:
        raise ValueError("Missing target. Supply --labels or --simulate-outcomes")
    if frame[LABEL].isnull().any() or not frame[LABEL].isin([0, 1]).all():
        raise ValueError("Target must be complete and binary")
    y = frame[LABEL].to_numpy(dtype=int)
    if parts is None:
        parts = make_splits(frame, y, seed=seed)
    X = frame[FEATURES].copy()
    for col in CATEGORICAL:
        X[col] = X[col].astype(str)
    if model_name == "logistic":
        # Fit preprocessing ONLY on train; unseen validation/test categories are ignored.
        preprocessor = ColumnTransformer(
            transformers=[
                ("numeric", StandardScaler(), list(NUMERICAL)),
                ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False), list(CATEGORICAL)),
            ],
            remainder="drop",
        )
        model = Pipeline([
            ("preprocess", preprocessor),
            ("classifier", LogisticRegression(
                C=1.0, max_iter=3000, solver="lbfgs", random_state=seed,
            )),
        ])
        model.fit(X.iloc[parts["train"]], y[parts["train"]])
        # Aggregate absolute standardized coefficients for each source feature.
        coefs = np.abs(model.named_steps["classifier"].coef_[0])
        ohe = model.named_steps["preprocess"].named_transformers_["categorical"]
        categorical_sizes = [len(levels) for levels in ohe.categories_]
        weights = dict(zip(NUMERICAL, coefs[:len(NUMERICAL)]))
        start = len(NUMERICAL)
        for name, count in zip(CATEGORICAL, categorical_sizes):
            weights[name] = float(np.sum(coefs[start:start + count]))
            start += count
        importance = [weights[key] for key in FEATURES]
    elif model_name == "catboost":
        try:
            from catboost import CatBoostClassifier
        except ImportError as e:
            raise RuntimeError("Install CatBoost: uv run --project backend --with catboost --with pandas --with scikit-learn ...") from e
        model = CatBoostClassifier(
            iterations=500, depth=5, learning_rate=0.04, loss_function="Logloss",
            eval_metric="AUC", random_seed=seed, allow_writing_files=False,
            thread_count=2, verbose=False,
        )
        model.fit(
            X.iloc[parts["train"]], y[parts["train"]], cat_features=list(CATEGORICAL),
            eval_set=(X.iloc[parts["val"]], y[parts["val"]]),
            early_stopping_rounds=50, verbose=False,
        )
        importance = model.get_feature_importance()
    elif model_name == "lightgbm":
        try:
            import lightgbm as lgb
        except ImportError as e:
            raise RuntimeError("Install LightGBM: uv run --project backend --with lightgbm --with pandas --with scikit-learn ...") from e
        for col in CATEGORICAL:
            X[col] = X[col].astype("category")
        model = lgb.LGBMClassifier(
            n_estimators=500, learning_rate=0.035, num_leaves=15,
            min_child_samples=20, random_state=seed, n_jobs=2, verbosity=-1,
        )
        model.fit(X.iloc[parts["train"]], y[parts["train"]],
                  eval_set=[(X.iloc[parts["val"]], y[parts["val"]])],
                  eval_metric="auc", categorical_feature=list(CATEGORICAL),
                  callbacks=[lgb.early_stopping(50, verbose=False)])
        importance = model.feature_importances_
    else:
        raise ValueError("model must be logistic, catboost or lightgbm")

    stats = {name: _metrics(y[idx], model.predict_proba(X.iloc[idx])[:, 1], seed, name == "test")
             for name, idx in parts.items()}
    # Evaluating test once, *after* early stopping on validation.
    ti = parts["test"]
    probs = model.predict_proba(X.iloc[ti])[:, 1]
    predictions = frame.iloc[ti][["application_id", "borrower_id", LABEL]].copy()
    predictions["predicted_risk_score_demo"] = np.round(probs, 6)
    predictions["dataset_split"] = "test"
    ranked = sorted(zip(FEATURES, map(float, importance)), key=lambda x: x[1], reverse=True)
    report = {
        "model": model_name, "seed": seed,
        "training_target": LABEL,
        "higher_prediction_means": "higher hypothetical default risk",
        "feature_count": len(FEATURES), "features": FEATURES,
        "categorical_features": list(CATEGORICAL),
        "splits": stats,
        "feature_importance": [{"feature": feature, "importance": round(value, 5)} for feature, value in ranked],
        "feature_importance_note": (
            "Logistic: absolute standardized coefficients (categoricals aggregated over one-hot levels); "
            "CatBoost/LightGBM: library-specific importance. These scales are NOT comparable."
        ),
        "warning": "Synthetic outcomes are NOT real observed defaults; metrics cannot validate actual bank credit risk.",
    }
    return model, report, predictions


def compare_models(frame: pd.DataFrame, *, seed: int = 42, models: tuple[str, ...] = (
    "logistic", "catboost", "lightgbm"
)) -> tuple[dict[str, tuple[Any, dict, pd.DataFrame]], pd.DataFrame, dict[str, Any]]:
    """Compare models on EXACTLY the same precomputed borrower-disjoint splits.

    The test set is reported once and not used for model selection or tuning.
    """
    if LABEL not in frame or frame[LABEL].isna().any():
        raise ValueError("Missing binary target")
    parts = make_splits(frame, frame[LABEL].to_numpy(dtype=int), seed=seed)
    results = {}
    for name in models:
        results[name] = train(frame, seed=seed, model_name=name, parts=parts)
    rows = []
    for name, (_, report, _) in results.items():
        for split_name in ("train", "val", "test"):
            m = report["splits"][split_name]
            rows.append({"model": name, "split": split_name, **m})
    comparison = pd.DataFrame(rows)
    # Paired bootstrap on the SAME held-out test labels, without inventing
    # independent standard errors for correlated model predictions.
    paired_intervals = {}
    y_true = frame.iloc[parts["test"]][LABEL].to_numpy(dtype=int)
    borrower_ids = frame.iloc[parts["test"]]["borrower_id"].to_numpy()
    by_model = {}
    test_ids = frame.iloc[parts["test"]]["application_id"].astype(str).tolist()
    for name, (_, _, preds) in results.items():
        aligned = preds.set_index("application_id").loc[test_ids]
        by_model[name] = aligned["predicted_risk_score_demo"].to_numpy(dtype=float)
    rng = np.random.default_rng(seed + 909)
    # Cluster resampling if more than one application belongs to a borrower.
    groups = list(dict.fromkeys(borrower_ids))
    group_to_indices = {group: np.flatnonzero(borrower_ids == group) for group in groups}
    for name in models:
        if name == "logistic":
            continue
        differences = []
        for _ in range(400):
            chosen = rng.choice(groups, size=len(groups), replace=True)
            sampled = np.concatenate([group_to_indices[g] for g in chosen])
            if len(np.unique(y_true[sampled])) < 2:
                continue
            differences.append(float(
                roc_auc_score(y_true[sampled], by_model[name][sampled])
                - roc_auc_score(y_true[sampled], by_model["logistic"][sampled])
            ))
        paired_intervals[name] = {
            "auc_delta_vs_logistic": round(
                results[name][1]["splits"]["test"]["roc_auc"]
                - results["logistic"][1]["splits"]["test"]["roc_auc"], 5,
            ),
            "paired_cluster_bootstrap_delta_auc_95ci": (
                [round(float(v), 5) for v in np.percentile(differences, [2.5, 97.5])]
                if differences else None
            ),
        }
    meta = {
        "seed": seed,
        "same_splits_for_all_models": True,
        "n_test": int(len(parts["test"])),
        "n_test_events": int(y_true.sum()),
        "paired_test_auc_vs_logistic": paired_intervals,
        "caution": "Simulated outcome labels do not validate real-world probability of default.",
    }
    return results, comparison, meta


def cli() -> int:
    parser = argparse.ArgumentParser(description="Compare SME credit scoring models on common splits")
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--applications", type=Path, required=True,
                        help="Use applications_generated.json, NOT applications_assessed.json")
    label_source = parser.add_mutually_exclusive_group(required=True)
    label_source.add_argument("--simulate-outcomes", action="store_true",
                              help="Invent counterfactual 12-month defaults for a DEMO only")
    label_source.add_argument("--labels", type=Path,
                              help="Complete application_id,default_12m CSV or JSON")
    parser.add_argument("--model", choices=("logistic", "catboost", "lightgbm", "all"), default="all")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    # Prevent accidentally replacing an existing experiment directory.
    if args.out_dir.exists() and any(args.out_dir.iterdir()) and not args.overwrite:
        parser.error(f"Output directory is not empty: {args.out_dir}. Use --overwrite or a new directory")
    feature_table = extract_features(_read_array(args.profiles), _read_array(args.applications))
    labels = (simulate_demo_labels(feature_table, seed=args.seed + 1000) if args.simulate_outcomes
              else load_observed_labels(args.labels, feature_table["application_id"].tolist()))
    data = feature_table.merge(labels[["application_id", LABEL]], on="application_id",
                               how="left", validate="one_to_one")
    if data[LABEL].isna().any():
        raise ValueError("Missing labels after joining")
    names = ("logistic", "catboost", "lightgbm") if args.model == "all" else (args.model,)
    parts = make_splits(data, data[LABEL].to_numpy(dtype=int), seed=args.seed)
    if args.model == "all":
        results, table, comparison_meta = compare_models(data, seed=args.seed, models=names)
    else:
        results = {args.model: train(data, seed=args.seed, model_name=args.model, parts=parts)}
        table = pd.DataFrame([{
            "model": args.model, "split": split_name, **results[args.model][1]["splits"][split_name],
        } for split_name in ("train", "val", "test")])
        comparison_meta = {"same_splits_for_all_models": True, "models": list(names)}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest = data[["borrower_id", "application_id", LABEL]].copy()
    manifest["split"] = "unknown"
    for split_name, ix in parts.items():
        manifest.loc[ix, "split"] = split_name
    manifest.to_csv(args.out_dir / "split_manifest.csv", index=False)
    if args.simulate_outcomes:
        labels.to_csv(args.out_dir / "simulated_labels.csv", index=False)
    comparison_meta["label_source"] = ("SIMULATED_UNOBSERVED_DEFAULTS" if args.simulate_outcomes
                                        else "EXTERNAL_LABELS_USER_SUPPLIED")
    comparison_meta["test_set_not_used_for_tuning"] = True
    (args.out_dir / "comparison.json").write_text(
        json.dumps(comparison_meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    table.to_csv(args.out_dir / "comparison.csv", index=False)
    for name, (model, report, predictions) in results.items():
        target = args.out_dir / "models" / name if args.model == "all" else args.out_dir
        target.mkdir(parents=True, exist_ok=True)
        report["label_source"] = comparison_meta["label_source"]
        report["cohort"] = "All requested loans, including hypothetical rejected applications"
        (target / "metrics.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        predictions.to_csv(target / "test_predictions.csv", index=False)
        pd.DataFrame(report["feature_importance"]).to_csv(target / "feature_importance.csv", index=False)
        if name == "logistic":
            import joblib
            joblib.dump(model, target / "model.joblib")
        elif name == "catboost":
            model.save_model(str(target / "model.cbm"))
        else:
            model.booster_.save_model(str(target / "model.lgb.txt"))
        print(f"{name:10s}: ROC-AUC={report['splits']['test']['roc_auc']:.4f}, "
              f"Gini={report['splits']['test']['gini']:.4f}, "
              f"PR-AUC={report['splits']['test']['pr_auc_average_precision']:.4f}")
    print("NOT real-world credit scoring accuracy. Outcomes are simulated if --simulate-outcomes was used.")
    print(f"Outputs: {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
