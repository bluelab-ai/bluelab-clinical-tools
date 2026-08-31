# XLF055 deployment checklist

1. Use Python 3.12 in a repository-local virtual environment and install
   `requirements.txt`.
2. Deliver the private runtime assets listed in the project README through an
   approved private channel. Confirm their paths and permissions.
3. Store login, portal, and optional SMTP settings outside the repository in a
   `0600` environment file based on `config/production.env.example`.
4. Run the test suite and start `scripts/run_streamlit_v26.py`. The service binds
   to `127.0.0.1:8520`; expose it only through an approved authenticated gateway.
5. Keep `app/runtime/feedback`, uploads, logs, and backups outside source control.
6. After deployment, verify login, scenario execution, population insights,
   comparison, downloads, feedback queueing, and `/_stcore/health`.

The example service file in `deploy/` contains placeholders and no secrets.
