"""Audit synthetic SME scoring experiment outputs; no fitting or model selection.

Example (from repository root):
  uv run --no-project --with pandas --with numpy --with matplotlib \
      --with scikit-learn python ml/scoring/audit_predictions.py \
      --run-dir ml/scoring/data/compare_42 \
      --profiles ml/synthetic_data/data/scoring_source_42/profiles_compliance.json \
      --applications ml/synthetic_data/data/scoring_source_42/applications_generated.json

Creates audit/summary.json, audit/calibration_bins.csv, audit/precision_recall_step.png,
audit/calibration_with_intervals.png and audit/prediction_distributions.png.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import (average_precision_score, brier_score_loss,
                             precision_recall_curve, roc_auc_score)

MODEL_NAMES = ('logistic', 'catboost', 'lightgbm')
SCORE = 'predicted_risk_score_demo'
LABEL = 'default_12m'
FORBIDDEN_INPUT_FIELDS = {'route', 'risk_score', 'assessment_id', 'model_confidence_pct',
                          'default_12m', 'simulator_probability'}


def wilson_interval(positive: int, count: int, z: float = 1.96) -> tuple[float, float]:
    if count < 1 or not 0 <= positive <= count:
        raise ValueError('Expected 0 <= positive <= count, count > 0')
    p = positive / count
    denom = 1 + z*z/count
    centre = (p + z*z/(2*count)) / denom
    radius = z * np.sqrt(p*(1-p)/count + z*z/(4*count*count)) / denom
    return float(max(0, centre-radius)), float(min(1, centre+radius))


def calibration_bins(y: np.ndarray, p: np.ndarray, model: str, n_bins: int = 5) -> pd.DataFrame:
    df = pd.DataFrame({'y': y, 'p': p})
    # Value ties are kept in the same bucket. Hence LightGBM bins need not be equal sized.
    df['bin'] = pd.qcut(df['p'], q=n_bins, duplicates='drop')
    grouped = df.groupby('bin', observed=True, sort=True).agg(
        n=('y', 'size'), events=('y', 'sum'), mean_prediction=('p', 'mean'))
    grouped = grouped.reset_index(drop=True)
    grouped.insert(0, 'model', model)
    grouped.insert(1, 'bucket', np.arange(1, len(grouped)+1))
    grouped['observed_frequency'] = grouped['events'] / grouped['n']
    bounds = [wilson_interval(int(row.events), int(row.n)) for row in grouped.itertuples()]
    grouped['wilson_low'] = [a for a, _ in bounds]
    grouped['wilson_high'] = [b for _, b in bounds]
    return grouped


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def check_temporal_inputs(profiles: Path, applications: Path) -> dict:
    profiles_data = json.loads(profiles.read_text(encoding='utf-8'))
    applications_data = json.loads(applications.read_text(encoding='utf-8'))
    by_id = {x['borrower_id']: x for x in profiles_data}
    if len(by_id) != len(profiles_data):
        raise ValueError('Duplicate borrower_id in input profiles')
    later = []
    bad_status = []
    for a in applications_data:
        p = by_id[a['borrower_id']]
        at = _dt(a['consents']['submit_confirmed_at'])
        for key, source in (
            ('bki_retrieved_at', p['bki_data']['retrieved_at']),
            ('fns_retrieved_at', p['fns_data']['retrieved_at']),
            ('compliance_checked_at', p['compliance']['checked_at']),
            ('profile_updated_at', p['updated_at']),
        ):
            if _dt(source) > at:
                later.append({'application_id': a['application_id'], 'source': key, 'source_time': source})
        if (a.get('status') != 'application_submitted' or
                a.get('current_assessment_id') is not None):
            bad_status.append(a['application_id'])
    return {'n_profiles': len(profiles_data), 'n_applications': len(applications_data),
            'future_snapshot_violations': later, 'assessed_application_violations': bad_status}


def audit(run_dir: Path, out_dir: Path, profiles: Path | None = None,
          applications: Path | None = None) -> dict:
    manifest = pd.read_csv(run_dir/'split_manifest.csv', dtype={'application_id': str, 'borrower_id': str})
    assert set(manifest['split']) == {'train', 'val', 'test'}
    assert manifest['application_id'].is_unique and manifest['borrower_id'].notna().all()
    borrower_sets = {part: set(df.borrower_id) for part, df in manifest.groupby('split')}
    assert all(borrower_sets[a].isdisjoint(borrower_sets[b])
               for a in borrower_sets for b in borrower_sets if a != b), 'Borrower leakage'
    heldout = manifest.loc[manifest['split'] == 'test'].set_index('application_id').sort_index()
    assert heldout['default_12m'].isin([0, 1]).all()
    y = heldout[LABEL].to_numpy(dtype=int)
    assert len(np.unique(y)) == 2
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    predictions = {}
    all_bins = []
    for name in MODEL_NAMES:
        p = pd.read_csv(run_dir/'models'/name/'test_predictions.csv', dtype={'application_id': str})
        assert p['application_id'].is_unique
        p = p.set_index('application_id').sort_index()
        assert p.index.equals(heldout.index), f'Test IDs mismatch: {name}'
        assert np.array_equal(p[LABEL].to_numpy(dtype=int), y), f'Target mismatch: {name}'
        assert p['borrower_id'].equals(heldout['borrower_id']), f'Borrower mismatch: {name}'
        scores = p[SCORE].to_numpy(dtype=float)
        assert np.isfinite(scores).all() and (scores >= 0).all() and (scores <= 1).all()
        preds_bins = calibration_bins(y, scores, name)
        all_bins.append(preds_bins)
        predictions[name] = scores
        results[name] = {
            'n': int(len(y)), 'positives': int(y.sum()),
            'observed_rate': float(y.mean()),
            'mean_prediction': float(scores.mean()),
            'bias_mean_minus_observed': float(scores.mean() - y.mean()),
            'unique_scores': int(np.unique(scores).size),
            'min_score': float(scores.min()), 'max_score': float(scores.max()),
            'roc_auc': float(roc_auc_score(y, scores)),
            'average_precision': float(average_precision_score(y, scores)),
            'brier': float(brier_score_loss(y, scores)),
        }
    bins = pd.concat(all_bins, ignore_index=True)
    bins.to_csv(out_dir/'calibration_bins.csv', index=False)

    plt.figure(figsize=(8.5, 5.5))
    for name, scores in predictions.items():
        precision, recall, _ = precision_recall_curve(y, scores)
        # Drop sklearn's artificial endpoint (recall=0, precision=1) for display only.
        plt.step(recall[:-1][::-1], precision[:-1][::-1], where='post',
                 label=f'{name} (AP={results[name]["average_precision"]:.3f})')
    plt.axhline(y.mean(), ls='--', color='gray', label=f'Prevalence {y.mean():.3f}')
    plt.xlabel('Recall'); plt.ylabel('Precision')
    plt.title('Step Precision–Recall (artificial endpoint hidden)')
    plt.ylim(0, 1.03);plt.grid(alpha=0.15);plt.legend()
    plt.tight_layout();plt.savefig(out_dir/'precision_recall_step.png', dpi=160);plt.close()

    plt.figure(figsize=(8.5, 5.5))
    for name in MODEL_NAMES:
        d = bins.loc[bins.model == name]
        pred = d['mean_prediction'].to_numpy()
        observed = d['observed_frequency'].to_numpy()
        lo = observed - d['wilson_low'].to_numpy()
        hi = d['wilson_high'].to_numpy() - observed
        plt.errorbar(pred, observed, yerr=np.vstack([lo, hi]), capsize=3, marker='o',
                     ls='-', label=name)
    lim = max(float(max(bins['mean_prediction']) * 1.25), .45)
    plt.plot([0, lim], [0, lim], '--', color='gray', label='Perfect calibration')
    plt.xlim(0, lim);plt.ylim(0, min(1., lim + .15))
    plt.xlabel('Mean predicted risk in bucket')
    plt.ylabel('Observed synthetic default frequency')
    plt.title('Reliability diagram with Wilson 95% intervals')
    plt.grid(alpha=.15);plt.legend();plt.tight_layout()
    plt.savefig(out_dir/'calibration_with_intervals.png', dpi=160);plt.close()

    plt.figure(figsize=(8.5, 5.5))
    for name, scores in predictions.items():
        plt.hist(scores, bins=30, alpha=.42, label=f'{name} ({len(np.unique(scores))} unique)')
    plt.xlabel('Predicted risk');plt.ylabel('Applications')
    plt.title('Prediction distribution / model discrimination')
    plt.grid(alpha=.15);plt.legend();plt.tight_layout()
    plt.savefig(out_dir/'prediction_distributions.png', dpi=160);plt.close()

    report = {'n_test': int(len(y)), 'n_default': int(y.sum()), 'class_rate': float(y.mean()),
              'borrower_group_overlap': 0, 'models': results, 'limitations': [
                  'The target is synthetic, not observed post-origination default.',
                  'Five bins of roughly 48 each have large binomial uncertainty.',
                  'This reports diagnostic performance; do not tune models on test.'
              ]}
    if profiles is not None or applications is not None:
        if profiles is None or applications is None:
            raise ValueError('Pass --profiles and --applications together')
        report['temporal_inputs'] = check_temporal_inputs(profiles, applications)
    (out_dir/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description='Audit held-out predictions and calibration')
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path)
    parser.add_argument('--profiles', type=Path)
    parser.add_argument('--applications', type=Path)
    args = parser.parse_args()
    target = args.out_dir or (args.run_dir/'audit')
    report = audit(args.run_dir, target, args.profiles, args.applications)
    print(json.dumps({'n_test': report['n_test'], 'models': report['models'],
                      'temporal_inputs': report.get('temporal_inputs')}, ensure_ascii=False, indent=2))
    print('Saved:', target)


if __name__ == '__main__':
    main()
