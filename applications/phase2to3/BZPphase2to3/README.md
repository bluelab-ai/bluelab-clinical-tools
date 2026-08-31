# BZP Phase III Planning Explorer

This repository contains the application source and deployment templates for the BZP Phase III planning explorer. It is an exploratory planning tool and does not represent a Phase III success-probability claim.

## Contents

- `sponsor_demo_app.py`: Streamlit application entry point.
- `sponsor_demo/`: UI, reporting, feedback, changelog, and population-insight functions.
- `clinical_trial_sim_engine/`: simulation and enrichment engine source.
- `config/production.env.example`: safe environment-variable template.
- `deploy/`: Linux systemd service template.
- `docs/DEPLOYMENT.md`: deployment and acceptance instructions for IT.

## Important boundary

The repository intentionally excludes private runtime assets, feedback records, uploaded files, application credentials, SMTP credentials, and all server-specific configuration. IT must receive the separate private runtime asset package and configure secrets on the target server before starting the service.

## Deployment

Follow [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). The application may be published through the company-approved reverse proxy, gateway, container platform, or other standard infrastructure. Cloudflare is not required.
