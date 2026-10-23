# Synthetic SME lending pipeline — v0.7

## Folder layout

```text
ml/synthetic_data/
    company.py           # Borrower Profile + financials
    financials.py        # Financial generator used by company.py
    bki.py               # Add synthetic credit history
    fns.py               # Add synthetic registry/tax status
    compliance.py        # Add internal-screening and 115-FZ mock signals
    applications.py      # Stage-4 Loan Applications
    assessment.py        # Rule-based Credit Assessments + app status updates
    validation.py        # Cross-record consistency checks
    sanity_check.py      # Descriptive risk statistics
    stats_report.py      # Optional descriptive CSV/Markdown/plots
    main.py              # One command to run the full chain
    tests/
        test_assessment.py
        test_main.py
        ... existing unit tests and fixtures/
    data/                 # Generated outputs, do NOT commit
```

## Dependencies and execution (Windows PowerShell)

Run from the **repository root**, where `backend/pyproject.toml` exists:

```powershell
uv sync --project backend
uv run --project backend --group ml python ml/synthetic_data/main.py `
  --count 1200 --seed 42 --scenario baseline `
  --out-dir ml/synthetic_data/data/run_baseline_42
```

The existing backend environment must have NumPy. If necessary and approved by
the team, inside `backend/` run `uv add numpy` and commit `pyproject.toml` and
`uv.lock` changes, but **do not commit `.venv`**.

### Generate alternative independent datasets

```powershell
uv run --project backend --group ml python ml/synthetic_data/main.py `
  --count 1200 --seed 42 --scenario stress_2025 `
  --out-dir ml/synthetic_data/data/run_stress_42

uv run --project backend --group ml python ml/synthetic_data/main.py `
  --count 1200 --seed 42 --scenario demo --mix demo `
  --out-dir ml/synthetic_data/data/run_demo_42
```

`--seed` fixes stochastic draws; **unchanged code and parameters** produce the
same JSON. The data are generated anew on each run. Existing output files are
protected by default; use a new folder, or explicitly append `--overwrite`.


### Files created

```text
run_baseline_42/
    profiles_companies.json
    profiles_bki.json
    profiles_fns.json
    profiles_compliance.json       # final Borrower Profiles
    applications_generated.json    # original stage-4 applications
    assessments_generated.json     # calculated Credit Assessments
    applications_assessed.json     # applications referencing assessments
    quality_report.json            # consistency checks
    sanity_report.json             # descriptive statistics
    run_metadata.json              # seeds, scenarios, route counts, caveats
```

For the backend integration, import these **three** files together:
`profiles_compliance.json`, `applications_assessed.json`,
`assessments_generated.json`. Their IDs cross-reference each other.

### Run a single stage

```powershell
uv run --project backend --group ml python ml/synthetic_data/assessment.py `
  --profiles ml/synthetic_data/data/run_baseline_42/profiles_compliance.json `
  --applications ml/synthetic_data/data/run_baseline_42/applications_generated.json `
  --out ml/synthetic_data/data/assessments_single.json `
  --applications-out ml/synthetic_data/data/applications_assessed_single.json
```


### Validate, test, and create statistical plots

```powershell
uv run --project backend --group ml python ml/synthetic_data/validation.py `
  --profiles ml/synthetic_data/data/run_baseline_42/profiles_compliance.json `
  --applications ml/synthetic_data/data/run_baseline_42/applications_assessed.json `
  --assessments ml/synthetic_data/data/run_baseline_42/assessments_generated.json `
  --report ml/synthetic_data/data/run_baseline_42/quality_rechecked.json

uv run --project backend --group ml python -m unittest discover `
  -s ml/synthetic_data/tests -t ml/synthetic_data -p "test_*.py" -v

uv run --project backend --group ml --with matplotlib python ml/synthetic_data/main.py `
  --count 1200 --seed 43 --scenario baseline --stats `
  --out-dir ml/synthetic_data/data/run_baseline_43
```

The `--stats` switch additionally saves `stats_report/{report.md, report.json,
features.csv, plots/*.png}`. `matplotlib` is optional; `--with matplotlib`
installs it for that run only, without changing the uv lockfile.
