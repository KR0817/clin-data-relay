# Project Agent Instructions

## Project

- Name: ClinData Relay
- Updated: 2026-08-22
- Stack: Python 3.12, FastAPI, SQLite, vanilla HTML/CSS/JavaScript, pytest, Node.js Artifact Tool, PowerShell, LibreClinica SOAP/ODM
- Package manager: Python virtual environment with `pip`; bundled Node runtime for spreadsheet generation

## Product boundary

- LibreClinica is the authority EDC. The companion may create candidates, reviews, immutable transfer packages, reconciliation records, dashboards and exports, but must never write LibreClinica database tables directly.
- Development and automated verification use synthetic data only. Real participant data, remote EDC endpoints, production Kimi, hospital LIS, SSO/MFA and external notifications remain blocked until institution, ethics, privacy, security and validation approval.
- Kimi may receive only a human-confirmed de-identified derivative plus bounded local OCR evidence and the active field dictionary. Model output never bypasses deterministic validation or human review.
- Preserve centre isolation, append-only audit provenance, immutable frozen packages, idempotency and fail-closed external integrations.

## Architecture and code style

- Prefer small functions and existing helpers. Do not add a framework or dependency when FastAPI, SQLite, standard Python, vanilla JavaScript or installed packages are sufficient.
- Validate untrusted input at API boundaries. Never expose credentials, raw provider errors or direct identifiers.
- Keep UI state local unless it must be shared or persisted. Maintain keyboard access, 44 px minimum targets, compact Chinese clinical UI and visible status/error states.
- Use English for code, identifiers, comments and technical documentation. Chinese UI copy is allowed because the product targets Chinese research teams.

## Required workflow

- For complex changes, update `PRD.md`, `Tech-Spec.md` and `docs/api-contract.md` before implementation.
- Use focused patches and preserve unrelated user changes.
- Add or update tests before/with behavior changes. Run focused tests, then the full suite.
- For UI changes, perform browser validation for desktop and mobile layout, overflow, console errors and the main workflow.
- Do not claim production or clinical validation from synthetic sandbox tests.

## Commands

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\scripts\start_companion_live.ps1
.\scripts\validate_libreclinica_sandbox.ps1 -Start -UseCachedImages
```

## Primary directories

- `app/`: FastAPI application, integrations and static workbench
- `config/`: versioned CRF, terminology and LibreClinica mappings
- `docs/`: contracts, validation boundaries, ADRs and research notes
- `scripts/`: launch, qualification and export helpers
- `tests/`: behavior and integration-boundary tests
- `.runtime/`: ignored local credentials and runtime outputs; never read or expose secret values
