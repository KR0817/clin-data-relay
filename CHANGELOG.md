# Changelog

All notable changes are recorded here before a versioned release is created.
This file is not a substitute for a Git history or an approved project license.

## Unreleased

### Added

- Added a deterministic, value-free Benchmark v1 allocation for 30 development
  and 120 locked synthetic reports, including a prespecified 30-report masked
  double-review subset and immutable artifact hashes.
- Added directional model-error transitions, human correction workload,
  deliberate abstention, availability uncertainty and prespecified stratum
  summaries to the synthetic benchmark engine.
- Added the Benchmark v1 protocol, reproduction gates and an explicitly unrun
  report skeleton that separates formal sample size from release smoke tests.

### Changed

- Advanced formal prediction, benchmark summary and package contracts to v2
  while retaining prediction-v1 input compatibility for demonstration fixtures.
- Kept `bench-v1` uncreated until source, annotation, adjudication, both paired
  prediction arms and the immutable result package actually exist.

## [0.3.0] - 2026-09-01

### Added

- Added a versioned, executable synthetic extraction benchmark with strict and
  numeric-normalized field metrics, report-clustered confidence intervals,
  paired arm comparisons, a frozen error taxonomy and value-free artifacts.
- Added an allow-listed OpenAI-compatible model-provider boundary while keeping
  Kimi as the default and retaining the existing `/api/settings/kimi` surface.

### Changed

- Expanded the Windows Lite packaged black-box check to cover a synthetic image,
  missing-key local fallback, synthetic pulmonary PDF extraction, bulk human
  review and reviewed Excel export without a live provider call.
- Updated provider-aware portable verification and aligned all release metadata
  and corresponding-source references on `v0.3.0`.

## [0.2.1] - 2026-08-31

### Fixed

- Made clean Windows and macOS Lite builds prepare the exact English and
  Simplified Chinese `tessdata_fast` files from an immutable upstream commit,
  enforce download bounds and verify pinned SHA-256 digests before packaging.
- Reserved source-only tag `v0.2.0` as the build-reproducibility finding and
  moved the downloadable, black-box-verified release to `v0.2.1`.

## [0.2.0] - 2026-08-31

### Changed

- Relicensed first-party repository content under the OSI-approved
  `AGPL-3.0-only` license and aligned Python, Remotion and citation metadata.
- Added the AGPL text and corresponding-source notice to first-party portable
  bundle builders, plus a public source link in the workbench.
- Added a Chinese README, POSIX-shell quick start, citation metadata, explicit
  AI-assisted development disclosure and a preregistered-style extraction
  benchmark protocol with no fabricated results.
- Kept clinical, privacy, human-review, Authority EDC and production BLOCK
  boundaries separate from the open-source license.

## [0.2.0-showcase.1] - 2026-08-31

### Changed

- Replaced the internal operator manual at the repository root with a concise
  public landing page and kept detailed operational material under `docs/`.
- Added a source-available evaluation license, contribution and security
  policies, an architecture diagram, synthetic UI screenshots and a
  reproducible two-minute product tour.
- Added a release gate that checks public artifacts, repository history,
  forbidden runtime paths and credential signatures without printing values.
- Preserved the real Git history and the research-prototype, human-review and
  Authority EDC boundaries; this showcase is not production authorization.

- Established a clean Git source root that excludes runtime data, secrets and
  build outputs.
- Added the owner-approved source-available evaluation `LICENSE`; production,
  clinical and commercial use still requires separate written authorization.
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
- Added PostgreSQL Study Membership persistence using a pseudonymous principal
  identifier instead of the raw identity-provider subject. One active grant per
  principal, idempotent reasoned deactivation and the shared serialized audit
  hash chain now commit atomically under schema version 5.
- Extracted the PostgreSQL audit-chain writer/verifier so reviewed-package and
  membership lifecycle events extend one global chain under the same advisory
  lock. The real PostgreSQL 16 CI contract now runs confirmed-read and
  membership lifecycle tests as well as bootstrap/import tests.
- Added digest-backed PostgreSQL Institutional Sessions under schema version 6.
  Sessions require the existing MFA and effective-membership authorization,
  cannot outlive provider authentication or membership expiry, fail immediately
  after membership deactivation and append atomic create/revoke audit events.
  Plaintext bearer tokens are returned once and excluded from persistence and
  object representations.
- Added a witnessed operator-only command for the first Central Data Manager
  Study Membership. It derives the existing pseudonymous Principal ID from the
  exact qualified-client OIDC subject, atomically admits one bootstrap grant,
  and never persists or returns the raw subject. An audited correction is
  available only before any Companion Session history exists.
- Added an operator-only emergency containment action for a mistaken
  bootstrap-created Central Data Manager after login. It deactivates only the
  referenced membership, appends a dedicated incident audit event, preserves
  session evidence, invalidates linked bearers through the active-membership
  check and never reopens bootstrap or creates replacement authority.
- Compacted the authenticated command deck for central and centre workspaces.
  Detailed EDC/production diagnostics now remain available inside a native
  system-status disclosure, while mobile session actions, navigation, workflow
  steps and the research run strip expose the next task sooner without changing
  authorization or API behavior.
- Study Membership grants now reject an expiry at or before grant time, and
  deactivation timestamps cannot predate the persisted grant.
- Production readiness now requires an actually ready identity adapter as well
  as approved configuration and unexpired evidence. The current runtime passes
  no such capability and remains fail-closed.
- Kept the central profile fail-closed pending a selected and qualified
  OIDC/SAML adapter, membership administration/HTTP composition, HTTPS,
  remaining workflow repositories, workers and operational qualification.

### Release blockers

- Qualified project-owned or contract-approved OIDC verification, routine
  membership administration, HTTP composition and the remaining central
  repositories.
- Verification passed Python compilation and 278 tests with thirteen
  PostgreSQL/external-service cases skipped locally. GitHub Actions run
  `32663416538` passed both the Windows source-quality job and the PostgreSQL 16
  concurrent bootstrap contract. The upstream Starlette/httpx deprecation
  warning remains.
