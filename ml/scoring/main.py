"""One entry point for generation -> model training -> probability calibration.

Runs existing, separately-tested modules as subprocesses to avoid duplicating
training/feature logic. Use a NEW --out-dir for every experiment. The runner
is intentionally independent of backend or notebook/Jupyter installation.

Synthetic defaults are teaching labels, NOT real credit outcomes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC_SCRIPT = REPO_ROOT / 'ml' / 'synthetic_data' / 'main.py'
SCORING_SCRIPT = Path(__file__).resolve().parent / 'calibrate_scoring.py'


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def build_commands(args: argparse.Namespace) -> tuple[list[list[str]], Path, Path, Path]:
    out = args.out_dir.resolve()
    if args.generate:
        profiles = out / 'dataset' / 'profiles_compliance.json'
        applications = out / 'dataset' / 'applications_generated.json'
    else:
        profiles = args.profiles.resolve()
        applications = args.applications.resolve()
    score_dir = out / 'scoring'
    commands: list[list[str]] = []
    if args.generate:
        generate_cmd = [
            sys.executable, str(SYNTHETIC_SCRIPT), '--count', str(args.count),
            '--seed', str(args.seed), '--scenario', args.scenario,
            '--as-of', args.as_of, '--out-dir', str(out / 'dataset'),
        ]
        if args.overwrite:
            generate_cmd += ['--overwrite']
        commands.append(generate_cmd)
    scoring_cmd = [
        sys.executable, str(SCORING_SCRIPT), '--profiles', str(profiles),
        '--applications', str(applications), '--model', args.model,
        '--seed', str(args.seed), '--out-dir', str(score_dir),
    ]
    if args.simulate_outcomes:
        scoring_cmd += ['--simulate-outcomes']
    else:
        scoring_cmd += ['--labels', str(args.labels.resolve())]
    if args.overwrite:
        scoring_cmd += ['--overwrite']
    commands.append(scoring_cmd)
    return commands, profiles, applications, score_dir


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Synthetic SME data -> scoring -> calibrated probability report')
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument('--generate', action='store_true', help='generate dataset with ml/synthetic_data/main.py')
    source.add_argument('--profiles', type=Path, help='existing profiles_compliance.json')
    ap.add_argument('--applications', type=Path, help='existing applications_generated.json')
    labels = ap.add_mutually_exclusive_group(required=True)
    labels.add_argument('--simulate-outcomes', action='store_true', help='DEMO labels, not real defaults')
    labels.add_argument('--labels', type=Path, help='observed 12-month loan outcomes, CSV/JSON')
    ap.add_argument('--out-dir', required=True, type=Path)
    ap.add_argument('--count', type=int, default=3000, help='only with --generate')
    ap.add_argument('--seed', type=int, default=43)
    ap.add_argument('--scenario', choices=('baseline', 'stress_2025', 'demo'), default='baseline')
    ap.add_argument('--as-of', default='2026-09-30', help='as-of date for the synthetic generator')
    ap.add_argument('--model', choices=('all', 'logistic', 'catboost', 'lightgbm'), default='all')
    ap.add_argument('--overwrite', action='store_true', help='intentionally replace known outputs')
    ap.add_argument('--dry-run', action='store_true', help='show commands without writing anything')
    args = ap.parse_args(argv)
    if args.generate:
        if args.applications is not None:
            ap.error('--applications must not be set with --generate')
        if args.count < 100:
            ap.error('--count should be >= 100; recommend >= 3000 for calibration')
        if args.labels is not None:
            ap.error('Observed labels cannot be paired with newly invented companies. Use existing profiles/applications.')
    elif args.applications is None:
        ap.error('--applications is required with --profiles')
    if not args.generate:
        for file in (args.profiles, args.applications, args.labels):
            if file is not None and not file.is_file():
                ap.error(f'File not found: {file}')
    return args


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    commands, profiles, applications, score_dir = build_commands(args)
    out = args.out_dir.resolve()
    if not args.dry_run and out.exists() and any(out.iterdir()) and not args.overwrite:
        raise SystemExit(f'Output directory is not empty: {out}. Choose a new run or --overwrite.')
    for cmd in commands:
        print('Running:', ' '.join(f'"{p}"' if ' ' in p else p for p in cmd), flush=True)
        if not args.dry_run:
            subprocess.run(cmd, cwd=REPO_ROOT, check=True)
    if args.dry_run:
        return 0
    manifest = {
        'schema_version': 1,
        'label_source': 'SIMULATED_DEMO_DEFAULTS' if args.simulate_outcomes else 'EXTERNAL_LABELS',
        'seed': args.seed,
        'scenario': args.scenario if args.generate else 'provided_data',
        'model': args.model,
        'input_profiles': str(profiles),
        'input_applications': str(applications),
        'input_hashes_sha256': {
            'profiles': sha256_file(profiles),
            'applications': sha256_file(applications),
        },
        'scoring_results': str(score_dir),
        'note': 'Synthetic labels do not establish real-world PD or validated scoring.',
    }
    if args.labels:
        manifest['labels_sha256'] = sha256_file(args.labels.resolve())
    out.mkdir(parents=True, exist_ok=True)
    (out / 'run_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Experiment completed. Notebook results:', score_dir)
    return 0


if __name__ == '__main__':
    raise SystemExit(run())
