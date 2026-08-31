# Contributing

ClinData Relay welcomes bounded technical review and pull requests that improve
the synthetic research prototype without weakening its data, authorization or
human-review boundaries.

## Before opening a pull request

1. Use synthetic data only. Do not attach reports, identifiers, participant
   records, credentials, logs or private deployment information.
2. Keep LibreClinica as the Authority EDC and keep OCR/model output behind human
   review.
3. Add or update focused tests for behavior changes.
4. Run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\check_public_release.ps1
   uv run python -m compileall -q app
   node --check .\app\static\js\workbench.js
   uv run pytest -q
   ```

5. Explain the user impact, the safety boundary and what you verified.

By submitting a contribution, you agree to the contribution terms in
[LICENSE](LICENSE).

## Scope

Good contributions are small, reviewable fixes to accessibility, tests,
documentation, deterministic parsing, validation and clearly bounded
interfaces. Please discuss major architecture, identity, data-model, external
AI or Authority EDC changes before implementation.

Security reports belong in the private channel described in
[SECURITY.md](SECURITY.md), not in a public issue.
