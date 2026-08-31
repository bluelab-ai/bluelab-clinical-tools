# Data and security boundary

- The public repository includes only code, documentation, parameter contracts,
  and aggregate effect summaries.
- `data/phase2_mrs01_web_dataset.csv` is a patient-level analysis table and is
  intentionally excluded even when identifiers are pseudonymized.
- The website does not display or export patient-level rows; downloads contain
  scenario-level or aggregate results only.
- Feedback records and attachments are runtime data and must remain outside Git.
- Users must not submit identifiable patient information through feedback.
- Production deployments should use authenticated HTTPS access, protected
  environment files, least-privilege filesystem permissions, and backups.
- The built-in shared login is a controlled trial mechanism, not enterprise SSO
  or MFA.
