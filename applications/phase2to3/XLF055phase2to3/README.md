# XLF055 Phase II-to-III recurrence-scenario explorer

This package contains the Streamlit frontend, registered scenario-engine code,
tests, documentation, and public-safe parameter contracts for the XLF055
exploratory planning tool. It is intended for scenario exploration and
directional hypothesis generation, not individual clinical prediction or a
guarantee of Phase III success.

## Repository contents

- `app/app.py`: Streamlit application.
- `app/planning_tool/`: frontend adapters, reporting, and feedback handling.
- `backend/`: registered recurrence-scenario engine.
- `outputs/model_registry/`: public-safe model interface contracts.
- `scripts/run_streamlit_v26.py`: validated local entry point.
- `tests/`: engine and frontend regression tests.
- `docs/user_manual/`: user manual in Markdown and PDF.

## Private runtime assets

The application deliberately cannot fully start from this public repository
alone. An approved administrator must place these separately supplied files at
their exact relative paths:

- `outputs/analysis_datasets/phase2_subject_master.parquet`
- `outputs/analysis_datasets/phase2_recurrence_analysis.parquet`
- `outputs/model_development/v2_1_bayesian_model_fit/restricted/candidate_model_payload.json`
- `outputs/model_development/v2_1_bayesian_model_fit/restricted/primary_posterior_draws.npz`
- `outputs/model_development/v2_1_bayesian_model_fit/directional_evidence.csv`
- `outputs/model_development/v2_1_bayesian_model_fit/cv_summary.csv`
- `outputs/model_development/v2_2_backend_extension/support_reference_v2_2.json`

Patient-level data, fitted private payloads, credentials, feedback records,
uploads, and server-specific files must never be committed.

## Run

After private assets are installed, create an isolated Python 3.12 environment,
install `requirements.txt`, copy `config/production.env.example` to a protected
runtime environment file outside the repository, and run:

```bash
python scripts/run_streamlit_v26.py
```

See `docs/DEPLOYMENT.md` for the deployment checklist.
