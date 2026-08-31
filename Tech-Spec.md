# Clinical EDC Companion Operations Release Technical Specification

**Date:** 2026-08-11

## PostgreSQL repository bootstrap

- `app/postgres_repository.py` is the first PostgreSQL seam. Its public
  interface prepares the repository bootstrap and returns a redacted immutable
  status containing only backend, server major version, schema version,
  migration count and `clinical_data_ready=false`.
- `COMPANION_POSTGRES_DSN` is runtime secret material. It is read only at the
  module boundary and must never be stored in settings payloads, logs, audit
  rows, health responses or project files.
- The bootstrap uses one transaction-scoped PostgreSQL advisory lock and a
  `companion_schema_migrations` ledger. Version 1 proves connection,
  transactional DDL and migration privileges; it creates no clinical table.
- Unknown future migration versions fail closed. Repeated preparation does not
  duplicate a migration row.
- Production-like environments require `sslmode=verify-full`. `development`
  and `test` may use non-verifying modes only over localhost or a Unix socket.
- Psycopg is a `central` optional dependency. The Centre Lite build does not
  import or require it. The CI integration job uses PostgreSQL 16 and an
  ephemeral run-specific credential.
- Central application startup remains disabled until clinical repository and
  institutional identity adapters satisfy their contract tests.

## Modular-monolith extraction and future repository seam

- `app/api/static_delivery.py` owns the public browser files and a closed image
  allow-list. Its interface is one router factory; it never mounts the project
  tree or accepts a filesystem path from the request.
- `app/api/authentication.py` owns role constants, login payload validation,
  bearer-session resolution and the login route. Its interface returns an
  `AuthModule` containing one router and one dependency callable used by the
  remaining route modules.
- Authentication receives the existing `Database`, environment and optional
  centre profile. It preserves the same SQLite transaction and audit-chain
  behavior. It does not create a speculative identity-provider abstraction;
  the second implementation will be added only when institutional OIDC/SAML is
  selected.
- `app/main.py` remains the application composition root. The first extraction
  removes duplicated static/authentication implementation but deliberately
  leaves unrelated clinical SQL in place for later vertical repository slices.
- The future central repository seam will expose domain operations rather than
  raw connections or ORM models. SQLite and PostgreSQL adapters must pass the
  same repository contract tests before central mode can start.
- Schema migration tooling is not added until the first PostgreSQL vertical
  slice exists. Startup-time SQLite compatibility upgrades remain the only
  migration implementation in this tranche.
- SQLite records its converged local schema in `schema_migrations`; health
  exposes the applied integer version so package diagnostics can distinguish
  application and database revisions without exposing a database path.

## Canonical source root and Git baseline

- `C:\ClinData Relay` is the canonical checkout. Scripts must derive paths
  from their own location or the process working directory; no source file may
  contain the retired absolute workspace path.
- The repository branch is `main`. The initial annotated tag is
  `v0.2.0.dev0`, matching `app.version.__version__`.
- `.gitignore` is the enforcement boundary for runtime and generated state.
  A pre-commit inventory must also reject credential-like filenames, SQLite
  files and oversized source artifacts.
- GitHub hosting is private. The root `LICENSE` is proprietary, so source access
  or distribution requires separate written owner authorization. A future
  public source release requires explicit relicensing and release review.
- `.github/workflows/quality.yml` is the source quality gate. It uses Python
  3.12, the pinned uv CLI, `uv sync --all-extras --frozen`, Python compilation,
  Node syntax checking and pytest on a Windows runner. It receives no runtime
  or provider secrets.

## Kimi settings module

- `app/api/kimi_settings.py` owns the validated key payload, redacted Kimi
  status projection and the centre-local settings router.
- Its router-factory interface receives the existing database, Kimi client,
  product mode, centre profile and authenticated-user dependency. It adds no
  provider abstraction and never returns or audits credential material.
- `app/main.py` registers the router and reuses the same status projection for
  health. Kimi extraction remains in the clinical extraction flow and is not
  moved by this slice.

## Dreamina static visual-asset pipeline

- Dreamina is a development-time provider only. The official local CLI creates
  source images from reviewed prompts; the workbench never contains a Dreamina
  SDK, API call, provider URL, credential or runtime feature flag.
- Source prompts and credential-free task metadata live under
  `packaging/assets/`. A ledger records prompt hash, task ID, model label,
  source hash, derivative hash, dimensions and human-review outcome. Provider
  account details and secrets are excluded.
- Approved sources are converted once to compressed WebP files under
  `app/static/img/`. Only these derivatives are included in application and
  centre-package static assets.
- `#workspace-context-art` is decorative and switches between a closed local
  central/site asset map in `workbench.js`. Oversight reuses the neutral central
  asset. The asset does not determine the role, centre scope or CTA.
- Candidate review renders a local decorative illustration only for an empty
  collection. Populated review data, actions and announcements remain unchanged.
- Every image has an empty accessible name, `aria-hidden="true"`, fixed width
  and height, bounded opacity and `pointer-events: none`. CSS preserves a solid
  text surface and hides nonessential context art on narrow screens.

## Role-aware workspace projection

- `app/static/js/workbench.js` derives `central`, `site` or `oversight` from the
  authenticated user's existing role. It writes the value to
  `document.body.dataset.workspaceMode` and fills the research run strip from a
  closed local configuration map. No role or centre value comes from query
  parameters or browser storage.
- `app/static/index.html` contains one shared run-strip component and one shared
  navigation. Links carry role-specific labels and allowed projection modes as
  presentation metadata; existing section IDs remain the navigation targets.
- Central and oversight projections open the existing operations disclosure
  after login. Site projection keeps intake as the primary destination. Lite
  mode still wins over workspace presentation through the existing
  `.lite-full-only` boundary.
- CSS consumes `data-workspace-mode` only for visual tokens and layout. The
  central accent is teal, the site accent is blue and oversight is slate; every
  state also has text, so color never carries permission meaning alone.
- The primary workspace link updates its target and label from the closed
  configuration. Workspace navigation uses `aria-current` for the most recent
  same-page destination and preserves DOM/tab order.
- This projection must not alter API calls, role checks, candidate review
  eligibility, centre scoping, transfer semantics or audit events. Hidden
  elements remain protected by their current server-side authorization.

## Workbench visual system

- `design-system/clinical-edc-companion/MASTER.md` is the visual source of
  truth. The browser implementation remains plain HTML, CSS and JavaScript.
- Semantic CSS tokens define page, surface, text, border, focus and status
  colors. Component rules consume tokens; clinical state must not be inferred
  from decorative color alone.
- The header, session summary, workflow navigation, step rail and workflow
  cards use the existing DOM and event handlers. New navigation links are
  same-page anchors and do not introduce client routing or shared state.
- System fonts and local WebP derivatives preserve offline startup and the
  current same-origin CSP. Data
  identifiers use the installed monospace fallback stack. Remote font imports,
  icon libraries and animation dependencies are prohibited.
- Responsive rules target 1440, 1024, 768, 375 and 375-by-812 landscape/portrait
  checks. Flexible grids must use `minmax(0, 1fr)` and long statuses must wrap.
- Motion is limited to 150-220 ms color, border and shadow transitions;
  `prefers-reduced-motion: reduce` disables them. Hover does not move cards or
  alter layout bounds.
- No HTTP payload, API endpoint, authorization decision, review policy or audit
  event changes as part of this tranche.

## Design principles

- Keep LibreClinica as the sole authority EDC.
- Reuse the existing FastAPI, SQLite and vanilla JavaScript stack.
- Add deterministic controls before adding automation.
- Store immutable events and releases; do not overwrite historical meaning.
- Treat every external integration as optional, capability-reported and fail-closed.
- Keep deployment seams explicit: static browser assets, runtime configuration and
  persistence adapters must be independently testable without changing the
  candidate/review contract.

## Review policy and tamper-evident audit chain

- `app/bulk_accept_policy.py` is the single pure policy seam for bulk review.
  Default eligible provenance is `agreement`, `local_only` and
  `local_fallback`. `conflict` and `kimi_only` require item review. A central
  data manager can extend the source set only with a bounded written reason.
- The policy returns accepted IDs, stable per-candidate skip reasons and one
  normalized summary. The API persists that same summary instead of
  reconstructing review meaning in the browser.
- Conflict item review requires `selected_source=local|kimi|manual`. Manual
  selection requires `edited_value`; Kimi-only acceptance requires
  `evidence_acknowledged=true` and the candidate's de-identified source ID.
- `app/audit_chain.py` canonicalizes the complete immutable event payload.
  `Database.append_audit_event()` reads the chain tail and inserts
  `prev_hash/event_hash` in the caller's existing SQLite transaction. Existing
  rows are backfilled once in rowid order during the additive schema upgrade.
- Chain verification protects event metadata and details, is reported by
  readiness, and is required by the application database backup check. Backup
  evidence includes an externalizable chain anchor. The chain is explicitly
  not a replacement for controlled central audit storage or WORM retention.
- SQLite connections enable foreign keys, WAL and a bounded busy timeout.
  Startup converts interrupted `running` recognition jobs/items to a retryable
  failed state because the supported local profile has one application writer.
- Image upload accepts only PNG/JPEG with matching signatures, a successful
  Pillow verification pass and an explicit 50-million-pixel ceiling. PDF
  upload applies cheap container limits before pypdf; Tesseract runs with a
  45-second timeout and writes stdout to a bounded temporary file. Full PDF
  parsing still lacks a killable helper-process timeout and remains listed as a
  production hardening item.

## Kimi default-on configuration

- `KimiSettings.from_environment()` defaults `KIMI_ENABLED` to `true`.
- `KIMI_ENABLED=false` is an explicit local-only opt-out; it is not inferred
  from a missing key.
- `KimiClient.ready` still requires a recipient-local key, an allow-listed
  Moonshot base URL and the `kimi-k3` model. Missing credentials therefore
  produce `key_required` health state and a local fallback rather than an
  outbound request.
- Launchers remove inherited `KIMI_API_KEY` values and use only the ignored,
  ACL-restricted `.runtime/kimi-api-key.txt` file. Configuration helpers prompt
  interactively and never package or print the secret.
- The browser displays Kimi as the default workflow only after health reports
  `ready`; while `key_required`, it shows the actionable configuration state and
  keeps local OCR available.
- Recognition-job API items default `use_kimi=true`; a caller can explicitly
  opt out per item, while the UI snapshots the current toggle into each queued
  report.
- The portable launcher always sets `KIMI_API_KEY_FILE` to its private runtime
  path, even before the file exists. Authenticated centre Lite users may replace
  that file through the settings endpoint. The write uses an atomic temporary
  file with current-user-only permissions, then reloads `KimiSettings` on the
  existing client instance; secrets never enter SQLite, audit details or HTTP
  responses.

## Encrypted centre packages and operational controls

- `app/offline_package.py` emits an outer `clinical-edc-reviewed-package-encrypted`
  envelope. The inner canonical reviewed package is encrypted with AES-256-GCM;
  Scrypt (`N=2^17,r=8,p=1`) derives the key from a request-supplied passphrase
  and a per-package random salt; the previous `N=2^15` envelope remains
  read-only compatible. AES-GCM uses a new 96-bit nonce per package and binds
  centre, dictionary, KDF parameters and the local audit-chain anchor as AAD.
  The package SHA-256 covers the canonical encrypted envelope without its
  self-hash. Passphrases and plaintext are never persisted.
- `POST /api/imports/reviewed-packages` accepts up to 100 package files plus one
  passphrase. Each file is decrypted, hash checked, compared to the active CRF
  dictionary release, deduplicated by package SHA-256 and logged independently.
- `offline_package_import_logs` stores package hash, filename, dictionary
  versions, result code and bounded failure detail only; it never stores
  ciphertext or clinical values.
- `source_files.content_purged_at` marks expired original bytes. The retention
  command keeps the source SHA-256 and audit rows but removes physical original
  files and makes later extraction return `source_file_content_expired`.
- The start script runs the existing online-backup/temporary-restore check
  before launching the companion when a database already exists. OS disk
  encryption is reported by a read-only endpoint; BitLocker/FileVault changes
  remain an administrator action outside the app.
- `principal_investigator` and `central_data_manager` are the only global
  repository roles. Site accounts are centre-scoped and generated through the
  central account lifecycle API.
- `app/production_readiness.py` evaluates runtime capability plus an
  unexpired, secret-free production evidence manifest. Environment variables
  alone never satisfy production gates. The manifest is metadata only and is
  not a clinical validation record by itself.
- Production gates include data-governance approval, HTTPS, managed secrets,
  institution identity/MFA, qualified PostgreSQL repository, backup/restore,
  disk encryption, validation evidence, qualified Authority EDC, monitoring,
  incident response, SOP/training and disaster recovery.

## Deployment profiles and seams

- `app/runtime_config.py` is the deep runtime-configuration module. Its interface
  resolves `environment`, `product_mode`, `deployment_profile` and a redacted
  database-backend label from constructor arguments and environment variables.
- `local` is the supported profile for tests and workstation use. `lite` selects
  the local-only fail-closed adapter; `full` selects the optional LibreClinica
  adapter. Both use the existing SQLite repository and keep writable state out of
  packaged application assets.
- `central` is an explicit fail-closed profile until a PostgreSQL repository
  adapter, managed identity, TLS and backup evidence are qualified. It must never
  fall back to SQLite or expose a partially migrated multi-writer mode.
- `app/static/css/app.css` and `app/static/js/workbench.js` are served by
  FastAPI's static-file seam. The first JavaScript extraction keeps the existing
  global handler names for compatibility; later slices may split the bundle
  into API, intake, review, administration and transfer modules after seam
  tests exist.
- The workbench's recognition-job panel is a thin projection of the durable
  job interface. It does not duplicate item state in a second store; refresh
  loads the latest role-scoped job and actions call the same run/cancel/retry
  routes used by recovery tooling.

## Modules

- `app/quality.py`: load and validate versioned quality rules; evaluate candidate values.
- `app/structured_import.py`: parse bounded UTF-8 CSV and return normalized rows.
- `app/operations.py`: pure helpers for scope keys, lock resolution, task types and snapshot hashing.
- `app/main.py`: persistence, authorization and HTTP orchestration using existing database helpers.
- `app/edc_adapter.py`: optional `read_value` capability with an explicit unsupported result for the current LibreClinica adapter.
- `app/offline_package.py`: canonical JSON package builder/parser with a
  content hash and strict pseudonymous reviewed-value schema. It has no EDC
  client and is intentionally suitable for file-based centre exchange.
- `app/static/index.html`: compact operations panels integrated into the existing workbench.

The first structural refactor adds `app/persistence.py` as a deep local
repository-bootstrap module. Its small interface is `Database(path)`,
`initialise()` and `connect()`. It owns SQLite connection pragmas, schema
bootstrap, additive compatibility columns, indexes and synthetic demo-account
seeding. HTTP handlers continue to receive the same row objects and do not learn
new storage details.

This seam is deliberately SQLite-only for now. A PostgreSQL adapter will be a
separate implementation after repository contract tests exist; this tranche does
not add a second shallow adapter or claim central deployment support.

The application factory also installs one response-header middleware. It adds
`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`,
`Permissions-Policy` and a same-origin CSP. The workbench JavaScript is served
from `/static/js/workbench.js`, so `script-src 'unsafe-inline'` is no longer
needed.

## Persistence

New tables are append-oriented unless explicitly marked mutable workflow state:

- `quality_findings`: immutable evaluation result per candidate/rule version.
- `data_issues`: mutable current companion issue status plus immutable audit events.
- `transfer_holds`: append-only hold/release records; effective state is the latest event per scope.
- `visit_attestations`: append-only pre-transfer attestations invalidated by later data changes. These are not electronic signatures.
- `readback_checks`: append-only authority verification attempts.
- `dictionary_releases`: immutable published/rolled-back releases; one active release pointer.
- `dictionary_release_items`: release-specific display labels.
- `tasks`: mutable assignment/status with audit events.
- `analysis_snapshots`: immutable canonical JSON plus SHA-256.
- `user_account_events`: append-only lifecycle metadata.

Existing tables gain only minimal columns needed for provenance: structured import batch ID and origin type on candidates; read-back state on transfers; a canonical candidate-state SHA-256 on visit attestations.

The durable recognition-job seam adds `recognition_jobs` and
`recognition_job_items` to the local repository. The job stores only bounded
workflow metadata (centre, subject/event, selected field codes and source-file
IDs); it never stores raw image bytes or API credentials. A future worker may
claim queued items, call the existing local extraction modules and update the
ledger. Until that worker is qualified, the bounded caller-triggered `run`
bridge and the browser's synchronous recognition path remain the execution
paths; no distributed queue dependency is introduced.

Execution is fail-closed at the job-state boundary: `POST .../run` rejects a
job already in `running` state with `recognition_job_already_running`, and
`POST .../cancel` rejects a running job with `recognition_job_running`. This
prevents duplicate candidate creation and avoids claiming cancellation while a
current extraction call may still create candidates. The UI disables both
actions in the running state; queued jobs remain cancellable and failed jobs
remain retryable.

## Quality evaluation

- Rules are loaded from `config/clinical_quality_rules.v1.json` and validated at startup.
- Numeric parsing is strict and locale-safe. Inequality values such as `<0.5` are preserved and can produce a warning when a numeric rule cannot be applied exactly.
- Unit comparison is normalized but no unit conversion occurs unless the rule explicitly declares a factor.
- `BLOCK` findings prevent review acceptance and transfer; `WARN` requires visibility but not a mandatory reason.
- Re-evaluation creates a new finding set with its own rule version; it never deletes prior findings.

## Companion issue state machine

`open -> answered -> resolved`, with `resolved -> open` allowed only for the central data manager. Site investigators may answer only within their centre. Query text is bounded and sanitized.

## Transfer-hold resolution

Scope specificity is `dataset`, `centre`, `subject`, `visit`. A record is held when the latest relevant hold event is `held`. The same helper is called by review, bulk review, import, transfer creation and submission. Formal Authority-EDC locks are not duplicated.

## Visit attestation validity

An attestation stores a SHA-256 over the visit candidate IDs, statuses, final values, units and review timestamps. History responses recompute that state and return `valid=false` with `candidate_state_changed` after any later candidate creation or review change. This is a companion acknowledgement only, not an electronic signature or Authority-EDC freeze.

## Read-back

- The adapter returns `matched`, `mismatch` or `unsupported` plus a response hash and no raw response.
- A matched result upgrades the transfer read-back state to `verified`.
- A mismatch retains the submitted transfer, records expected/observed hashes or bounded values, and creates a central task.
- The current LibreClinica adapter returns `unsupported` because its qualified SOAP surface exposes import but no approved clinical-value read API. Direct database verification remains a qualification script only and is not used in the application.

## Structured import

- Maximum file size: 5 MiB; maximum rows: 5,000.
- Required headers are exact stable API names; unknown columns are reported and ignored only if required columns are present.
- Rows are normalized, dictionary checked, quality evaluated and duplicate checked before persistence.
- Each accepted row becomes a normal `candidate`; review and transfer gates are unchanged.

## Pulmonary-function PDF extraction

- `config/pulmonary-function-field-dictionary.v1.json` is the immutable source for the 21 workbook headers, report-label aliases, value-column selection and units.
- The runtime CRF dictionary projects the 18 clinical fields into each supported visit so the user-selected visit remains the authoritative context. The three source-identifier headers remain visible to dictionary administrators but are non-uploadable.
- `app/pulmonary_function.py` uses `pypdf` locally, accepts at most five pages, rejects encrypted or textless PDFs, normalizes whitespace and parses only anchored pulmonary row labels.
- Row extraction is deterministic: ordinary spirometry and diffusion rows select the measured column; `FEV1实/预` selects the measured/predicted column; single-value `VBEex` selects its only numeric value. The `REF` workbook header has a `PEF` report alias.
- The parser returns field code, normalized decimal text, unit and sanitized evidence metadata. It never returns or stores patient demographics or report identifiers.
- `POST /api/source-files/{id}/pulmonary-function-extract` is idempotent by source file and visit, creates ordinary human-review candidates and records `local-pdf-pft-candidate-v1` provenance.
- PDF intake bypasses the image masking and Kimi paths. The original remains in the existing local source store under the same synthetic/approved-use boundary.
- New dictionary fields are merged into an existing active dictionary release by a new system-authored published release while preserving prior display-header overrides.
- Authority submission remains fail closed until corresponding LibreClinica CRF items and verified OIDs exist; no placeholder OIDs and no direct LibreClinica database writes are introduced.

## Engine-neutral extraction evidence

`app/extraction_contract.py` defines the small boundary shared by the PDF, local OCR and hybrid paths. An `ExtractionEvidence` record contains only canonical metadata and bounded de-identified spans:

- `contract_version`, `engine`, `engine_version`, `model_ids`;
- source/derivative SHA-256, dictionary id/version and preprocessing version;
- duration, page count/dimensions, field spans and closed-enumeration warnings;
- an idempotency key derived from the source derivative, active dictionary release, selected fields, engine/model and preprocessing.

The record contains no raw bytes, credentials, report identifiers or unbounded provider response. SQLite persists it in `extraction_runs`; candidates reference the run. A unique idempotency index makes retries return the original run. Existing candidate schemas are upgraded additively so prior databases remain readable.

`GET /api/source-files/{id}/pdf-inspection` uses the local `pypdf` reader to classify text-layer versus scanned pages without creating candidates. It reports page count, text character counts and a stable `pdf_text_layer|pdf_scanned_pages|pdf_invalid` classification. Scanned pages are diagnosable but remain blocked until a separately qualified local OCR adapter is enabled.

`app/ocr_evaluation.py` evaluates synthetic gold manifests only. It reports exact-match, numeric-tolerance, unit-match, missing and extra-field metrics; it never logs source values. PaddleOCR remains a feature-gated future adapter, not a second authoritative pipeline.

## Recognition field scope

- `GET /api/recognition-fields?event_ref=` projects the active published display headers for uploadable candidate fields. It is available only to workflow write roles and never exposes identifier-only dictionary rows.
- `LocalOcrExtractPayload.field_codes` is an optional bounded, unique list of uppercase stable field codes. Omission means the complete event allow-list for backward compatibility; an explicit list must be non-empty and a subset of the event allow-list.
- PDF, local OCR and hybrid OCR/Kimi paths filter local values and the Kimi field dictionary before candidate persistence. Kimi output outside the explicit selection is ignored.
- The browser snapshots the current selection into each batch item so changing the controls after upload cannot change an in-progress batch.
- The browser maintains a session-only `pendingUploadQueue`. Adding reports validates the pseudonymous subject code, visit, selected field codes and accepted file types, then snapshots those values plus the current Kimi preference into each queued file. Files are not uploaded until the reviewer starts the queued batch.
- The initial empty queue render disables the add action until field metadata is
  available. `refreshRecognitionFields()` must therefore re-render the queue in
  its completion path; directly enabling only the upload action leaves the add
  action permanently disabled after login.
- `activeUploadBatch` is created from the queue without rewriting subject or visit values. Upload form fields and extraction payloads are always read from `item.subjectRef` and `item.eventRef`, never from the current intake controls. Queue controls are disabled while preparation or recognition is running.
- Candidate review rendering partitions the existing role-scoped response by `edc_subject_ref` and `edc_event_ref`, with the active batch shown first. Candidate decisions remain item-level requests and bulk review continues to send explicit candidate IDs.

## Reviewed-recognition Excel export

- `/api/exports/reviewed-recognition-data.xlsx` selects role-scoped `human_confirmed` candidates regardless of transfer state; `/api/exports/submitted-data.xlsx` retains its submitted-only contract.
- Event sheets are wide tables whose clinical columns are derived from field codes actually present in the selected rows, not the complete dictionary. Fixed columns include centre, subject research code and aggregate LibreClinica state (`all_submitted`, `partially_submitted` or `not_submitted`).
- Workbook notes explicitly identify the output as a companion reviewed-recognition export. Formula-leading values remain escaped, and the field-mapping sheet is restricted to the exported fields.
- API fetches use `cache: no-store`; bulk-review responses are also applied to in-memory candidates before a server refresh so accepted rows cannot remain actionable because of a stale client response.
- A bulk-review click computes IDs from the current in-memory projection. When
  that projection is empty, the handler performs one bounded
  `refreshRecognitionJobs()` plus `refreshCandidates()` cycle, recomputes the
  requested group and continues the original click. It never loops and never
  falls back to candidate IDs outside the recovered active job.

## Deferred Authority provisioning

- Source upload validates and stores the pseudonymous subject/event context before local processing. LibreClinica provisioning is best-effort: a sanitized `EdcAdapterError` produces `edc_subject_provisioning.status=deferred` plus its stable error code instead of failing the upload.
- Deferred state does not change the source hash, candidate provenance or review gates and never claims an Authority record exists. Local recognition, human review and reviewed-recognition export remain available.
- On an explicit transfer submission, the application retries idempotent subject/event provisioning before ODM import. Provisioning or import failure changes only the transfer ledger to `failed`; accepted companion values and Excel export remain intact.

## Dictionary releases

- Existing mutable header overrides are migrated into release `baseline-import`.
- Editing creates or updates a central-only draft.
- Publish validates all item keys against the immutable field dictionary and atomically activates a new release.
- Rollback creates a new release referencing the selected historical release; historical releases are never reactivated in place.

## Security

- Never read or expose ignored credential files.
- Account creation uses server-generated one-time bootstrap tokens in tests only; production provisioning requires external identity approval.
- Centre first-run plaintext credentials live only in browser memory until the
  user confirms storage. An explicit copy or text-download action is permitted;
  the server still sees the chosen password only during setup and persists its
  scrypt hash. The local reset command requires filesystem access to the centre
  installation, rotates the scrypt hash, revokes all sessions and appends a
  credential-free audit event.
- Monitor/auditor roles are read-only and cannot download source images.
- CSV values are treated as untrusted text and never executed or interpreted as formulas in exported spreadsheets.
- Spreadsheet exports force formula-leading untrusted values to text and never create formulas from uploaded or reviewed values.

## Operational readiness

- Health reports database backup age, adapter/read-back capability, rule/dictionary versions and external integration gates.
- A backup script uses SQLite online backup, creates SHA-256 evidence and performs a restore/integrity check into a temporary database.
- The live launcher points the health endpoint and backup script to the same ignored `.runtime/backups` directory.
- Production readiness remains `BLOCK` unless HTTPS, managed secrets, backup restore evidence, approved identity provider and validation evidence are configured.

## Confirmed-transfer presentation

- The client receives the existing role-scoped candidate and transfer collections; no API pagination or persistence semantics change.
- Human-confirmed candidates are ordered with non-final transfer states before `submitted`/`reconciled` states, then by review time descending.
- The list renders at most five rows until the user activates a button with `aria-expanded=true`; the same control collapses back to five rows.
- Re-rendering after review or transfer refresh preserves the current expansion choice for the session and recalculates the hidden count.

## Split batch review

- `recommended` is retained as the client compatibility name for active-batch
  `agreement`, `local_only` and `local_fallback` candidates that pass the
  server-side quality and hold gates.
- `reviewable` contains `conflict` and `kimi_only` candidates. Its control
  navigates to item-level evidence review and never sends a bulk acceptance
  request.
- Both controls remain enabled after login. An empty group produces a local status message and no HTTP request.
- The bulk control calls the role-scoped bulk-review API with explicit candidate
  IDs; each accepted candidate receives a `review_mode=bulk` human-confirmation
  event linked to the request summary hash.
- Quality BLOCK candidates are excluded from both groups and remain visible for
  individual resolution. `conflict` and `kimi_only` candidates remain visibly
  labelled, require a loaded confirmed derivative image and require the reviewer
  to select local, Kimi or a manual value explicitly.

## Kimi-bound derivative redaction

- Local line-level redaction covers patient identifiers, clinical staff
  identity/signature labels, and collection/receipt/review timestamp lines.
- The browser still requires visual preview confirmation; automated marker
  matching is not treated as proof that every identifier was removed.
- Only the confirmed derivative is eligible for the hybrid Kimi adapter.

## Windows portable distribution

- Use PyInstaller `onedir` with a console launcher; one-file temporary extraction is avoided because the application needs writable `data/` and `.runtime/` directories.
- The launcher binds only to `127.0.0.1`, creates writable local directories, selects a free configured port and opens the local browser after health succeeds.
- Static UI, versioned config, mapping data, Tesseract executable/runtime files and project language data are bundled. A Python/openpyxl exporter is the packaged fallback when the development Artifact Tool/Node runtime is absent.
- Build output excludes `.runtime`, databases, uploads, API keys, SOAP credentials and user-specific logs. A generated manifest records hashes of distributed files.
- Kimi is disabled until the recipient creates a local credential file. No sender credential or database volume is copied.

## Integrated portable runtime

- `Start-Clinical-EDC.cmd` is the single recipient entry point. It invokes a signed-source PowerShell bootstrap that verifies bundled hashes, loads the pinned offline Docker images when absent, starts a package-scoped localhost-only Compose project, completes local credentials and then launches the companion executable.
- The archive contains the LibreClinica application image, `postgres:16-alpine`, `marlonb/mailcrab:v1.1.0`, a Compose definition, and a custom-format PostgreSQL seed. Docker Desktop/WSL2 remains an operating-system prerequisite and is not redistributed.
- The seed is derived from the synthetic study metadata only. It preserves study, event, CRF, item, mapping and role configuration while removing all subject, event-CRF, item-data, session/login-audit and sender-password material. A clean-restore verification asserts those invariants before packaging.
- On first start, Kimi setup stores the recipient key in an ACL-restricted local file. LibreClinica generates a unique high-entropy password, stores a Windows-DPAPI-encrypted browser-login copy plus the SHA-1 representation required by the legacy SOAP interface, and applies the digest to predefined local accounts through `psql` stdin. No reusable password exists in the distributed archive and no cleartext password or hash appears in process arguments or logs.
- Docker Desktop itself is not redistributed: its current subscription agreement grants a non-transferable license and restricts third-party distribution. The launcher detects Docker, opens the official installer page when absent, and waits for the recipient to accept Docker's terms. Only the redistributable Docker images required by this product are bundled.
- The portable launcher reads only bundle-local credential files, points the adapter to the configurable localhost LibreClinica URL, enables subject provisioning and never allows remote authority endpoints.
- Subsequent starts reuse the package-scoped Docker volume and local runtime files. `Stop-LibreClinica.cmd` stops containers without deleting the volume.
- A clean-install QA project uses distinct Compose names, ports and volumes, proves Kimi/adapter readiness, performs OCR, human review, subject provisioning and SOAP submission, then destroys only the named QA resources.

## Lite portable runtime

- `COMPANION_PRODUCT_MODE=lite` is the presentation/runtime profile. The health interface exposes `product_mode=lite`; the EDC adapter is forced to `simulation_only` even if the recipient environment contains unrelated LibreClinica variables or credential files.
- The existing intake, pulmonary PDF parser, image de-identification/OCR, candidate review, SQLite repository and reviewed-recognition workbook exporter remain the deep modules behind the same HTTP interfaces. Lite is an adapter/profile at the launcher and presentation seams, not a copied application.
- `Start-Clinical-EDC-Lite.exe` infers the Lite profile from its packaged executable name before importing `app.main`. The UI hides operations, Authority readiness, freeze/submit, transfer/reconciliation and dictionary-administration surfaces, renames the confirmed section to local reviewed data, and retains upload, scope selection, review and Excel export.
- Windows cannot embed a custom icon in a command script. The build therefore makes the icon-bearing `Start-Clinical-EDC-Lite.exe` the only root start entry and stores `Start-Clinical-EDC-Lite.cmd` under `compatibility/` as a secondary command entry point. This avoids movable-package failures caused by absolute paths inside Windows shortcut files and prevents two visually identical root filenames. Optional `Configure-Kimi.cmd` stores a recipient key under the bundle-local ACL-restricted `.runtime` directory; it is never required for local PDF extraction.
- PyInstaller receives the same ICO for the Lite executable. The Dreamina source PNG, prompt and credential-free provenance remain build inputs; recipient ZIPs contain the ICO but not provider task records, account data or API credentials.
- `scripts/build_windows_lite.ps1` builds a separate onedir/ZIP, copies only the Python application, Tesseract, required configuration, minimal recipient documentation and relevant license texts, rejects runtime/secret artifacts and asserts that Docker/LibreClinica assets are absent.
- Build verification launches the packaged EXE with an isolated data root, asserts the Lite health contract, exercises a representative PDF through upload/extraction/human review/reviewed Excel export, writes a verification JSON and then creates `MANIFEST.sha256` plus the ZIP.

## Centre-specific Windows Lite runtime

- `app.centre_profile` is the single parser for `clinical-edc-centre-lite` profile version 1. It accepts only `profile_type`, `profile_version`, `centre_code` and `username`, with bounded uppercase centre and email-like username formats.
- The portable launcher sets `COMPANION_CENTRE_PROFILE_FILE` only when a bundle-root `centre-profile.json` exists. External inherited profile variables are removed first.
- `Database.initialise()` seeds the existing synthetic demo users when no profile is configured. With a centre profile it seeds one locked `site_investigator`; any pre-existing user set that is not exactly the matching account fails with `centre_profile_database_scope_mismatch`.
- One-time setup is exposed only for a configured locked centre profile. Passwords require 16-128 characters with upper, lower, digit and symbol classes, are encoded with stdlib `hashlib.scrypt` plus a random salt, and are compared with `hmac.compare_digest`. Legacy demo digests remain readable for development compatibility.
- The first-run browser uses `crypto.getRandomValues` to produce a 24-character password, requires confirmation, completes setup, then logs in through the ordinary session endpoint. Setup never returns or persists the password.
- `scripts/build_windows_centre_packages.ps1` reuses one verified Windows Lite build, copies it per validated profile, adds the profile and centre guide, regenerates the manifest, runs isolated black-box verification and writes one ZIP plus verification JSON per centre.
- Centre-package QA inspects the newly created SQLite repository after the packaged process stops to assert one matching user, zero other/global users and no direct password material. The QA directory is removed before delivery.
- Launcher reuse is identity-aware. `/api/health` must match the expected
  product mode and, for a centre build, the exact profile code and username.
  A mismatched healthy Companion on the preferred port is never opened as the
  requested package; the launcher searches only the next ten localhost ports.
- `recognition_job_items.candidate_ids_json` stores the ordered IDs returned by
  the successful extraction call. The field is empty for queued/failed legacy
  items and is replaced atomically on a successful retry. Job response payloads
  expose it as `candidate_ids` without source paths or evidence content.
- For a succeeded legacy item, both SQL `NULL` and the JSON value `[]` mean that
  no usable association was persisted. The response then derives candidate IDs
  through the existing exact centre/subject/visit/selected-field and
  original-or-confirmed-derivative lineage query and persists any recovered
  IDs. A non-empty stored array remains authoritative.
- The workbench initially restores `activeBatchCandidateIds` from the latest
  recognition job before fetching candidates. Once the role-scoped candidate
  response is available, it preserves that batch when at least one of its IDs
  is pending; otherwise it selects the newest listed recognition job that still
  contains a pending candidate. This also advances bulk review to the next
  pending job after the current one is accepted. It does not infer candidate
  ownership from `source_file_id`, because image extraction uses a confirmed
  de-identified derivative with a different ID.

## macOS Lite distribution

- `app.portable_launcher` is the shared launcher implementation. The Windows wrapper preserves the current entry point; the macOS entry point forces `product_mode=lite` when Finder supplies no command-line arguments.
- The macOS build uses PyInstaller `onedir` plus `windowed` to produce `ClinicalReportExtractorLite.app`. It runs natively on the architecture used to build it; separate `arm64` and `x86_64` artifacts avoid an unverified universal-binary merge.
- Static/config data and the pinned tessdata remain resources inside the app. The build-host Tesseract executable is added as a collected binary so PyInstaller resolves and signs its native dependencies. Runtime discovery checks the PyInstaller resource root rather than assuming a Windows `.exe` path.
- Default writable state is `~/Library/Application Support/ClinicalReportExtractorLite`; the app bundle remains immutable. Kimi configuration is optional and stored with owner-only permissions under that data root's `.runtime` directory.
- `scripts/build_macos_lite.sh` rejects non-macOS hosts and architecture mismatches, builds the `.app`, verifies its signature, launches it with an isolated data root, runs the same 18-field PDF/review/Excel verifier, rejects secret/database/Docker/LibreClinica assets and creates an architecture-labelled ZIP plus verification JSON.
- Without a Developer ID environment value, PyInstaller's ad-hoc signature is accepted only for internal QA. With an installed Developer ID identity, the build uses hardened-runtime signing; optional notarization uses an existing Keychain profile and never accepts credentials on the command line.
- PyInstaller is not a cross-compiler. Windows can validate source, tests and the build contract, but a distributable macOS artifact is complete only after the script passes on the matching macOS architecture. A CI workflow may run those two native builds and upload the artifacts without storing signing material in source.

## Package-import ledger repository

- `app/package_import_repository.py` defines immutable receipt/log records and
  the SQLite import-ledger adapter. Receipt claiming uses both package ID and
  envelope SHA-256 uniqueness and must happen in the caller's final SQLite
  transaction so candidate creation and idempotency succeed or roll back
  together. Standalone failure and duplicate logs use the adapter's own short
  transaction.
- `app/postgres_repository.py` applies ordered migrations under the existing
  transaction-scoped advisory lock. Migration 2 creates PostgreSQL receipt and
  attempt-log tables with equivalent constraints. Its adapter owns connections
  and transactions; provider errors are reduced to stable repository codes.
  This slice stores no candidate values and does not change central readiness.
- Repository input records normalize basenames and bound text before either SQL
  dialect sees them. Log reads are limited to 1-500 rows and newest-first.
- In the active SQLite route, the successful `imported` attempt is appended in
  the same transaction as the receipt and imported candidates. Parse,
  validation, hold and duplicate failures are logged in independent bounded
  transactions because no candidate transaction is committed for those paths.

## Reviewed-package clinical import repository

- `app/reviewed_import_repository.py` owns immutable import commands/results
  and the SQLite adapter. Its external interface is `import_package(command)`
  plus `list_imported_values(import_id)`; callers do not manage SQL or audit
  ordering.
- Each record contains only centre-scoped pseudonymous subject/event/field
  references, the originating source SHA-256, final reviewed value/unit,
  review timestamp and a deterministic quality assessment prepared from the
  active versioned rules. Mutable mappings are canonicalized before storage.
- One transaction covers receipt claim, source metadata, candidate rows,
  quality rows, hash-chained audit rows and the terminal imported/duplicate
  attempt. PostgreSQL takes a transaction-scoped audit advisory lock before
  reading the chain tail. A partial unique index protects active candidate
  identity/value/unit equivalence across concurrent package imports.
- The encrypted envelope remains filesystem/object-storage material outside
  the repository. The local route writes it to a new source-specific path and
  removes that new file when repository import does not succeed; package bytes
  never enter PostgreSQL.
- `app/postgres_reviewed_import_repository.py` is optional-central code and is
  not imported by Centre Lite. Migration 3 creates source metadata, candidates,
  audit events and quality findings required only by this vertical slice.
  Missing central reads and managed identity keep readiness false.

## Confirmed-data read repository

- `app/confirmed_data_repository.py` owns `ConfirmedDataScope`, the immutable
  `ConfirmedDataRow` projection, the repository protocol and the SQLite
  adapter. A scope always states whether all centres are allowed; a site caller
  passes one exact centre code rather than relying on SQL assembled in an HTTP
  handler.
- `app/postgres_confirmed_data_repository.py` is optional-central code. It uses
  the same projection and filtering contract without being imported by Centre
  Lite or the current HTTP composition root.
- Both adapters select only `human_confirmed` candidates, use the newest
  quality assessment per candidate and order by stable insertion sequence.
  PostgreSQL cannot claim an Authority submission because migration 3 has no
  transfer domain, so it returns `authority_submitted=false`.
- `reviewed_recognition_export_payload()` remains responsible only for role to
  repository-scope translation, dictionary/header projection and workbook
  grouping. It no longer owns clinical-row SQL.
- PostgreSQL migration 4 adds a partial confirmed-read index covering centre,
  visit, subject, creation time and sequence. It adds no HTTP route and does
  not change `clinical_data_ready=false`. SQLite creates the equivalent partial
  scope index during its existing idempotent initialization path.

## Verified-principal authorization contract

- `app/institutional_identity.py` is a pure post-verification authorization
  boundary. It does not parse JWT/SAML, perform discovery, fetch keys, expose a
  callback or read provider secrets.
- `VerifiedInstitutionalPrincipal` is constructed only after a future adapter
  verifies the provider assertion. It carries provider ID, opaque subject,
  username, timezone-aware authentication time and normalized MFA status; it
  deliberately has no application role or centre field. Its class name is a
  legacy compatibility name and does not assert hospital affiliation.
- `StudyMembership` is application-controlled authorization. It matches a
  configured provider alias and namespaced pseudonymous principal ID, has one
  supported study role, optional exact centre, active flag and timezone-aware
  effective interval. The raw provider subject remains transient in the
  verified principal and is never stored by the membership repository.
- `authorize_institutional_principal()` requires MFA, permits five minutes of
  positive clock skew, limits authentication age to eight hours, checks exact
  membership identity/effectivity and enforces role/centre invariants. It
  returns `InstitutionalUser`, whose ID is a namespaced SHA-256 of provider ID
  and subject; the raw subject is not returned.
- Failures are `InstitutionalIdentityError` instances whose string value is one
  closed error code. No provider response, assertion, username or raw identity
  value is included.
- The module is not wired into `create_auth_module()` until a specific approved
  OIDC/SAML adapter and membership repository are selected and contract-tested.
  Local SQLite login and Centre Lite remain unchanged; central startup remains
  fail-closed.
- `evaluate_production_readiness()` receives a runtime capability boolean from
  composition. The current application and operator script pass `False`
  because no assertion-verifying adapter exists. The identity gate requires
  that capability plus approved configuration and unexpired evidence.

## PostgreSQL study-membership persistence

- `institutional_principal_id()` is the single derivation function for the
  namespaced SHA-256 principal identifier. Authorization and persistence use
  the same value; neither exposes or stores the raw subject.
- `PostgresStudyMembershipRepository` owns `grant`, `find_active`,
  `deactivate` and `verify_audit_chain`. It is an internal adapter and is not
  imported by Centre Lite or the current HTTP composition root.
- Migration 5 creates `study_memberships` with database checks for role/centre
  shape, timezone-aware effective intervals and complete deactivation
  metadata. A partial unique index enforces one active row per principal ID.
- Grant and deactivation take the same PostgreSQL transaction advisory lock as
  reviewed-package audit writers. They append `study_membership_granted` or
  `study_membership_deactivated` to the shared `audit_events` chain before
  commit. Shared audit timestamps are canonicalized to UTC before hashing and
  insertion so connection timezone settings cannot change verification. Audit
  detail contains the membership ID, provider alias, role, centre and lifecycle
  reason only.
- An already inactive membership is returned unchanged and does not create a
  second event. Unknown membership IDs, duplicate active grants and invalid
  input return stable repository error codes.
- This schema slice leaves `clinical_data_ready=false`. A qualified provider
  adapter, HTTP session composition, remaining repositories and operational
  evidence are still required before central startup can pass.

## PostgreSQL institutional-session persistence

- `PostgresInstitutionalSessionRepository` exposes only `create_session`,
  `resolve_session`, `revoke_session` and `verify_audit_chain`. It receives an
  already verified principal and does not parse or retain an OIDC/SAML token.
- Creation locks the matching active Study Membership for the transaction,
  reuses `authorize_institutional_principal()` and inserts a session plus
  `institutional_session_created` audit event atomically. A concurrent
  membership deactivation cannot create an authorization race.
- Bearer tokens use standard-library cryptographic randomness. Only a lowercase
  SHA-256 digest is persisted and indexed; the returned session object excludes
  the plaintext token from its representation.
- Effective expiry is `min(issued + 8h, provider authentication + 8h,
  membership expiry)`. Resolution joins the membership and fails closed for an
  inactive, not-yet-effective or expired membership even when the session row
  itself has not expired.
- First revocation writes `revoked_at` and an
  `institutional_session_revoked` event atomically. Repeated revocation is a
  successful no-op and does not extend the audit chain.
- Migration 6 adds session metadata only. Centre Lite and local SQLite login are
  unchanged; no institutional callback or central HTTP composition is added.

## Project-owned OIDC verified-claim boundary

- `app/project_oidc_identity.py` is a pure post-verification adapter. Its public
  seam is `principal_from_verified_oidc_claims(policy, claims)`; callers must
  supply an ID-token claim mapping already verified by an OIDC library for
  signature, discovery/JWKS, state, nonce, expiry and token integrity.
- `ProjectOidcPolicy` contains only non-secret configuration: provider alias,
  exact HTTPS issuer, confidential client identifier, required MFA ACR and the
  exact username claim name. It never contains a client secret.
- The adapter rechecks issuer and audience, requires the configured ACR,
  converts OIDC `auth_time` NumericDate to UTC and constructs the existing
  post-verification principal without role or centre fields. A multi-valued
  audience is accepted only when it contains the configured client and `azp`
  equals that client.
- Provider `groups`, `realm_access`, `resource_access`, role, centre and email
  claims are ignored. Study Membership remains the sole authorization source.
- `ProjectOidcIdentityError` exposes only closed error codes. Structural
  principal errors are translated to a bounded OIDC claim error rather than
  leaking values.
- The name `VerifiedInstitutionalPrincipal` remains a legacy internal type for
  compatibility. It represents a verified provider principal and does not
  assert hospital affiliation when produced by this adapter.
- This module does not add Authlib or an HTTP callback. The next integration
  slice must use Authorization Code Flow, exact redirect URIs, state/nonce,
  short provider-token lifetime and an out-of-URL Companion session exchange.
  Central HTTP and `identity_provider_ready` remain fail-closed.

## Project OIDC browser authentication contract

- `app/api/project_oidc_authentication.py` owns the three-route HTTP boundary
  and an Authlib-backed external client adapter. Authlib is isolated in the
  optional `central` dependency group; Centre Lite does not import it.
- The registered confidential client uses the fixed issuer discovery document,
  `openid` scope, Authorization Code Flow and PKCE `S256`. The login route
  passes a fixed configured callback URI, a generated nonce, the configured MFA
  ACR and an eight-hour `max_age`; it never derives redirects from the request
  Host header.
- Starlette `SessionMiddleware` is a composition prerequisite. Production must
  supply a managed random signing secret, `https_only=True`, `same_site=lax`,
  `HttpOnly` and a short session age. The router fails closed when middleware
  state is absent.
- Authlib performs discovery/JWKS, state/nonce and ID-token validation. The
  adapter returns only the validated `userinfo` claim mapping; access, refresh
  and ID tokens are not returned to the router or persisted.
- `VerifiedPrincipalLink` is a transient/persistable projection containing the
  provider alias, pseudonymous Principal ID, username, authentication time and
  MFA result. It contains no raw provider subject and cannot carry role or
  centre. Existing principal authorization delegates to the same link-based
  authorization function.
- PostgreSQL migration 7 adds `oidc_login_exchanges`. Exchange and browser
  binding values use independent 256-bit randomness; only SHA-256 digests are
  stored. Each row expires after two minutes and is consumed once under
  `SELECT ... FOR UPDATE`.
- Exchange consumption returns the verified-principal link, after which
  `PostgresInstitutionalSessionRepository.create_session_from_link()` applies
  existing MFA age, membership and role/centre checks. A consumed exchange is
  not restored if session issuance fails; the user must repeat OIDC login.
- The callback returns a 303 redirect with a Login Exchange code only. The
  exchange POST returns the existing Companion bearer response once and clears
  the browser binding. All authentication responses are `no-store`.
- This module is contract-tested independently and is not included by
  `create_app()`. Therefore it does not yet make `identity_provider_ready` true
  or enable `COMPANION_DEPLOYMENT_PROFILE=central`.

## Project session HTTP authentication contract

- `app/api/project_session_authentication.py` owns the future-central bearer
  resolver and logout endpoint. It depends only on the public
  `resolve_session()` and `revoke_session()` repository operations and reuses
  the existing `AuthModule`/`UserContext` downstream boundary.
- The bearer parser accepts the existing `Bearer <token>` shape. The
  PostgreSQL repository remains authoritative for token format, digest lookup,
  expiry, revocation and current Study Membership effectivity.
- Successful resolution projects only pseudonymous user ID, bounded username,
  role and centre into `UserContext`. No session token or database object is
  attached to the user context.
- Logout resolves the session and then calls the repository's idempotent
  revocation operation. It returns `204`; later use of that bearer receives the
  same `invalid_or_expired_token` response as other invalid sessions.
- Repository exceptions are reduced to `project_session_unavailable` with
  status `503`. Authentication failures do not distinguish missing database
  rows, expiry, revocation or inactive membership.
- The module is contract-tested with the repository interface and is not
  included by `create_app()`. It introduces no schema or dependency and does
  not enable the central deployment profile.

## First Central Data Manager membership bootstrap

- `institutional_principal_id_from_subject()` is the only pre-login derivation
  path. It applies the same provider/subject validation and namespaced SHA-256
  derivation as `institutional_principal_id()` without constructing a falsely
  verified principal. Existing authenticated derivation delegates to it.
- `PostgresStudyMembershipRepository.bootstrap_first_central_data_manager()`
  receives only provider alias, Principal ID, operator and server-side times.
  It never receives the raw OIDC subject.
- Under the shared transaction advisory audit lock, bootstrap permits a grant
  only when no active membership and no institutional-session row exists.
  Historical rows are acceptable only when they are inactive Central Data
  Manager bootstrap grants with corresponding
  `study_membership_bootstrap_rolled_back` events. Generic deactivation and all
  non-bootstrap membership history close the path. This permits only the
  dedicated correction workflow and never reopens bootstrap after any session
  has existed.
- The inserted `StudyMembership` fixes role to `central_data_manager`, centre
  to `None`, validity start to the grant time and active to true. The normal
  `study_membership_granted` audit detail adds `bootstrap: true`.
- `rollback_unused_central_data_manager_bootstrap()` locks the target row,
  verifies the bootstrap audit marker and rejects recovery when any
  institutional session exists. It then writes complete deactivation metadata
  and one `study_membership_bootstrap_rolled_back` audit event. Repeated
  rollback is a no-op only when that dedicated event already exists; a generic
  deactivation is not promoted into a bootstrap rollback.
- `scripts/bootstrap_central_membership.py` reads at most 8 KiB of strict JSON
  from stdin. `COMPANION_POSTGRES_DSN`, `COMPANION_ENV` and
  `COMPANION_OIDC_PROVIDER_ID` are environment-only inputs. Error output is one
  bounded JSON code and never includes request or connection values.
- The bootstrap input's `subject_id` must be the exact `sub` emitted for the
  qualified OIDC client. Keycloak Admin REST identity, email, username and
  group values are not accepted substitutes. The mapping is an operational
  qualification gate, not an application inference. The command does not know
  issuer, client ID or mapper configuration and cannot verify that gate.
- `operator_id` is a caller-supplied audit label. The fixed confirmation limits
  accidental execution but is neither operator authentication nor two-person
  approval; witness and subject-mapping evidence remain in the approved
  external operations record.
- This slice adds no migration. The operator command still invokes the normal
  repository prepare step and can apply previously unapplied versioned
  migrations; it must run under the same backup and change-control procedure.
  Central HTTP stays unmounted and Centre Lite is unchanged. The emergency
  containment action below does not supply routine membership administration
  or replacement authority, which remain production blockers.

## Emergency deactivation of a used bootstrap membership

- `PostgresStudyMembershipRepository.emergency_deactivate_bootstrap_central_data_manager()`
  validates actor, reason, incident reference, membership ID and server time
  before opening PostgreSQL.
- Under `lock_audit_chain()`, it row-locks the target and requires centre
  `None`, role `central_data_manager`, active state and the original
  `study_membership_granted` audit detail `bootstrap=true`. It does not accept a
  normal CDM or any site membership.
- The same transaction changes the membership to inactive and appends
  `study_membership_emergency_deactivated`. Existing session rows remain
  immutable operational evidence; `resolve_session()` already joins the active
  membership, so access fails immediately after the deactivation commit.
- The emergency event is distinct from
  `study_membership_bootstrap_rolled_back`. It never restores bootstrap
  eligibility, even when no session row exists.
- `scripts/bootstrap_central_membership.py` reuses its strict 8 KiB JSON parser,
  environment-owned PostgreSQL configuration, bounded error allowlist and
  redacted output for the new action. No schema or dependency is added; the
  normal repository prepare/change-control caveat remains.
- The command is containment only. It does not provision a replacement CDM,
  revoke or delete session rows, mount an HTTP route or claim dual approval.

## Compact authenticated command deck

- `app/static/index.html` groups `#edc-status` and `#production-status` inside
  one native `details.session-health` disclosure. The existing IDs and live
  regions remain the JavaScript update targets; the disclosure is presentation
  only and closed by default.
- `#identity`, the Kimi control, export, data exchange and logout remain visible
  in the session command surface. No diagnostic text is deleted, truncated in
  the DOM or promoted into an authorization decision.
- Desktop compaction changes only spacing and intrinsic dimensions. Buttons,
  links, summaries and form controls retain a minimum 44 CSS pixel target.
- At `max-width: 560px`, session actions use a two-column grid with the Kimi
  control spanning both columns. The role-aware navigation becomes a bounded
  single-row horizontal scroller with focus-visible links and scroll snapping;
  only this component scrolls horizontally, never the page.
- The workflow stepper stays in one four-column row on phones. Each item stacks
  its number above its label and may wrap internally without clipping.
- The research run strip keeps centre scope and permission text visible. Its
  facts use two columns on phones, with the permission boundary spanning the
  row. Existing role/Lite projection logic and section anchors are unchanged.
- No JavaScript, API, schema, remote asset, font, framework or dependency is
  added by this presentation slice.

## Windows host preflight

- `scripts/portable_host_preflight.ps1` is the single host-capability boundary. It uses locale-independent CIM/optional-feature state where available, captures Docker stderr instead of exposing the raw named-pipe response, and returns a stable diagnostic code.
- Hardware readiness is satisfied when either firmware virtualization is reported by `Win32_Processor` or a Windows hypervisor is already present. SLAT is required for the WSL2 backend. Virtual machines with unavailable virtualization receive `EDC-HOST-NESTED-VIRTUALIZATION-REQUIRED`; physical machines receive `EDC-HOST-VIRTUALIZATION-DISABLED`.
- Other fail-closed codes cover unsupported Windows Server, missing Docker Desktop, disabled Virtual Machine Platform, unavailable WSL and a non-ready Docker engine. Unknown optional-feature telemetry does not create a false block when the Docker engine is demonstrably ready.
- Each failed preflight writes `.runtime/portable-host-diagnostic.json` without Docker raw errors, credentials, environment variables, paths outside the bundle or hardware serial identifiers.
- If every host prerequisite passes except engine readiness, the launcher invokes the supported `docker desktop start --detach` command when available, otherwise starts Docker Desktop from its documented per-user or all-users installation directory. It never restarts an already-running Desktop process. The launcher polls the sanitized Docker probe for up to 180 seconds and leaves the Desktop UI visible so the recipient can complete Docker's first-run agreement.
- Auto-start timeout or launch failure retains `EDC-HOST-DOCKER-ENGINE-NOT-READY`; downstream image and Compose operations remain blocked. The diagnostic records only a bounded start method/category and never captures command output or an executable path.
- Expected non-zero probes and Docker commands that emit normal progress on stderr use a redirected native-process boundary with local non-terminating error semantics and inspect only the exit code. This avoids Windows PowerShell 5.1 converting Docker stderr into a terminating `NativeCommandError` when an offline image is intentionally absent before `docker load`, Compose reports successful progress, or PostgreSQL is still becoming ready.
- `Repair-Docker-Prerequisites.cmd` is a separate user-triggered elevated action. It enables only Microsoft's WSL and Virtual Machine Platform features, sets `hypervisorlaunchtype=auto`, updates WSL when available and requires a reboot. It cannot enable BIOS/UEFI virtualization or host-level nested virtualization.

## Verification

- Unit tests for rule parsing/evaluation, CSV parsing and scope locks.
- API tests for role isolation, issue state transitions, transfer-hold gates, read-back match/mismatch/unsupported, account lifecycle, dashboard and snapshots.
- Regression suite for existing OCR/Kimi and LibreClinica paths.
- Real CSV fixture using synthetic data.
- Browser checks at desktop and mobile viewport for all new panels and primary actions.

## Public showcase repository surface

- `README.md` is the public landing page and links to versioned synthetic
  screenshots, `docs/assets/architecture.svg`, the rendered demo and the
  existing detailed design/operations documents. It must not become a second
  API contract or production runbook.
- This showcase tranche originally used a source-available evaluation grant.
  ADR 0022 and the AGPL release surface below supersede that license decision;
  the production clinical boundary remains unchanged.
- `docs/adr/0021-public-showcase-repository.md` supersedes only ADR 0008's
  private-remote default. The canonical architecture, Authority EDC boundary,
  central fail-closed gates and synthetic-data restrictions are unchanged.
- `scripts/check_public_release.ps1` uses Git and PowerShell only. It inspects
  tracked paths and text without echoing matched values, verifies required
  showcase files and rejects common credential/private-key signatures. The
  source-quality workflow runs it before tests.
- `showcase/demo-video/` contains the small Remotion source project. Its public
  assets are fixed synthetic screenshots; rendering has no dependency on the
  live application, Kimi, LibreClinica, a database or network service.
- `docs/demo/clin-data-relay-demo.mp4` is 1280x720, 30 fps and approximately
  120 seconds. The repository copy remains below 10 MiB; larger future media
  belongs in a GitHub Release rather than normal Git history.
- The architecture SVG is hand-authored repository content with system fonts,
  descriptive text and no remote assets. README supplies a text alternative
  through its architecture explanation.
- No HTTP endpoint, request/response schema, authentication rule, database
  migration, clinical value, model call or transfer behavior changes in this
  release-publication slice.

## AGPL open-source release surface

- `LICENSE` is the verbatim GNU AGPL version 3 text. `pyproject.toml`, the
  Remotion package metadata, README badges and `CITATION.cff` use the SPDX
  identifier `AGPL-3.0-only` as the single machine-readable license identity.
- Safety notices remain non-license documentation. They describe validation,
  privacy, regulatory and deployment responsibilities without attempting to
  prohibit fields of use through an additional license term.
- `packaging/SOURCE-CODE.txt` points recipients to the public repository and
  the Git tag matching the application version. Windows full/Lite and macOS
  Lite builders copy it together with the root `LICENSE`; existing third-party
  notices remain unchanged.
- The web workbench exposes a small same-origin-safe footer link to the public
  source and AGPL notice. It carries no state and changes no authorization or
  API behavior.
- `scripts/check_public_release.ps1` requires the Chinese README, citation,
  evaluation protocol, AI-development disclosure and AGPL markers. It still
  scans tracked paths and complete Git patch history without printing values.
- The POSIX quick start is documentation-only and uses the same `uv`, Uvicorn,
  environment variables and localhost binding as the PowerShell example.
- `docs/evaluation/benchmark-protocol-v0.1.md` defines the evaluation contract;
  it contains no results. A provider-generalization refactor is deferred until
  the frozen benchmark can detect a regression or benefit.
- `scripts/prepare_tessdata.py` is a standard-library build prerequisite shared
  by Windows and macOS Lite builders. It downloads only `eng` and `chi_sim`
  from one immutable `tessdata_fast` commit, enforces a 16 MiB per-file bound,
  validates pinned SHA-256 values before atomic replacement and stores the
  result under ignored `vendor/` state. A valid cache makes repeat builds
  offline; a network or digest failure is fail-closed.
- Source-only tag `v0.2.0` records the clean-build discovery that this
  prerequisite was absent. The corrected formal binary release is version
  `0.2.1`. Source archives come from GitHub; binary assets are uploaded only
  after their existing synthetic black-box verification succeeds and a
  SHA-256 sidecar is generated.
- Portable builders discover third-party license files from installed
  `*.dist-info` directories instead of embedding dependency-version paths.
  Missing license text remains a hard build failure.
- `portable_synthetic` is a launcher-controlled, loopback-only evaluation
  environment. Without a centre profile it permits the same legacy synthetic
  accounts as `test`/`development`, immediately upgrading the successful
  account to scrypt. A centre profile disables that path and uses the existing
  first-run setup credential; `production` remains denied.

## Executable benchmark artifact contract

- `app/benchmark_evaluation.py` is a pure standard-library scoring module. It
  owns schema validation, frozen normalization, report-level scoring,
  deterministic clustered bootstrap intervals, paired arm comparisons and the
  protocol error taxonomy. It imports no OCR, Kimi, FastAPI or persistence
  module and performs no network or database operation.
- Gold JSONL uses `clin-data-relay-gold-v1`; prediction JSONL uses
  `clin-data-relay-prediction-v1`. One gold row identifies one report and visit.
  One prediction row identifies one report, visit and arm. Field identity is
  the stable uppercase `field_code`; repeated identities within a row are
  rejected instead of silently resolved.
- Gold rows state whether the privacy gate should `allow` or `block`; blocked
  rows contain no gold fields. Predictions state the observed decision and may
  contain no fields when blocked. False negatives are report-clustered and use
  the dedicated direct-identifier taxonomy category. Optional review outcomes
  record only edit/reject counts and elapsed milliseconds; absent observations
  remain `null` instead of being treated as zero.
- `benchmark-normalization-v1` trims text, canonicalizes decimal commas and
  comparison symbols, compares numeric values through `Decimal`, and compares
  units case-insensitively after whitespace normalization. It performs no unit
  inference or conversion.
- Content metrics use every gold field in the supplied set. Provider timeout or
  error remains an availability outcome; it is not silently dropped. A
  `fallback` row may contain the local predictions actually shown to reviewers.
- Bootstrap resampling draws reports with replacement and retains every field
  from a selected report. The random seed and replicate count are written into
  the report. Undefined zero-denominator bootstrap draws are omitted for that
  metric and a wholly inapplicable interval is `null`. Paired deltas resample
  the shared report IDs and never treat fields as independent clusters.
- `scripts/evaluate_extraction_benchmark.py` accepts one gold file and one or
  more `ARM=PATH` prediction files. It validates exact arm agreement, hashes
  every input, and atomically publishes a previously absent output directory
  containing `summary.json`, `errors.csv` and `manifest.json`.
- Error rows contain report/visit/arm/field identifiers and taxonomy labels but
  no expected or predicted value, evidence text, source path, OCR text or raw
  provider error. The summary contains aggregate counts, rates and operational
  totals only.
- `benchmarks/synthetic-v0.1/examples` is a metric-engine demonstration, not the
  planned 30-report development set or locked 100-report test set. Its manifest
  states `DEMONSTRATION_ONLY` and no README or release may present its scores as
  extractor performance.

## OpenAI-compatible model provider boundary

- `app/model_provider.py` owns `ModelProviderSettings`,
  `OpenAICompatibleClient`, structured candidate parsing, outbound request
  validation and credential-file writing. `app/kimi.py` is a compatibility
  facade exporting the historical Kimi class/error names as aliases.
- Generic environment variables are `MODEL_PROVIDER`, `MODEL_ENABLED`,
  `MODEL_API_KEY`, `MODEL_API_KEY_FILE`, `MODEL_BASE_URL`, `MODEL_NAME`,
  `MODEL_ALLOWED_BASE_URLS`, `MODEL_API_KEY_REQUIRED`, `MODEL_TIMEOUT_SECONDS`,
  `MODEL_MAX_RETRIES` and `MODEL_REASONING_EFFORT`. Each absent generic value
  falls back to the equivalent existing `KIMI_*` value where one exists.
- Provider aliases match `[a-z][a-z0-9._-]{1,63}`. Base URLs have no query,
  fragment, userinfo or non-root path beyond the API prefix. Kimi receives the
  two built-in Moonshot v1 URLs. A non-Kimi URL is ready only when it exactly
  matches one entry in `MODEL_ALLOWED_BASE_URLS` after trailing-slash removal.
- Allowed remote URLs require HTTPS. HTTP is accepted only for `localhost`,
  `127.0.0.1` or `::1`. `MODEL_API_KEY_REQUIRED=false` is valid only for such a
  loopback URL; otherwise readiness fails closed.
- `reasoning_effort` is included only when configured. Its Kimi default remains
  `low`; custom providers receive no speculative parameter by default.
- Existing `/api/settings/kimi` routes remain for package compatibility. Their
  redacted response adds `provider`; health adds `model_provider`; configuration
  audit detail contains provider and model only. No browser request can change
  provider transport configuration.
