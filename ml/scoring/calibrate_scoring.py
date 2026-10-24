"""Leakage-safe probability calibration for the demo SME default simulator.

Train model / early-stop / fit calibrator / evaluate are four borrower-disjoint folds.
Uses train_scoring.py for its established feature contract and model trainers.
No observed credit outcomes are provided: simulated labels remain DEMO ONLY.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import joblib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score, average_precision_score
from sklearn.model_selection import StratifiedGroupKFold

from train_scoring import (
    CATEGORICAL, FEATURES, LABEL, _read_array, extract_features,
    load_observed_labels, simulate_demo_labels, train,
)

METHODS = ('raw', 'platt', 'isotonic')
MODELS = ('logistic', 'catboost', 'lightgbm')
EPS = 1e-7


def four_way_split(frame: pd.DataFrame, *, seed: int) -> dict[str, np.ndarray]:
    """Five folds -> train 40%, earlystop 20%, calibration 20%, test 20%.

    Every borrower in one partition only. All partitions contain both labels.
    """
    y = frame[LABEL].to_numpy(dtype=int)
    if len(frame) < 100 or min(int(y.sum()), int(len(y) - y.sum())) < 20:
        raise ValueError('Need >=100 rows and >=20 observations of both classes')
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed)
    folds = [np.asarray(holdout, dtype=int) for _, holdout in
             splitter.split(frame[FEATURES], y, frame['borrower_id'])]
    parts = {
        'train': np.concatenate(folds[3:]),
        'val': folds[1],
        'calibration': folds[2],
        'test': folds[0],
    }
    borrower_sets = []
    for name, idx in parts.items():
        if len(np.unique(y[idx])) < 2:
            raise ValueError(f'Split {name} contains only one class; use a larger dataset')
        borrower_sets.append(set(frame.iloc[idx]['borrower_id']))
    if any(borrower_sets[i] & borrower_sets[j] for i in range(4) for j in range(i+1, 4)):
        raise AssertionError('Borrower appears in multiple partitions')
    indices = np.concatenate(list(parts.values()))
    if len(indices) != len(frame) or len(np.unique(indices)) != len(frame):
        raise AssertionError('Partition indices do not cover the dataset exactly once')
    return parts


def platt_inputs(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    return np.log(p / (1 - p)).reshape(-1, 1)


def fit_calibrator(method: str, p: np.ndarray, y: np.ndarray) -> Any:
    if method == 'platt':
        # Learn P(Y=1 | logit(p)) = sigmoid(a*logit(p) + b).
        # Only calibration labels used; no test-based tuning.
        model = LogisticRegression(C=1e6, solver='lbfgs', max_iter=2000)
        model.fit(platt_inputs(p), y)
        return model
    if method == 'isotonic':
        model = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds='clip')
        model.fit(np.asarray(p, dtype=float), y)
        return model
    raise ValueError('Unknown calibration method')


def apply_calibrator(method: str, calibrator: Any, p: np.ndarray) -> np.ndarray:
    if method == 'platt':
        out = calibrator.predict_proba(platt_inputs(p))[:, 1]
    elif method == 'isotonic':
        out = calibrator.predict(np.asarray(p, dtype=float))
    else:
        raise ValueError('Unknown calibration method')
    return np.clip(np.asarray(out, dtype=float), EPS, 1-EPS)


def metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float | int]:
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    if len(np.unique(y)) != 2:
        raise ValueError('Both label classes required for ROC-AUC')
    return {
        'n': int(len(y)),
        'events': int(y.sum()),
        'event_rate': round(float(y.mean()), 6),
        'mean_prediction': round(float(p.mean()), 6),
        'roc_auc': round(float(roc_auc_score(y, p)), 6),
        'gini': round(float(2 * roc_auc_score(y, p) - 1), 6),
        'average_precision': round(float(average_precision_score(y, p)), 6),
        'brier': round(float(brier_score_loss(y, p)), 6),
        'log_loss': round(float(log_loss(y, p, labels=[0, 1])), 6),
    }


def _predict(model: Any, frame: pd.DataFrame, idx: np.ndarray, name: str) -> np.ndarray:
    X = frame.iloc[idx][FEATURES].copy()
    if name == 'lightgbm':
        for c in CATEGORICAL:
            # Use all known category levels, as the initial trainer does.
            X[c] = pd.Categorical(X[c], categories=frame[c].astype('category').cat.categories)
    else:
        for c in CATEGORICAL:
            X[c] = X[c].astype(str)
    return np.asarray(model.predict_proba(X)[:, 1], dtype=float)


def calibrate_experiment(frame: pd.DataFrame, *, seed: int = 43,
                         models: tuple[str, ...] = MODELS):
    parts = four_way_split(frame, seed=seed)
    y = frame[LABEL].to_numpy(dtype=int)
    outputs: dict[str, dict[str, Any]] = {}
    metrics_rows = []
    for name in models:
        # train() sees only train, val, test; calibration rows are NOT used.
        trained, base_report, _ = train(frame, seed=seed, model_name=name,
                                       parts={k: parts[k] for k in ('train', 'val', 'test')})
        p_cal = _predict(trained, frame, parts['calibration'], name)
        p_test = _predict(trained, frame, parts['test'], name)
        yc = y[parts['calibration']]
        yt = y[parts['test']]
        calibrators = {
            'platt': fit_calibrator('platt', p_cal, yc),
            'isotonic': fit_calibrator('isotonic', p_cal, yc),
        }
        all_probs = {'raw': p_test}
        for method, calibrator in calibrators.items():
            all_probs[method] = apply_calibrator(method, calibrator, p_test)
        for method, prediction in all_probs.items():
            metrics_rows.append({'model': name, 'calibration': method,
                                 **metrics(yt, prediction)})
        outputs[name] = {
            'model': trained,
            'base_report': base_report,
            'calibrators': calibrators,
            'calibration_predictions': p_cal,
            'test_predictions': all_probs,
        }
    summary = pd.DataFrame(metrics_rows)
    return outputs, summary, parts


def reliability_points(y: np.ndarray, p: np.ndarray, *, n_bins: int = 8):
    """Equal-frequency bins, preserving tied predictions (never split one score)."""
    frame = pd.DataFrame({'y': y, 'p': p})
    if frame['p'].nunique() <= 1:
        frame['bin'] = 0
    else:
        frame['bin'] = pd.qcut(frame['p'], q=min(n_bins, len(frame)),
                               labels=False, duplicates='drop').fillna(0).astype(int)
    grouped = frame.groupby('bin', observed=True).agg(
        n=('y', 'size'), events=('y', 'sum'),
        predicted=('p', 'mean'), observed=('y', 'mean'))
    return grouped.reset_index()


def wilson_interval(events: np.ndarray, total: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Approximate Wilson 95% interval for observed event proportions."""
    z = 1.959963984540054
    n = np.asarray(total, dtype=float)
    phat = np.asarray(events, dtype=float) / n
    denom = 1 + z*z / n
    center = (phat + z*z / (2*n)) / denom
    half = z*np.sqrt(phat*(1-phat)/n + z*z/(4*n*n)) / denom
    return np.maximum(0,center-half), np.minimum(1,center+half)


def brier_gain_bootstrap(y: np.ndarray, raw: np.ndarray, calibrated: np.ndarray,
                         borrower_ids: np.ndarray, *, seed: int, n_boot: int = 1500):
    """Paired borrower-cluster bootstrap CI for raw Brier minus calibrated Brier."""
    y = np.asarray(y, dtype=int)
    per_obs_gain = (np.asarray(raw)-y)**2 - (np.asarray(calibrated)-y)**2
    borrowers = np.asarray(borrower_ids, dtype=str)
    groups = list(dict.fromkeys(borrowers))
    idx_by_group = {g: np.flatnonzero(borrowers == g) for g in groups}
    rng = np.random.default_rng(seed)
    samples=[]
    for _ in range(n_boot):
        chosen = rng.choice(groups, size=len(groups), replace=True)
        ix = np.concatenate([idx_by_group[g] for g in chosen])
        samples.append(float(per_obs_gain[ix].mean()))
    return (float(per_obs_gain.mean()),
            [float(v) for v in np.percentile(samples,[2.5,97.5])])

def save_experiment(out_dir: Path, frame: pd.DataFrame, outputs: dict,
                    comparison: pd.DataFrame, parts: dict[str, np.ndarray], *, seed: int,
                    source: str):
    out_dir.mkdir(parents=True, exist_ok=True)
    # All bootstrap uncertainty is descriptive. No hyperparameters are chosen by test.
    comparison = comparison.copy()
    comparison['brier_gain_vs_raw'] = 0.0
    comparison['brier_gain_ci_low'] = np.nan
    comparison['brier_gain_ci_high'] = np.nan
    y_for_ci = frame.iloc[parts['test']][LABEL].to_numpy(dtype=int)
    groups_for_ci = frame.iloc[parts['test']]['borrower_id'].astype(str).to_numpy()
    for model_idx,(name,result) in enumerate(outputs.items()):
        for method_idx,method in enumerate(('platt','isotonic')):
            gain,(lo,hi)=brier_gain_bootstrap(
                y_for_ci, result['test_predictions']['raw'],
                result['test_predictions'][method], groups_for_ci,
                seed=seed + 1000*model_idx + 10*method_idx)
            mask=(comparison['model']==name) & (comparison['calibration']==method)
            comparison.loc[mask,'brier_gain_vs_raw'] = gain
            comparison.loc[mask,'brier_gain_ci_low'] = lo
            comparison.loc[mask,'brier_gain_ci_high'] = hi
    comparison.to_csv(out_dir/'calibration_comparison.csv',index=False)
    manifest = frame[['application_id','borrower_id',LABEL]].copy()
    manifest['split'] = ''
    for name, idx in parts.items():
        manifest.iloc[idx, manifest.columns.get_loc('split')] = name
    manifest.to_csv(out_dir/'split_manifest.csv',index=False)
    test = frame.iloc[parts['test']][['application_id','borrower_id',LABEL]].copy().reset_index(drop=True)
    for name, result in outputs.items():
        for method, preds in result['test_predictions'].items():
            test[f'{name}_{method}'] = preds
    test.to_csv(out_dir/'test_predictions_calibrated.csv',index=False)
    all_records=[]
    for name, result in outputs.items():
        # Trained base and calibration object are both required to reproduce probabilities.
        folder=out_dir/'models'/name
        folder.mkdir(parents=True,exist_ok=True)
        if name=='logistic':
            joblib.dump(result['model'], folder/'model.joblib')
        elif name=='catboost':
            result['model'].save_model(str(folder/'model.cbm'))
        else:
            result['model'].booster_.save_model(str(folder/'model.lgb.txt'))
        for method, calibrator in result['calibrators'].items():
            joblib.dump(calibrator, folder/f'{method}_calibrator.joblib')
        for method, preds in result['test_predictions'].items():
            for _, row in reliability_points(test[LABEL].to_numpy(),preds).iterrows():
                all_records.append({'model':name,'method':method,'bin':int(row['bin']),
                                    'n':int(row['n']),'events':int(row['events']),
                                    'predicted':float(row['predicted']),'observed':float(row['observed'])})
    pd.DataFrame(all_records).to_csv(out_dir/'reliability_bins.csv',index=False)
    y_test = test[LABEL].to_numpy(dtype=int)
    fig, axes = plt.subplots(1,len(outputs),figsize=(5*len(outputs),4.5),
                             sharex=True,sharey=True,squeeze=False)
    axes = axes[0]
    for ax,(name,result) in zip(axes, outputs.items()):
        ax.plot([0,1],[0,1],linestyle='--',color='gray',linewidth=1)
        for method,p in result['test_predictions'].items():
            grp = reliability_points(y_test,p,n_bins=8)
            lo,hi = wilson_interval(grp['events'].to_numpy(),grp['n'].to_numpy())
            ax.errorbar(grp['predicted'],grp['observed'],
                        yerr=[grp['observed'].to_numpy()-lo,
                              hi-grp['observed'].to_numpy()],
                        marker='o',capsize=2,linewidth=1,label=method)
        ax.set_title(name)
        ax.set_xlim(0,0.75); ax.set_ylim(0,0.75)
        ax.set_xlabel('Mean predicted default probability')
        ax.grid(alpha=0.25)
        ax.legend()
    axes[0].set_ylabel('Observed simulated default frequency')
    fig.suptitle('Reliability (test) — synthetic 12m labels; bins ≈ equal count')
    fig.tight_layout();fig.savefig(out_dir/'reliability.png',dpi=140);plt.close(fig)
    # Pre-declared evaluation; no selection based on the test set.
    report = {
        'seed':seed, 'label_source':source,
        'split_sizes':{k:len(v) for k,v in parts.items()},
        'split_events':{k:int(frame.iloc[v][LABEL].sum()) for k,v in parts.items()},
        'split_purpose':{'train':'fit base estimator','val':'early stopping',
                         'calibration':'fit platt and isotonic only',
                         'test':'evaluation only'},
        'results':json.loads(comparison.to_json(orient='records')),
        'caution':'DEMO ONLY: future defaults simulated; not real credit PD.',
        'protocol':'Preselected two calibrators for each model, no tuning/selection by test.',
    }
    (out_dir/'calibration_comparison.json').write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


def cli() -> int:
    ap=argparse.ArgumentParser(description='Leakage-safe demo PD calibration: raw / Platt / isotonic')
    ap.add_argument('--profiles',type=Path,required=True)
    ap.add_argument('--applications',type=Path,required=True)
    src=ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--simulate-outcomes',action='store_true')
    src.add_argument('--labels',type=Path)
    ap.add_argument('--seed',type=int,default=43)
    ap.add_argument('--model',choices=('all',)+MODELS,default='all')
    ap.add_argument('--out-dir',type=Path,required=True)
    ap.add_argument('--overwrite',action='store_true')
    args=ap.parse_args()
    if args.out_dir.exists() and any(args.out_dir.iterdir()) and not args.overwrite:
        ap.error('Output dir not empty, specify a new --out-dir or --overwrite')
    features=extract_features(_read_array(args.profiles),_read_array(args.applications))
    labels=simulate_demo_labels(features,seed=args.seed+1000) if args.simulate_outcomes else \
           load_observed_labels(args.labels,features['application_id'].tolist())
    frame=features.merge(labels[['application_id',LABEL]],how='left',on='application_id',validate='one_to_one')
    if frame[LABEL].isna().any():
        raise ValueError('Missing default labels')
    names=MODELS if args.model=='all' else (args.model,)
    results, comp, parts=calibrate_experiment(frame,seed=args.seed,models=names)
    report=save_experiment(args.out_dir,frame,results,comp,parts,seed=args.seed,
                           source='SIMULATED_DEMO_DEFAULTS' if args.simulate_outcomes else 'EXTERNAL_LABELS')
    print(comp[['model','calibration','roc_auc','brier','log_loss','mean_prediction']].to_string(index=False))
    print('Split sizes', report['split_sizes'])
    print('Results:',args.out_dir)
    print('NOT a real-world PD model or validated bank score.')
    return 0


if __name__=='__main__':
    raise SystemExit(cli())
