# TY601A (Tapgrel) Phase II-to-III planning explorer

This package contains the Streamlit application, dynamic multi-endpoint engine,
tests, public-safe aggregate effect tables, parameter contract, and user manual
for the TY601A exploratory Phase III planning tool. Planning results are scenario
outputs, not predictions or guarantees of trial success.

## Supported planning endpoints

- D1-D90 CEC-adjudicated ischemic stroke.
- D90 full ordinal mRS (0-6).
- D90 mRS 0-1.
- D90 mRS 0-2.

The four options are alternative primary-endpoint planning scenarios. Selecting
one does not create a co-primary or secondary endpoint hierarchy.

## Repository contents

- `app.py`: Streamlit application entry point.
- `planning_tool/`: simulation, population, and comparison engine.
- `data/phase2_mrs01_*_effects.csv`: aggregate effect summaries.
- `data/phase3_dynamic_parameter_contract.json`: parameter contract.
- `feedback_mail.py`: optional durable SMTP outbox worker.
- `tests/`: engine and frontend smoke tests.
- `docs/user_manual/`: user manual in Markdown and PDF.

## Private runtime asset

The patient-level analysis table below is deliberately excluded from GitHub and
must be delivered separately through an approved private channel:

- `data/phase2_mrs01_web_dataset.csv`

The application requires that exact relative path for full operation. Login and
portal secrets, SMTP credentials and recipients, feedback records, uploads,
generated reports, logs, and backups are also excluded.

## Run

After the private dataset is installed, create an isolated Python 3.12
environment, install `requirements.txt`, load a protected environment file based
on `config/production.env.example`, and run:

```bash
streamlit run app.py --server.address 127.0.0.1 --server.port 8526
```

See `docs/DEPLOYMENT.md` for the deployment checklist.
