# TY601A deployment checklist

1. Use Python 3.12 in a repository-local virtual environment and install
   `requirements.txt`.
2. Deliver `data/phase2_mrs01_web_dataset.csv` through an approved private
   channel and verify its path and permissions.
3. Store login, portal, recipient, and optional SMTP settings outside the
   repository in a `0600` environment file based on
   `config/production.env.example`.
4. Run the tests and start Streamlit on `127.0.0.1:8526`. Expose it only through
   an approved authenticated gateway.
5. Keep `runtime/`, reports, backups, logs, and uploaded files outside Git.
6. Verify login, all four endpoint scenarios, population insights, scenario
   comparison and rename, downloads, feedback queueing, and `/_stcore/health`.

The example service file in `deploy/` contains placeholders and no secrets.
