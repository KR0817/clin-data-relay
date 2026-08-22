# Clinical EDC Companion Operations Release PRD

**Status:** implementation baseline  
**Date:** 2026-08-11  
**Environment:** synthetic localhost qualification only

## 2026-08-22 PostgreSQL repository bootstrap

The first central-database slice establishes a real PostgreSQL connection and
migration seam without moving clinical records or enabling the central web
profile. It is an infrastructure tracer bullet, not a production repository.

Acceptance criteria:

- PostgreSQL support is an optional dependency and does not change the Centre
  Lite installation or SQLite behavior.
- One module owns connection-policy validation, transactional migration
  locking, the migration ledger and a redacted capability result.
- Non-local environments require hostname-verifying TLS. Development or test
  connections may disable TLS only for a loopback or local Unix-socket host.
- Repeated preparation is idempotent and rejects a database schema newer than
  the application understands.
- Errors and status never expose the DSN, password, host, database user or raw
  provider exception.
- A real PostgreSQL 16 service runs the public module interface in CI.
- `COMPANION_DEPLOYMENT_PROFILE=central` remains fail-closed because no
  clinical-data repository adapter or institutional identity exists yet.

## 2026-08-22 production-software architecture tranche 1

The product will keep one codebase but support two explicit deployment shapes:
a centre-bound Lite desktop application for local intake and an independently
qualified central web application for multi-centre coordination. Lite retains
SQLite and encrypted-package exchange. Central must use PostgreSQL, managed
identity and server operations; it must never fall back to a shared SQLite file.

This tranche prepares the codebase without changing clinical behavior. Browser
delivery and authentication move behind small modules, while the existing HTTP
contracts, centre scoping, review policy, audit meaning and local persistence
remain unchanged. It is a modular-monolith refactor, not a microservice split.

Acceptance criteria:

- The homepage, CSS, JavaScript and allow-listed workbench images are registered
  through one static-delivery module and retain their current paths, media types
  and no-store headers.
- Login and bearer-session resolution are registered through one authentication
  module. Legacy-demo upgrade remains development/test-only and still records a
  chained audit event.
- Existing routes consume the exported authenticated-user dependency; no route
  reaches into authentication session SQL directly.
- `central` remains fail-closed. This tranche adds no PostgreSQL package and
  makes no claim of concurrent central readiness.
- The full regression suite, JavaScript syntax check, Python compilation and
  local startup check pass with unchanged response contracts.
- The project uses a proprietary root license and the repository remains
  private. Source access or distribution requires the owner's separate written
  authorization and must not be presented as an open-source release.

## 2026-08-22 source repository baseline

- The canonical development root is `C:\ClinData Relay`.
- The canonical source repository contains code, tests, configuration,
  documentation and credential-free build definitions only.
- Runtime databases, uploaded reports, de-identified derivatives, API keys,
  credentials, backups, virtual environments, generated distributions and
  bundled third-party binaries are local artifacts and must not enter Git.
- The remote remains private under the proprietary license. Any future public
  source release requires an explicit owner-approved relicensing decision and
  a new public-release review.
- The first baseline tag matches the application development version and is
  created only after a clean-root dependency install and complete test run.
- Every push to `main` and every pull request must recreate the locked Python
  environment and pass Python compilation, workbench JavaScript syntax and the
  full automated test suite before the change is considered mergeable.

## 2026-08-22 Kimi settings module extraction

The centre-local Kimi configuration flow is the next modular-monolith slice.
The application composition root must register one router that owns eligibility,
key validation, credential-file selection, atomic write, client reload, redacted
status and audit behavior.

Acceptance criteria:

- Existing `GET|PUT /api/settings/kimi` paths, payloads, status codes and role
  restrictions remain unchanged.
- Only the bound Lite centre investigator can configure the key.
- The key never enters SQLite, audit details, logs or any HTTP response.
- Health and settings responses use the same redacted Kimi status projection.
- `app/main.py` no longer owns the Kimi key payload or settings route bodies.

## 2026-08-22 Dreamina-assisted workbench visual assets

The workbench may use a small set of development-time Dreamina illustrations
to improve role recognition and empty-state comprehension. These illustrations
are decorative support for the established central, site and review layouts;
they never encode a clinical status, permission or action. The shipped
application remains offline-capable and does not call Dreamina at runtime.

Acceptance criteria:

- Generate three abstract assets: central coordination context, site report
  intake context and review-empty context. They contain no person, patient,
  readable text, number, hospital mark, clinical image or direct identifier.
- Preserve the original prompt, provider task metadata, SHA-256 and human-review
  result in a development-only asset ledger. No credential or provider account
  identifier is stored in the repository or distributed bundle.
- Ship only compressed, same-origin WebP derivatives. Each image is decorative
  (`alt=""`, `aria-hidden="true"`) with explicit intrinsic dimensions so it
  cannot replace a label or create layout shift.
- Central and site sessions receive the corresponding contextual artwork;
  oversight uses the neutral central artwork. The candidate-review illustration
  appears only when the candidate collection is empty.
- Text contrast, keyboard flow, role projection, API behavior and server-side
  authorization remain unchanged. Validate at 1440, 1024, 768 and 375 CSS
  pixels with no horizontal overflow or obscured primary action.

## 2026-08-18 role-aware central and site workspaces

The authenticated workbench will project one shared application into three
task-oriented views: central coordination, site data capture and read-only
oversight. This is an information-architecture change, not a second frontend.
Role and centre authorization continue to be enforced by the existing APIs.

The visual signature is a compact research run strip directly below the
session controls. It states the current workspace, centre scope, immediate
operational focus and permission boundary before the user reaches any action.
Central users land on cross-centre operations; site users land on report intake;
read-only users land on oversight. Navigation labels and visible destinations
follow the same role context without duplicating clinical workflow components.

Acceptance criteria:

- `central_data_manager` and `principal_investigator` receive a central
  coordination context; `site_investigator` receives a centre-bound capture
  context; monitor/auditor sessions receive an explicitly read-only context.
- The current centre scope and a plain-language role name are visible above the
  first workflow action. Raw role codes are not the primary user-facing label.
- Central navigation prioritizes operations, review, confirmed data and the
  dictionary where authorized. Site navigation prioritizes intake, review,
  confirmed data and centre operations. Read-only navigation never implies a
  write action.
- The same HTML sections, DOM IDs, JavaScript handlers and HTTP contracts are
  reused. Presentation hiding never substitutes for server authorization.
- Lite mode continues to hide Authority-only operations and dictionary
  surfaces while retaining the centre identity strip, intake, review and
  reviewed-data export.
- Desktop and mobile checks cover central, site and read-only projections,
  keyboard focus, long centre codes, long status text and zero page-level
  horizontal overflow.

## 2026-08-18 workbench visual redesign

The workbench will use a calm, light clinical-operations visual system with a
navy command header, white data surfaces, blue primary actions and semantic
green/amber/red states. The redesign changes presentation only: upload,
de-identification, recognition, review, freeze, submission, audit and export
contracts remain unchanged.

Acceptance criteria:

- The first screen exposes the current identity, integration state, primary
  workflow navigation and next data-capture action without horizontal clipping.
- Upload, review, confirmed data and operations areas have visibly different
  hierarchy; destructive, warning and successful states are never identified
  by color alone.
- The page has no horizontal overflow at 375, 768, 1024 or 1440 CSS pixels,
  including long operational status strings and populated action toolbars.
- All interactive targets remain at least 44 CSS pixels, keyboard focus remains
  visible, and reduced-motion preferences disable non-essential transitions.
- The offline application uses system fonts, inline SVG and audited same-origin
  WebP illustrations only. It does not add a web-font request, UI framework,
  animation runtime or runtime third-party request.
- Existing API, authorization, review-gate and audit tests continue to pass.

## 2026-08-14 Kimi default-on distribution tranche

The distributed companion enables the Kimi workflow by default so a recipient
does not need to change a product setting before recognition. This is a
configuration default, not permission to send data automatically: outbound
requests remain fail-closed until the recipient enters a local Kimi key, and
the existing de-identification, field-dictionary, evidence and human-review
gates remain mandatory. An explicit `KIMI_ENABLED=false` opt-out continues to
support local-only operation.

Acceptance criteria:

- Missing Kimi credentials report `kimi_integration=key_required` and never
  cause a request containing a blank or inherited key to leave the host.
- A configured and allow-listed Kimi K3 client reports `kimi_integration=ready`.
- The first-run Windows/macOS configuration helpers store the key only in the
  recipient-local runtime directory; no key is bundled or written to logs.
- Lite and full packages retain their existing fail-closed authority and
  production-readiness gates.

## 2026-08-17 review-gate and audit-integrity hardening

The 2026-08-14 accept-all behavior is superseded. A single click is not
sufficient review for an OCR/Kimi conflict or a value found only by Kimi.
Default bulk review is therefore limited to `agreement`, `local_only` and
`local_fallback`. `conflict` and `kimi_only` remain pending for item-level
review. A central data manager may use an explicit exceptional override only
with a non-empty written reason; quality `BLOCK`, unknown provenance and
unknown quality states remain ineligible under every mode.

Conflict review must not silently prefer the model value. The reviewer must
choose the local value, the Kimi value, or enter a manual value. Kimi-only
acceptance requires an explicit evidence acknowledgement tied to the confirmed
de-identified derivative.

Acceptance criteria:

- The 2026-08-14 black-box composition of six `agreement` plus eleven
  `kimi_only` candidates accepts six by default and leaves eleven pending.
- The override path is central-data-manager-only and rejects an empty reason.
- Each confirmed event records `review_mode`, a request/batch ID, the policy
  version, the normalized policy summary and the selected value source.
- Quality `BLOCK`, transfer holds, cross-centre records and non-pending records
  remain fail-closed and are reported with stable skip reasons.
- Audit events are linked by SHA-256 over their immutable event payload. Chain
  verification is included in health/readiness and backup evidence; an anchor
  can be exported for storage outside the workstation. This is tamper-evident
  mitigation, not WORM storage.
- A representative de-identified report is sent through the configured Kimi
  path during black-box verification; the original identifiable image is never
  sent to Kimi.
- The local preview also masks clinical staff labels/signatures and collection,
  receipt and review timestamp lines before a derivative may be confirmed for
  Kimi transmission.

## 2026-08-14 centre package onboarding repair

Centre recipients must be able to finish the complete first-use workflow from
the local web page. After authenticated login, the fixed centre investigator
can enter or replace the recipient-local Kimi key; the server stores it only in
the package runtime directory, never returns it, and hot-reloads the Kimi client
without a restart. The patient report queue must become actionable as soon as
the recognition dictionary has loaded.

First-run account creation must stop before automatic login and display the
username and chosen password exactly once with explicit copy/download actions.
After the user confirms that the credential was saved, the browser may log in
and must clear its in-memory plaintext. A local command-line reset entry point
must support an already-initialised package whose password was lost; reset
revokes existing sessions and prints the replacement password once without
writing it to the archive, database, logs or configuration.

Acceptance criteria:

- A centre Lite user can save a bounded Kimi key in the authenticated web UI;
  the response and health payload contain status only, never the key.
- Saving the key atomically replaces the local credential, restricts its file
  permissions and changes `kimi_integration` to `ready` in the same process.
- Recognition-field loading re-renders the patient queue controls, so a valid
  patient code plus selected PDF/image can always be added after login.
- First-run credentials remain visible until the user explicitly copies,
  downloads or confirms storage; a browser reload cannot recover them.
- `Reset-Centre-Password.cmd` works only for a centre-profile package, revokes
  sessions and emits one fresh strong password to the local console.

### Centre-package runtime identity and review recovery

The centre package must never treat a different Companion instance on the same
localhost port as itself. A completed recognition task must retain the exact
candidate IDs it created so the two current-batch review actions survive page
reload, logout/login and image de-identification source replacement.

Acceptance criteria:

- A SITE_A Lite launcher accepts an existing service only when health reports
  `product_mode=lite` and the exact SITE_A centre code and username.
- If the preferred port contains the full product, another centre package or an
  unrelated service, the launcher starts the requested centre package on the
  next bounded free localhost port and opens that URL.
- A successful recognition-job item returns and persists its exact
  `candidate_ids`; no source-file heuristic is required by the browser.
- Reloading and logging back into a centre package restores the latest
  completed batch and enables each bulk action only when that group contains
  eligible pending candidates.
- Quality BLOCK candidates remain individual-review only.

## 2026-08-14 offline reviewed-package exchange

When a centre cannot reach the hospital EDC, the companion can exchange an
integrity-checked JSON package instead of pretending that LibreClinica is
available. Site investigators export only their human-confirmed,
pseudonymous values; a central data manager imports the package once, with
hash verification, CRF mapping validation and an audit event. The import is
marked `authority_submission=not_attempted` and remains a companion record
until an approved authority workflow is run.

Acceptance criteria:

- `POST /api/exports/reviewed-recognition-package.json` requires a passphrase
  and returns an encrypted package with no images, OCR evidence, direct
  identifiers or unconfirmed values.
- `POST /api/imports/reviewed-packages` is central-manager-only, processes
  multiple files independently, rejects hash tampering, mixed centres,
  unsupported fields and duplicate package hashes, and never calls
  LibreClinica.
- Imported values retain the originating source hash, review timestamp and
  package provenance while remaining visible in the ordinary role-scoped
  candidate and Excel views. Reviewer identity remains a pseudonym inside the
  package and is not exported as an email address.

## 2026-08-14 controlled centre-package operations

The centre exchange is extended from plain JSON to an encrypted transport
package. A site investigator supplies a package passphrase for a one-click
AES-256-GCM export. The central data manager can select several package files
and import them in one request; every file gets an independent SHA-256,
dictionary-version check, duplicate decision, audit row and failure detail.

Operational controls are explicit: the original source retention period is
configured through `COMPANION_ORIGINAL_RETENTION_DAYS` (default 30 days), an
expiry cleanup command deletes only physical original files after a dry run,
and the database backup command performs a temporary restore integrity check.
The app exposes BitLocker/FileVault status as a preflight check but does not
attempt privileged OS changes. Centre investigator accounts are generated with
unique centre codes; only the principal investigator and central data manager
roles can access the central cross-centre repository views.

Acceptance criteria:

- Plain reviewed packages are no longer accepted by the import endpoint.
- Batch import returns per-file `imported`, `duplicate` or `failed` results
  and persists a non-sensitive import log.
- Export packages contain ciphertext only; original images, OCR evidence and
  direct identifiers are rejected by the package schema before encryption.
- Retention cleanup is hash-preserving and reversible only from the verified
  database backup, while expired source bytes are no longer readable through
  the app.

## 2026-08-14 production-readiness evidence boundary

The health endpoint must not treat environment variables as proof of a
production control. A production evidence manifest, with bounded expiry and
an auditable evidence reference for each gate, is required alongside the
configuration. The manifest may contain approval metadata only; it must never
contain passwords, tokens, private keys or clinical values.

Acceptance criteria:

- `GET /api/health` reports every production gate, its current state and a
  stable blocking reason without exposing secrets.
- HTTPS, managed secrets, institution identity/MFA, data governance,
  validation, authority qualification, monitoring, incident response, SOP
  training and disaster recovery require both an explicit runtime condition
  and an unexpired evidence-manifest entry.
- A SQLite/local profile cannot pass the central repository gate; selecting
  `COMPANION_DEPLOYMENT_PROFILE=central` still fails closed until a qualified
  PostgreSQL repository adapter exists.
- `scripts/check_production_readiness.py` emits a machine-readable report and
  exits non-zero whenever any gate is blocked. It is a preflight, not a
  substitute for institutional approval or validation.

## 2026-08-12 implementation tranche

The next implementation tranche keeps the current single-process behavior while
making the deployment seam explicit. The browser will consume versioned static
assets from `/static`, and the launcher will report a validated runtime profile
(`lite` or `full`) before the workbench is used. This is an internal seam, not a
new clinical workflow: candidate review, de-identification, Kimi, transfer and
Excel rules remain unchanged.

Central multi-user deployment is a separate qualification target. It requires a
PostgreSQL-backed repository, managed identity, TLS and backup/restore evidence;
the local SQLite profile must not be silently treated as a network database.

Acceptance criteria for this tranche:

- `/static/css/app.css` is served with the same no-store policy as the page and
  preserves the responsive 44px interaction targets.
- `GET /api/health` reports the runtime profile and database backend without
  exposing paths, credentials or source identifiers.
- Lite remains Docker/LibreClinica-free; full remains the localhost sandbox
  profile. An unsupported central configuration fails closed with a diagnostic
  configuration error rather than starting against SQLite.
- Existing PDF/image recognition, human review, simulated transfer and reviewed
  Excel export tests remain green.

### Frontend static-module tranche

The workbench behavior moves out of the HTML document into a same-origin static
JavaScript module. This is an internal delivery seam: the current browser
workflow, endpoints, roles and review gates remain unchanged. The first module
is intentionally a single compatibility bundle; later slices may split its
API, intake, review, administration and transfer concerns after public seams
are covered by tests.

Acceptance criteria:

- The page references `/static/js/workbench.js` and contains no inline
  workbench script.
- The static module is served with the same no-store policy as the stylesheet,
  contains no credentials or API keys, and is included in packaged builds.
- The CSP no longer needs `script-src 'unsafe-inline'`.
- Existing desktop/mobile browser checks and the full API regression suite stay
  green without changing candidate or transfer behavior.

### Durable recognition-job tranche

Batch recognition must survive a browser refresh and isolate per-file failures.
The local profile therefore persists a small job ledger in SQLite while keeping
source files, candidate review and Authority submission semantics unchanged.
This is a local queue seam, not a claim of a qualified distributed worker.

Acceptance criteria:

- A write-capable user can create a bounded recognition job from already
  registered source files with a frozen subject/visit and field-scope snapshot.
- Job and item status (`queued`, `running`, `succeeded`, `failed`, `cancelled`)
  is queryable without exposing source paths or credentials.
- Site users can see only jobs for their centre; central data managers can see
  all jobs. Read-only roles cannot enqueue, cancel or retry.
- Cancellation and retry are append-only audit events and never delete source
  files, candidates or prior failures.
- The existing synchronous browser flow remains supported until a qualified
  worker executes the durable queue; no Redis/Celery dependency is introduced.
- The workbench shows the current durable job and per-file state after upload;
  refresh restores the latest role-scoped job, and the user can run, cancel or
  retry it without re-uploading source files.
- A job has at most one active caller-triggered run. Duplicate run requests
  are rejected while the job is `running`, and cancellation is disabled during
  active extraction so the job cannot report a terminal state before its
  current item has finished.

## Persistence modularization tranche

The first code-structure optimization extracts the local SQLite repository
bootstrap behind a small persistence interface. This is an internal change: the
HTTP payloads, authorization rules, candidate states and transfer semantics do
not change. The extracted module must remain the only owner of connection setup,
schema bootstrap and synthetic account seeding.

Acceptance criteria:

- A fresh database and an existing database can both be opened through the same
  `Database` interface and preserve the current schema behavior.
- Application startup imports the persistence module rather than defining the
  schema in the HTTP orchestration module.
- Existing API, OCR, transfer, export and packaging tests remain green.
- No PostgreSQL dependency or fallback is introduced by this refactor.

The same tranche adds baseline browser security headers to every HTTP response.
The policy must remain compatible with the current single-page workbench and be
strictened after inline JavaScript extraction.

## Problem

The current companion can turn de-identified check-sheet images into reviewed LibreClinica submissions, but it does not yet provide a complete data-management loop. Study teams still need deterministic data validation, field queries, locking, post-transfer verification, operational oversight, structured imports and analysis-ready snapshots.

The product must improve trial operations without becoming a second authority EDC or allowing AI output to bypass human review.

## Users

- Site investigator: works only within the assigned centre, reviews candidates, answers companion data issues, records pre-transfer attestations and sees assigned tasks.
- Central data manager: sees all centres, manages rules and dictionary releases, opens/resolves companion data issues, applies transfer holds, reconciles transfers and exports analysis snapshots.
- Monitor: read-only cross-centre access to reviewed data, evidence, queries and audit metadata; cannot review, submit, change configuration or export direct identifiers.
- Auditor: read-only access to searchable audit and frozen release evidence; cannot change trial data.

## Outcomes

1. Every candidate receives deterministic quality findings before review or transfer.
2. Companion data issues are resolved through a traceable field-level workflow without replacing formal LibreClinica queries.
3. Records under an active companion transfer hold cannot drift through review, transfer or import paths.
4. Submitted values have an explicit read-back state; unsupported authority read-back remains visible and cannot be misrepresented as verified.
5. Structured CSV/XLSX-compatible rows can enter the same candidate/review pipeline without bypassing controls.
6. Central teams can see centre progress, unresolved risk and transfer failures on one dashboard.
7. Dictionary changes use draft, publish and rollback releases rather than mutable live labels.
8. Analysis exports are immutable snapshots with data, metadata, quality/query state and a content hash.
9. Operational readiness is fail-closed when backup, secrets, TLS or approved external integrations are unavailable.
10. Investigators can choose the fields to recognize before starting a batch, so irrelevant report values do not become candidates.
11. A one-click reviewed-recognition export contains only fields that were actually recognized and human-confirmed, while clearly distinguishing values that have and have not reached LibreClinica.

## Functional requirements

### Data quality

- Versioned field rules support data type, requiredness, allowed values, unit, warning range and blocking range.
- Candidate assessment returns `PASS`, `WARN` or `BLOCK` with stable rule codes.
- Transfer creation rejects unresolved `BLOCK` findings and open queries.
- Bulk accept excludes candidates with blocking findings; extraction conflicts
  and Kimi-only provenance remain visible but can be accepted by an explicit
  reviewer-triggered batch action.

### Companion data issues

- Central data managers can open a field-level companion data issue.
- Site investigators can answer issues for their centre.
- Central data managers can resolve or reopen issues.
- Every transition records actor, time and bounded text in the audit trail.
- The UI states that formal queries and SDV remain in LibreClinica and provides the Authority reference when available.

### Pre-transfer attestations and holds

- Site investigators can record a non-electronic-signature pre-transfer attestation after all blocking issues are cleared.
- Central data managers can place/release a companion transfer hold at subject, visit or dataset scope with a reason.
- A hold blocks candidate review, import, transfer creation and transfer submission for its scope.
- Releasing a hold never erases the prior hold record.
- Formal investigator signature, freeze, lock and SDV remain Authority-EDC workflows.

### Authority read-back

- The adapter contract exposes an optional read-back capability.
- Submitted transfers transition to `verified`, `mismatch` or `unsupported` read-back state.
- Mismatch opens a central task and blocks automatic retry.

### Structured import

- Accept UTF-8 CSV files with `subject_ref`, `event_ref`, `field_code`, `value` and optional `unit`.
- Apply centre scope, dictionary allow-list, duplicate detection and quality rules.
- Persist valid rows as ordinary candidates with structured-import provenance.
- Reject the entire file on malformed schema; report row-level accepted/skipped/blocked results without partial ambiguity.

### Pulmonary-function PDF intake

- Accept a pulmonary-function PDF alongside existing report images on the same intake page.
- Read text-layer PDFs locally; never send a PDF, its extracted text or report identifiers to Kimi.
- Register all 21 headers from the supplied pulmonary-function workbook. `姓名` and `住院号` are direct identifiers and `测试号` is a source report identifier; none of those three become review candidates or Authority-EDC values.
- Map the 18 clinical headers to measured values in the report table. `FEV1实/预` uses the measured/predicted percentage and the workbook header `REF` is retained while matching the report label `PEF`.
- Persist only field-level candidates with sanitized evidence, then require the existing human review before acceptance.
- Fail closed for encrypted PDFs, malformed PDFs, files without a usable text layer, unsupported report layouts or reports with no mapped values.

### Recognition scope and reviewed export

- The intake page exposes the active uploadable field list for the selected visit, with select-all, pulmonary-only, clear and search controls.
- The selected field codes are frozen into the current client batch and sent to both pulmonary-PDF and image hybrid extraction endpoints.
- The reviewer can build one intake queue by repeatedly pairing a pseudonymous subject code and visit with one or more report images/PDFs. Each queued file preserves its own subject/visit association; starting the batch uploads every queued file and then exposes one unified de-identification, extraction and review flow.
- The pending-candidate panel groups the unified batch by subject and visit so reviewers can verify record ownership before accepting, editing or rejecting values. Grouping is presentation-only and never weakens item-level audit, quality or role gates.
- Extraction creates candidates only for selected, event-allowed field codes. An omitted selection remains backward compatible and means all event-allowed fields; an empty or invalid explicit selection is rejected.
- The primary one-click Excel action exports human-confirmed recognition values in the caller's role scope and includes only field columns that actually occur in those values.
- The reviewed export labels itself as a companion export and exposes an aggregate LibreClinica submission state per subject and visit. It must not imply that unsubmitted pulmonary fields are Authority-EDC records.
- The existing submitted-only export endpoint remains available for authority-confirmed downstream workflows.
- LibreClinica availability never blocks local source registration, de-identification, recognition, candidate review or the reviewed-recognition Excel export. A failed subject/visit provisioning attempt is recorded as deferred and retried only when the user later triggers Authority submission.

### Lite portable workflow

- Separate Windows and macOS Lite distributions provide only local PDF/image intake, recognition-field selection, human candidate review, SQLite persistence and reviewed-recognition Excel export.
- The Lite distribution has no Docker Desktop, WSL2/Linux engine, LibreClinica, PostgreSQL or mail-capture prerequisite and does not contain their launchers, images, seeds or documentation.
- Recipient startup is extract-and-double-click. Python, Node.js and Tesseract require no separate installation. Kimi remains optional and the local pulmonary-function PDF path works without a key or network access.
- macOS is delivered as native, architecture-specific `arm64` and `x86_64` application bundles. Runtime data lives under the user's Application Support directory rather than inside the signed app bundle.
- An unsigned/ad-hoc macOS artifact is an internal QA build. Frictionless external distribution requires an Apple Developer ID signature and Apple notarization; signing secrets are never stored in the project or artifact.
- Lite mode never exposes Authority submission, transfer, reconciliation, central operations or LibreClinica status controls. Human-confirmed values remain companion records and the workbook labels their authority state as `not_submitted`.
- The integrated LibreClinica distribution remains a separate deliverable and is not weakened or silently replaced by Lite behavior.

### Centre-specific Windows Lite packages

- Each centre ZIP contains one immutable, non-secret `centre-profile.json` with exactly one centre code and one investigator username.
- A fresh centre package creates exactly one active `site_investigator`; it contains no central account, other centre account, sender database, password, session or clinical record.
- First launch blocks normal login until the investigator generates or enters a strong password in the local browser. Only a salted scrypt hash is stored; the plaintext is never written to the ZIP, database, logs or runtime files.
- A profile cannot be attached to an existing database with a different user scope. Startup fails closed instead of retaining demo or central accounts.
- The Windows-only build creates separate centre-labelled ZIPs from a reviewed profile list and black-box verifies setup, login, centre isolation, local PDF extraction, human review and encrypted centre-package export.

### Evidence and duplicates

- Candidate responses expose safe evidence text and source hash; the UI shows provenance beside the review action.
- Duplicate source hashes and duplicate subject/event/field/value rows are reported before new candidates are created.
- Every extraction records an engine-neutral evidence contract: source and de-identified derivative hashes, engine/model versions, dictionary release, preprocessing version, duration, page dimensions, bounded evidence spans and warnings. Raw image/PDF bytes and direct identifiers are never copied into the contract.
- Repeating the same extraction inputs is idempotent. A canonical key over source derivative, dictionary release, selected fields, engine/model and preprocessing returns the existing run and candidates instead of creating duplicates.
- Synthetic gold fixtures provide field-level exact-match, numeric-tolerance, unit and review-rate metrics for extractor qualification. Metrics are local and contain no participant content.

### Operations

- Dashboard metrics cover subjects, visit completion, pending reviews, open queries, blocking findings, transfer/read-back states and tasks by centre.
- Dictionary releases support draft edits, validation, publish and rollback with audit history.
- Analysis snapshots contain submitted values and the active dictionary/rule/query/lock metadata; snapshots are hash-addressed and downloadable.
- In-app tasks cover query response, review, transfer failure, read-back mismatch and overdue synthetic visit windows.
- External email/enterprise messaging remains disabled until explicitly approved.

### Accounts and audit

- Central data managers can create, deactivate and reactivate non-administrator users without setting or exposing a stored plaintext password.
- Session revocation occurs on deactivation.
- Audit search is centre-scoped, paginated and filterable by actor, event type and time.

## Non-goals

- No direct LibreClinica database writes.
- No automated diagnosis, clinical interpretation or Kimi auto-approval.
- No audio follow-up, literature search or GitHub execution in the product.
- No claim of production validation, electronic-signature compliance or real-patient readiness from localhost tests.
- No live hospital LIS/HL7/FHIR, SSO/MFA or external notification connection without approved endpoints and credentials.

## Acceptance criteria

- All new API paths enforce centre and role boundaries with negative tests.
- Blocking rules, open companion issues and active transfer holds prevent transfer.
- Structured imports never bypass candidate review.
- A representative text-layer pulmonary-function PDF creates the expected 18 review candidates without persisting name, hospital number or test number as candidate values.
- PDF processing remains local-only and does not invoke Kimi even when the user-level Kimi toggle is enabled.
- A test adapter proves read-back match and mismatch behavior; LibreClinica reports `unsupported` until a supported read API is qualified.
- Analysis snapshots are deterministic, immutable and hash verified; they are companion exports, not formal locked analysis datasets until reconciled and frozen in the Authority EDC process.
- Desktop and mobile workbench views have no horizontal page overflow or console errors.
- The workbench removes redundant explanatory copy from the header, global warning, export-ready state and operations summary while preserving actionable error/status feedback.
- The confirmed-transfer area is a compact list ordered with pending submissions first, shows five records by default and exposes an accessible expand/collapse control for the remainder.
- Batch review keeps two reviewer-triggered actions enabled after login. Both
  actions cover every active-batch non-BLOCK candidate so either action can
  finish the batch in one request. Quality BLOCK candidates remain
  individual-review only.
- Activating either action with no matching candidate returns a visible no-op message instead of appearing unresponsive.
- If a reviewer activates either bulk action while recognition jobs, candidate rows or quality assessments are still loading, the workbench performs one bounded job-and-candidate refresh and continues the same click automatically. It shows the empty-group message only after that refresh still finds no matching candidate.
- On login, refresh, and after a successful bulk review, the workbench preserves the active batch when it still has pending candidates; otherwise it automatically selects the newest recognition job that still contains pending candidates. A completed newest job must never strand older pending candidates behind item-by-item review.
- A succeeded legacy recognition-job item whose stored candidate-ID value is missing or an empty JSON array restores candidate IDs from exact centre, subject, visit, selected-field and original/de-identified source lineage. An empty legacy array must not force reviewers to accept still-pending candidates one by one.
- After a successful bulk review, accepted candidates disappear from the pending list immediately; skipped candidates remain visible with their server-enforced review gates.
- Selecting only `PFT_FEV1` and `PFT_FVC` before pulmonary-PDF extraction creates no other pulmonary candidates, and the reviewed-recognition workbook contains only recognized field columns.
- With LibreClinica unreachable, an uploaded PDF can still be locally recognized, human-confirmed and included in the reviewed-recognition workbook with `not_submitted`; the Authority submission action remains visibly unavailable or failed until connectivity returns.
- A reviewer can queue reports for at least two different pseudonymous subjects before starting upload; every upload and extraction request uses the subject and visit stored on that individual queue item, and the resulting pending candidates render under the correct subject/visit group.
- Queue items can be removed before upload. Once upload starts, queue mutation is disabled so a report cannot silently change subject ownership during processing.
- A Windows x64 onedir distribution starts the companion without a separate Python installation and contains no credentials.
- The distribution includes pinned offline LibreClinica, PostgreSQL and mail-capture images plus a subject-free synthetic study seed; Docker Desktop with WSL2 is the only external runtime prerequisite.
- A root `Start-Clinical-EDC.cmd` performs first-run setup, prompts for the recipient's Kimi API key, generates a recipient-local LibreClinica password, starts both services and opens both localhost interfaces.
- After first-run setup, Kimi and the LibreClinica SOAP adapter are enabled by default. Missing or invalid local configuration fails closed instead of silently falling back to a simulated upload.
- The distributed seed contains the synthetic study, four CRFs, 161 mapped items and provisioned local roles, but zero subjects, event CRFs, item values, login audit rows or sender password hashes.
- Before calling the Docker API, the Windows launcher detects hardware/firmware virtualization, SLAT, virtual-machine/nested-virtualization context, required Windows features, WSL availability and Docker engine readiness. It replaces raw named-pipe/API errors with stable Chinese remediation codes and writes a credential-free diagnostic report.
- When Docker Desktop is installed but its Linux engine is stopped, `Start-Clinical-EDC.cmd` starts Docker Desktop, keeps any first-run agreement window visible, and waits up to three minutes before returning the existing actionable diagnostic.
- A clean recipient host with no preloaded images treats expected `docker image inspect` and database-readiness non-zero exits as polling signals, loads the bundled offline archive and does not terminate under Windows PowerShell 5.1.
- The archive exposes explicit `Diagnose-This-PC.cmd` and administrator-triggered `Repair-Docker-Prerequisites.cmd` entry points. The repair may enable WSL/Virtual Machine Platform and the Windows hypervisor, but never claims it can change BIOS/UEFI or a VDI host policy.
- `ClinicalReportExtractorLite-windows-x64.zip` starts without Docker/WSL/LibreClinica, accepts a representative pulmonary-function PDF, persists human-confirmed candidates and exports a valid Excel workbook containing the confirmed pulmonary fields.
- The Lite archive contains no Docker, LibreClinica, PostgreSQL or mail-capture assets and no credentials, sender database, uploads or logs.
- The Windows Lite archive exposes one visible branded `Start-Clinical-EDC-Lite.exe` generated with the reviewed Dreamina icon asset. It remains usable after the archive is extracted or moved, starts in Lite mode without arguments, and `compatibility/Start-Clinical-EDC-Lite.cmd` remains available as a secondary command entry point.
- The icon has no embedded text or patient imagery, remains recognizable at 16 px, is stored as a multi-size ICO, and is also applied to the PyInstaller executable. Generation provenance contains no account identifier or credential material.
- Every centre-specific Windows ZIP contains exactly one validated profile and no database. Its first-run repository contains one matching investigator and zero global/other-centre users; completing setup is required before login.
- Black-box verification uses an isolated writable directory, completes one-time password setup, logs in as the packaged investigator, creates reviewed synthetic values and exports an encrypted package whose centre code matches the profile.
- `ClinicalReportExtractorLite-macos-arm64.zip` and `ClinicalReportExtractorLite-macos-x86_64.zip` are built natively on matching macOS runners, contain a double-clickable `.app`, use the same Lite health contract and pass the same PDF-to-review-to-Excel verification.
- The macOS app contains its Python and Tesseract runtimes, creates no data inside its signed bundle and remains fail closed when optional Kimi configuration is absent.
- Full automated test suite passes; representative failure cases are tested.

## 2026-08-22 central package-import ledger

The encrypted centre-package import ledger is the first operational central
domain moved behind a database-neutral repository contract. It records package
receipts and bounded per-file outcomes only. It does not store package bytes,
passphrases, images, direct identifiers or clinical values, and it does not
make the central deployment available before the remaining clinical domains
and institutional identity are qualified.

Acceptance criteria:

- SQLite and PostgreSQL adapters expose the same receipt lookup, atomic claim,
  append-only attempt-log and bounded log-list behavior.
- A package is unique by both canonical package ID and encrypted-envelope
  SHA-256. Concurrent claims produce exactly one receipt; later claims are
  classified as duplicates without overwriting the first receipt.
- The current SQLite HTTP workflow claims the receipt inside the same
  transaction that creates imported candidates. A lost duplicate race rolls
  back that package's candidate writes and returns the existing stable 409
  response.
- PostgreSQL migration 2 creates only the non-clinical import receipt and log
  tables. Central application startup remains fail-closed and
  `clinical_data_ready=false`.
- Failure detail is capped at 500 characters and source filename at 200
  characters. Neither adapter may persist ciphertext, passphrases, extracted
  values or direct identifiers in the ledger.

## 2026-08-22 reviewed-package clinical import slice

The next central persistence slice moves one complete clinical transaction
behind a shared repository interface: accepting a previously human-reviewed,
pseudonymous centre package into the Companion. It does not enable general
candidate creation, source-image intake, user administration or Authority EDC
submission in PostgreSQL.

Acceptance criteria:

- `import_package()` atomically claims the package, creates source metadata,
  inserts non-duplicate human-confirmed candidates, evaluates/persists the
  supplied deterministic quality result, appends chained audit events and
  records the final import attempt.
- SQLite and PostgreSQL adapters pass the same contract for first import,
  exact-value deduplication, repeated-package rejection and imported-value
  retrieval.
- PostgreSQL serializes audit-chain tail updates and uses a database uniqueness
  constraint to prevent two different packages from creating the same active
  candidate concurrently.
- The repository accepts only pseudonymous field records and metadata. Raw
  images, encrypted package bytes, passphrases, Kimi keys and direct identity
  fields are outside its interface and schema.
- The existing local HTTP endpoint retains its request, response, role,
  dictionary, hold and encrypted-file behavior while delegating the clinical
  transaction to the SQLite adapter.
- PostgreSQL migration 3 remains an incomplete central repository;
  `clinical_data_ready=false` and central startup stay fail-closed until all
  required central reads, identity and operational controls are qualified.
- The evidence contract is persisted and returned with candidates; a repeated extraction returns the same candidates and run without a second candidate set.
- A PDF inspection response distinguishes usable text-layer pages from scanned pages before extraction. Scanned pages remain fail-closed until an approved local OCR adapter is enabled.
