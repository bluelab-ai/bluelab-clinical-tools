# Phase II-to-III clinical-planning tools

This directory groups the Blue Ballon BlueLab exploratory Phase II-to-III
applications:

- `BZPphase2to3`: BZP Phase III planning explorer.
- `XLF055phase2to3`: XLF055 recurrence-scenario explorer.
- `TY601Aphase2to3`: TY601A (Tapgrel) multi-endpoint Phase III planning explorer.

## Public-repository boundary

Only application code, tests, documentation, aggregate parameter contracts,
and safe deployment templates are tracked. The following must be delivered and
configured separately on an approved runtime host:

- subject- or patient-level datasets;
- fitted model payloads and posterior draws that are not approved for public release;
- login and portal secrets;
- SMTP credentials and recipient configuration;
- feedback databases, uploads, logs, caches, and generated reports.

Each project README lists its exact private runtime files.
