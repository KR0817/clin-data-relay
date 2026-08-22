# Changelog

All notable changes are recorded here before a versioned release is created.
This file is not a substitute for a Git history or an approved project license.

## Unreleased

### Changed

- Defined `C:\ClinData Relay` as the canonical clean source root and prepared a
  private Git baseline that excludes runtime data, secrets and build outputs.
- Added the owner-approved proprietary root `LICENSE`; the repository remains
  private and source distribution requires separate written authorization.
- Adopted `ClinData Relay` as the user-facing product name while retaining
  compatibility-sensitive package, API and launcher filenames.
- Added a secret-free Windows CI quality gate for locked installation,
  compilation, workbench syntax and the full test suite.
- Updated first-party GitHub Actions to their current Node 24-based major
  releases after the initial remote run exposed the Node 20 deprecation.
- Established `app.version.__version__` as the package and runtime version source.
- Included the closed workbench HTML, CSS, JavaScript and approved WebP assets
  in Python package builds.
- Began the modular-monolith extraction for separate centre Lite and central
  web deployment shapes.
- Moved local credential and bearer-session persistence behind a framework-free
  authentication service while preserving the existing HTTP contract.
- Added a local schema migration ledger and exposed non-sensitive application
  and database schema versions through health diagnostics.
- Moved centre-local Kimi key validation, redacted status and settings routes
  behind a dedicated API module. Existing paths, role checks and audit behavior
  are unchanged; credential material remains local file state only.
- Added the first central PostgreSQL bootstrap slice with strict TLS policy,
  transaction-locked schema ledger, redacted preflight output and a real
  PostgreSQL 16 CI contract. It creates no clinical tables and does not enable
  central application startup.
- Added a shared encrypted-package import-ledger contract with SQLite and
  PostgreSQL adapters. Package ID/SHA-256 claims are now authoritative in the
  final SQLite candidate transaction, and successful import logs commit with
  the receipt and candidates. PostgreSQL migration 2 contains metadata only;
  central startup remains fail-closed.
- Added the first complete PostgreSQL clinical write slice for reviewed centre
  packages: source metadata, active-candidate deduplication, deterministic
  quality findings, serialized hash-chain audit and terminal import logging
  commit atomically. The existing SQLite endpoint now uses the same repository
  seam; central startup remains fail-closed.
- Encrypted reviewed packages now require timezone-aware ISO timestamps before
  either database adapter runs, avoiding SQLite/PostgreSQL drift.
- Added an explicit confirmed-data read repository with exact-centre or
  all-centres scope, pseudonymous subject/visit filters, deterministic order
  and latest-quality projection for SQLite and PostgreSQL. The existing
  reviewed-recognition workbook now uses this seam without changing its HTTP
  or workbook contract.
- PostgreSQL migration 4 adds only a partial confirmed-read index. Imported
  centre-package values remain `not_submitted` until transfer/read-back
  persistence is qualified, and central HTTP remains fail-closed.
- Added a provider-independent institutional identity authorization contract.
  Institution-verified MFA identity is separated from application-controlled
  study membership; only the latter supplies role and centre.
- Production readiness now requires an actually ready identity adapter as well
  as approved configuration and unexpired evidence. The current runtime passes
  no such capability and remains fail-closed.
- Kept the central profile fail-closed pending a selected and qualified
  OIDC/SAML adapter, membership persistence, HTTPS, remaining workflow
  repositories, workers and operational qualification.

### Release blockers

- Qualified institutional OIDC/SAML verification, membership persistence and
  the remaining central repositories.
- Verification passed Python compilation, JavaScript syntax checking,
  `uv lock --check`, 228 tests with five PostgreSQL-only cases skipped locally,
  and focused identity/readiness checks. The upstream Starlette/httpx
  deprecation warning remains.
