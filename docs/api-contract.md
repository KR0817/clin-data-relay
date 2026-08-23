# Operations API Contract

**Version:** `operations-v1`  
**Boundary:** synthetic localhost qualification

All endpoints require a bearer session unless marked public. Site-scoped users receive `404` for inaccessible record IDs where existence disclosure would cross centre boundaries.

## Internal module extraction

The 2026-08-22 modular-monolith extraction is HTTP-transparent. Static delivery
and authentication are registered through router factories, but every public
path, request field, response field, status code, cache header, role rule and
session lifetime remains unchanged. The authenticated-user dependency is the
only authentication interface used by downstream route modules.

This is not the PostgreSQL or institutional-identity release. `central` remains
fail-closed, and no OIDC/SAML callback, refresh token or central database field
is added by this tranche.

The canonical-root and Git-baseline migration is HTTP-transparent. Moving the
source checkout, excluding local runtime state and creating a private remote do
not change routes, request or response fields, roles, session lifetime, storage
semantics or the Authority EDC boundary.

The Kimi settings module extraction is also HTTP-transparent. It preserves
`GET /api/settings/kimi` and `PUT /api/settings/kimi`, the existing bounded key
validation, Lite centre-investigator restriction, redacted response fields and
`kimi_credential_configured` audit event. The credential value remains local
file state and is never a response or database field.

The PostgreSQL repository bootstrap adds no HTTP route and does not enable the
central deployment profile. Its interface is an operator/development preflight;
all existing HTTP paths continue to use the local SQLite profile until the
clinical repository and institutional identity slices are complete. No DSN or
connection metadata is added to `/api/health`.

The PostgreSQL Study Membership repository is also HTTP-transparent. Schema
version 5 stores only a provider alias and pseudonymous Institutional Principal
ID with role, centre and lifecycle metadata. No identity-provider subject,
assertion, token, credential or provider response is an HTTP, membership lookup
or audit-detail field. The verified principal username is not a membership key;
existing creator and audit-actor fields still identify the separately
authorised operator. The slice adds no membership administration endpoint,
login, callback or session field. Central startup remains fail-closed.

The PostgreSQL Institutional Session repository is likewise internal and
HTTP-transparent. It returns a bearer secret only to its direct caller and
stores only a token digest, bounded operator username, membership reference and
lifecycle timestamps. It adds no login, callback, logout, refresh, metadata or
JWKS endpoint. Existing local `POST /api/auth/login` and bearer resolution are
unchanged; central HTTP remains fail-closed until a qualified provider adapter
is selected and composed.

## Runtime and static assets

- `GET /static/css/app.css` — versioned browser stylesheet for the workbench. It
  is a presentation asset only and carries no clinical data or credentials.
- `GET /static/js/workbench.js` — same-origin workbench behavior bundle. It is a
  presentation/orchestration asset only, carries no credentials or API keys,
  and is served with `Cache-Control: no-store, max-age=0` during qualification.
- `GET /static/img/workbench-*.webp` — audited decorative workbench derivatives.
  They contain no patient data, readable report text, credentials or runtime
  provider dependency. Prompt and provider task metadata are not served from
  `/static`.
- The browser derives a `central`, `site` or `oversight` workspace projection
  only from the authenticated `POST /api/auth/login` response. This changes
  headings, navigation labels and default disclosures only. It does not add an
  endpoint, broaden a role, change centre scoping or make browser visibility an
  authorization control.
- Context-art selection is a presentation-only consequence of that same closed
  role projection. Images do not add an API field or participate in an
  authorization, recognition, review or export decision.
- `GET /api/health` includes `deployment_profile` and a redacted
  `database_backend` label. It never returns database paths, connection strings,
  API keys or passwords.
- `GET /api/health.kimi_integration` is `ready`, `key_required`,
  `misconfigured` or `disabled`. `key_required` means Kimi is enabled by the
  product default but no recipient-local key is present; it never means that a
  request was attempted. `kimi_default_enabled` reports the resolved boolean
  default without exposing credential material.
- `GET /api/settings/kimi` requires an authenticated workflow-write session and
  is available only in a centre-profile Lite runtime. It returns
  `{configured, status, model}` and never returns the credential or its path.
- `PUT /api/settings/kimi` accepts `{key}` with a bounded non-whitespace secret,
  atomically writes the launcher-owned local credential file and hot-reloads the
  Kimi client. It returns the same status-only shape. Generic/full runtimes fail
  closed with `centre_kimi_configuration_unavailable`.
- `COMPANION_DEPLOYMENT_PROFILE=central` is fail-closed until the qualified
  PostgreSQL repository adapter is installed. It must not silently use the local
  SQLite repository.

The persistence extraction is intentionally HTTP-transparent. No endpoint,
request field, response field, role rule or transfer state changes in this
tranche. The local SQLite repository remains private implementation behind the
application factory and is not a network-sharing interface.

All HTTP responses include baseline security headers. The CSP permits only
same-origin scripts and resources (with data/blob previews for local evidence);
it does not permit arbitrary remote scripts, frames or form targets.

## Quality

- `GET /api/quality/rules` — active rule version and central-safe rule metadata.
- `GET /api/candidates/{id}/quality` — latest `PASS|WARN|BLOCK` assessment and findings.
- `POST /api/candidates/{id}/quality/re-evaluate` — reviewer-triggered deterministic re-evaluation.

## Companion data issues

- `GET /api/data-issues?status=&centre_code=&candidate_id=` — role-scoped companion issue list.
- `POST /api/candidates/{id}/data-issues` — central manager opens an issue with `{message}`.
- `POST /api/data-issues/{id}/answer` — site investigator answers with `{message}`.
- `POST /api/data-issues/{id}/resolve` — central manager resolves with `{message?}`.
- `POST /api/data-issues/{id}/reopen` — central manager reopens with `{message}`.

## Transfer holds and attestations

- `GET /api/transfer-holds/effective?centre_code=&subject_ref=&event_ref=` — effective companion hold state.
- `POST /api/transfer-holds` — central manager appends `{scope, centre_code?, subject_ref?, event_ref?, action, reason}`.
- `POST /api/visits/{centre_code}/{subject_ref}/{event_ref}/attest` — site investigator records a pre-transfer attestation and a canonical candidate-state hash.
- `GET /api/visits/{centre_code}/{subject_ref}/{event_ref}/attestations` — role-scoped attestation history with `valid` and `invalidation_reason`; any later candidate-state change invalidates the prior attestation.

These endpoints do not create formal EDC queries, electronic signatures, freezes or locks.

## Structured import

- `POST /api/imports/structured-csv` — multipart `file`, `synthetic_attestation=true`; returns batch summary, ignored headers and created candidate IDs.

The CSV must be UTF-8/UTF-8-BOM, no larger than 5 MiB and no more than 5,000 rows. Required headers are `subject_ref,event_ref,field_code,value`; `unit` is optional. Unknown headers are reported and ignored. Schema, dictionary, value, duplicate and quality validation completes for the entire file before any candidate is persisted.

## Durable recognition jobs

- `POST /api/recognition-jobs` creates a local durable ledger from
  `{items:[{source_file_id,edc_subject_ref,edc_event_ref,field_codes?}]}`.
- `GET /api/recognition-jobs` lists role-scoped jobs and bounded item status.
- `GET /api/recognition-jobs/{id}` returns one role-scoped job with item status,
  sanitized error codes and timestamps.
- `POST /api/recognition-jobs/{id}/cancel` marks queued work cancelled; it
  never deletes source files or candidates. A running job returns
  `409 recognition_job_running` so the current extraction call can finish
  without a false terminal state.
- `POST /api/recognition-jobs/{id}/retry` requeues failed items only and records
  an audit event.
- `POST /api/recognition-jobs/{id}/run` caller-triggered recovery bridge that
  executes queued items through the existing local PDF/OCR extraction seams;
  it updates each item independently and never writes LibreClinica.

The local ledger is a persistence seam for browser refresh and worker recovery.
The bounded `run` bridge executes existing local extraction synchronously until
a separately qualified background worker replaces it; it does not write
LibreClinica. Site users are
centre-scoped; central data managers are cross-centre; monitor and auditor
roles are read-only. Item error details are closed-enumeration codes and never
include paths, OCR text, images, credentials or raw provider responses.

The workbench recognition-job panel is a client projection of these routes. It
may show only the latest job for compactness; the list/detail endpoints remain
complete for operational tooling.

Each item includes `candidate_ids`, an ordered list of exact candidate IDs
created or returned by its latest successful extraction. The list is empty for
queued, running, failed and cancelled items. A succeeded legacy item is repaired
only from exact centre/subject/visit/field and original-or-confirmed-derivative
source lineage when its stored association is SQL `NULL` or the JSON value
`[]`; any recovered IDs replace that empty legacy value. A non-empty stored
array remains authoritative. The list contains identifiers only and follows
the same job/centre authorization scope.

The run bridge is single-flight: a request against a `running` job returns
`409 recognition_job_already_running`, preventing duplicate candidate creation.
The browser disables run and cancel while the job is running.

## Pulmonary-function PDF intake

- `POST /api/source-files/upload` accepts PNG, JPEG and `application/pdf`.
  Images must match their magic bytes, decode successfully and remain under the
  explicit pixel limit. For browser drag-and-drop compatibility, an empty,
  `application/x-pdf`, or `application/octet-stream` MIME is accepted only when
  the safe basename ends in `.pdf`; PDF preflight requires `%PDF-`, a trailing
  `%%EOF`, a bounded indirect-object count and bounded dictionary nesting.
  Accepted PDFs are normalized to `application/pdf`. PDFs are limited to 20 MiB;
  images retain the 8 MiB limit.
- `GET /api/recognition-fields?event_ref=WEEK_0` returns uploadable `{field_code, display_header, source_header, category}` options from the active dictionary for a workflow write role.
- `POST /api/source-files/{id}/pulmonary-function-extract` accepts `{edc_subject_ref, edc_event_ref, field_codes?}` and returns ordinary candidate payloads.
- `GET /api/source-files/{id}/pdf-inspection` returns `{classification,page_count,pages:[{page_number,width,height,text_char_count}],warnings}` for a locally stored PDF. It never creates candidates, calls Kimi or returns raw page text. `classification` is one of `pdf_text_layer`, `pdf_scanned_pages` or `pdf_invalid`.

`field_codes` is an optional non-empty unique list of at most 500 stable uppercase field codes. When omitted, all fields allowed for the selected event remain eligible. When present, both PDF and hybrid extraction create candidates only for the requested event-allowed fields; unknown or cross-event values return `recognition_field_not_allowed`. The extraction endpoint requires a locally stored PDF, centre access and a reviewer-capable role. It is idempotent for the same source and visit, rejects a different subject for an already extracted source/visit, never calls Kimi, and never creates candidates for `姓名`, `住院号` or `测试号`.

When a localhost LibreClinica adapter is configured, upload still requires pseudonymous `edc_subject_ref` and `edc_event_ref`, but Authority availability is not an intake gate. The response reports `edc_subject_provisioning.status=completed|deferred`; deferred results include only a stable sanitized `error_code`, retain `subject_oid=null`, and do not block local recognition, human review or the reviewed-recognition Excel export. Explicit transfer submission retries provisioning and remains the only Authority-write gate.

## Excel exports

- `GET /api/exports/reviewed-recognition-data.xlsx` exports role-scoped, human-confirmed recognition values. Event sheets contain only field columns that occur in the exported records and expose aggregate LibreClinica submission state. The workbook is explicitly a companion export and may contain values not yet present in LibreClinica.
- `GET /api/exports/submitted-data.xlsx` retains the authority-confirmed contract and exports only candidates whose latest transfer is `submitted`.

## Encrypted batch exchange and operational endpoints

- `POST /api/exports/reviewed-recognition-package.json` accepts a
  `package_passphrase` form field and returns an AES-256-GCM encrypted package.
  The site investigator is the only package-export role; the response carries
  `X-Offline-Package-SHA256`. Plain JSON package uploads are rejected.
- `POST /api/imports/reviewed-packages` is central-data-manager-only. It accepts
  `files[]` and `package_passphrase`, processes each file independently and
  returns `results[]` with `imported`, `duplicate` or `failed`, including only
  stable error codes and counts. A package whose dictionary ID/version differs
  from the active release is rejected and logged.
- `GET /api/imports/reviewed-package-logs` is central-data-manager-only and
  returns bounded per-file import logs and failure details without values or
  ciphertext.
- `GET /api/security/disk-encryption` reports a read-only BitLocker/FileVault
  preflight (`enabled|disabled|unknown|unsupported`). The app never changes
  OS encryption state.
- `GET /api/security/retention` reports the configured original-source
  retention days and purged count. `scripts/cleanup_expired_originals.py`
  performs dry-run/explicit cleanup while preserving source hashes and audit.
- `POST /api/admin/centre-accounts` creates unique site investigator accounts
  for a bounded list of centre-code/email pairs in synthetic/development
  environments. Passwords are returned once and never stored in logs.
- Central cross-centre candidate, package-log and import views are restricted
  to `principal_investigator` and `central_data_manager`; site investigators
  remain centre-scoped.

Stable pulmonary PDF error details include:

- `pulmonary_pdf_required`
- `pdf_encrypted`
- `pdf_text_layer_required`
- `pulmonary_report_values_not_found`
- `pulmonary_pdf_parse_failed`
- `pulmonary_pdf_page_limit`
- `pdf_inspection_required`

## Extraction evidence and idempotency

- Candidate payloads include `extraction_run_id` and a bounded `extraction_evidence` object when generated by a local extraction path.
- `GET /api/extraction-runs/{id}` returns the role-scoped immutable evidence contract without raw bytes or direct identifiers.
- The evidence contract includes engine/model versions, source and derivative hashes, dictionary/preprocessing releases, duration, page dimensions, bounded spans and warnings.
- Extraction retries with the same canonical inputs return the existing run/candidates with HTTP 200; they never create a second candidate set. A selected-field request that asks for fields absent from the prior candidate set, or a changed dictionary release, engine/model or preprocessing version, creates a new idempotency key; a subset request may safely reuse the existing superset.
- `POST /api/extraction-evaluations` is not a production data path; the local `scripts/evaluate_ocr.py` command evaluates only synthetic gold/prediction JSON and emits aggregate metrics.

## Authority read-back

- `POST /api/transfers/{id}/readback` — runs the configured adapter capability and records `verified|mismatch|unsupported`.
- Transfer payloads include `readback_status`, `readback_checked_at` and `readback_attempt_count`.

## Operations and tasks

- `GET /api/dashboard` — centre-scoped operational metrics.
- `GET /api/tasks?status=` — assigned or central tasks.
- `POST /api/tasks/{id}/complete` — completes a task with optional bounded note.

Issue-response tasks close automatically when the site submits an answer. Transfer-failure and read-back-mismatch tasks remain companion workflow aids; formal query, SDV, signature, freeze and lock workflows remain in LibreClinica.

## Dictionary releases

- `GET /api/admin/dictionary-releases` — central-only release history and active release.
- `POST /api/admin/dictionary-releases/draft` — create/reuse a draft.
- `PUT /api/admin/dictionary-releases/{id}/items/{event_ref}/{field_code}` — update a draft label.
- `POST /api/admin/dictionary-releases/{id}/publish` — validate and publish.
- `POST /api/admin/dictionary-releases/{id}/rollback` — create a new release from history.

The existing `/api/admin/field-dictionary` response includes the active release and remains compatible. Direct mutable header updates are retained as a compatibility path that writes only to the active draft and never changes an immutable published release.

## Accounts and audit

- `GET /api/admin/users` — central-only user list without password hashes or tokens.
- `POST /api/admin/users` — create `{username, centre_code?, role}` and return a one-time synthetic bootstrap password only in test/development.
- `POST /api/admin/users/{id}/deactivate` — deactivate and revoke sessions.
- `POST /api/admin/users/{id}/reactivate` — reactivate.
- `POST /api/candidates/{id}/review` accepts `decision`, optional `reason`, and
  review evidence fields. A `conflict` acceptance requires
  `selected_source=local|kimi`; a manual value uses `decision=edit`,
  `selected_source=manual` and `edited_value`. `kimi_only` acceptance requires
  `evidence_acknowledged=true` and the candidate `source_file_id`.
- `POST /api/candidate-reviews/bulk-accept` accepts unique `candidate_ids` and
  an optional `review_batch_id`. By default only `agreement`, `local_only` and
  `local_fallback` are eligible. Optional `override_sources` plus a non-empty
  `override_reason` are central-data-manager-only. The response contains
  `accepted_count`, `skipped_count`, accepted `candidates`, per-candidate
  `skipped` records and a normalized `summary`.
- `GET /api/audit-events?event_type=&actor=&review_mode=&review_batch_id=&from=&to=&limit=&offset=` — role-scoped searchable audit.
- `GET /api/audit-chain/verify` — read-only global-role chain verification.
- `GET /api/audit-chain/anchor` — principal-investigator/central-data-manager
  export of the current chain head, event count and generation time. The
  anchor contains no clinical values or credentials.

## Analysis snapshots

- `POST /api/analysis-snapshots` — central manager creates an immutable submitted-data snapshot.
- `GET /api/analysis-snapshots` — central list.
- `GET /api/analysis-snapshots/{id}` — metadata and integrity state.
- `GET /api/analysis-snapshots/{id}/download` — canonical JSON with attachment disposition.

Snapshots have no update or delete route. Each download is checked against the stored SHA-256 and is explicitly labelled as a companion export rather than a formal Authority-EDC lock.

## Public health

- `GET /api/health` — reports capability state, `application_version`,
  `database_schema_version`, active quality/dictionary versions,
  `product_mode=full|lite` and fail-closed production-readiness gates without
  exposing credentials. Each gate includes a boolean state and a stable
  blocking reason; production approval metadata is read from the secret-free
  evidence manifest configured by `COMPANION_PRODUCTION_EVIDENCE_FILE`.

When `product_mode=lite`, the local upload, extraction, review, candidate-list and reviewed-recognition Excel interfaces are unchanged. Authority transfer interfaces remain fail closed and are not presented by the browser. Lite mode never converts a local review into an Authority submission.

The backup gate reads restore evidence from the configured backup directory. A passing backup gate does not change the overall localhost/synthetic production status from `BLOCK`.

## Client presentation boundary

The 2026-08-18 visual redesign is presentation-only. Same-page navigation,
responsive layout, semantic color tokens and inline decorative SVG do not add
requests or change response interpretation. Existing element IDs used by
`workbench.js`, all review payloads, role scopes, audit semantics and
fail-closed transfer behavior remain stable.

The confirmed-transfer workbench list is a client-side projection of the existing role-scoped candidate and transfer responses. It shows five rows by default and can reveal the remaining rows without changing API completeness, export scope or transfer state.

The two batch-review controls are always interactive client projections. The
bulk action sends only active-batch `agreement`, `local_only` and
`local_fallback` candidates. The review-required action scrolls to the first
`conflict` or `kimi_only` candidate and does not call the bulk endpoint. Empty
selections do not call the API. `POST /api/candidate-reviews/bulk-accept`
independently enforces the same default source policy plus quality, hold,
authorization and pending-state gates. A central-data-manager override exists
at the API boundary for controlled operations, but it is not exposed as a
one-click browser action and requires a written reason and per-candidate
confirmed deidentified evidence acknowledgement.

If an interactive bulk-review control is activated before its client
projection finishes loading, the client performs one role-scoped recognition
job and candidate refresh, recomputes the same requested group and then either
sends its explicit candidate IDs or displays the empty-group message. The
refresh does not broaden centre scope or bypass server review gates.

The client initially projects the latest recognition job, then reconciles that
selection against the role-scoped pending candidates. If the selected job has
no pending candidate, the client selects the newest listed recognition job that
does. This changes only the client selection; the bulk-review request still
contains explicit candidate IDs and cannot cross role or centre scope.

The split batch-review controls also remain a client-side projection. `POST /api/candidate-reviews/bulk-accept` continues to receive an explicit bounded `candidate_ids` array and independently enforces quality BLOCK, role, centre and transfer-hold gates. Button labels never create an auto-approval API.

Before any Kimi-bound request, the derivative draft masks OCR lines carrying
patient identifiers, clinical staff identity/signature labels, or collection,
receipt and review timestamps. `POST /api/deidentification-drafts/{id}/confirm`
continues to require an explicit visual-review attestation; marker detection
alone does not authorize outbound processing.

The multi-subject intake queue is also client-side and introduces no batch upload endpoint. For every queued file, the browser calls `POST /api/source-files/upload` separately with that item's own `edc_subject_ref` and `edc_event_ref`; subsequent PDF or hybrid extraction uses the same immutable item context. Candidate grouping by subject/visit does not alter `GET /api/candidates`, candidate IDs, review payloads, centre isolation or audit semantics.

## Portable runtime health contract

After recipient first-run configuration and successful localhost LibreClinica startup, `GET /api/health` reports `status=ok`, `data_boundary=synthetic_only`, `kimi_integration=ready`, `edc_adapter=libreclinica_soap` and `production_readiness.status=BLOCK`. The LibreClinica readiness probe must also confirm the login route and SOAP WSDL before the companion starts. Missing configuration or an unavailable authority service fails closed and never converts an intended authority submission into a simulated submission.

The Lite portable runtime reports `status=ok`, `product_mode=lite`, `local_ocr=local_only`, `excel_export=ready`, `edc_adapter=fail_closed_simulation_only` and `production_readiness.status=BLOCK`. Kimi may be `ready`, `key_required`, `misconfigured` or `disabled`; its state does not gate local PDF extraction or Excel export.

`scripts/check_production_readiness.py` uses the same read-only evaluator as
the health endpoint and exits non-zero when any production gate is blocked. It
does not enable controls, alter credentials, or claim institutional approval.

The Lite HTTP contract is platform-neutral. Windows and macOS packages expose the same localhost routes and response bodies; operating-system architecture, signing state and filesystem locations are packaging concerns and are not added to clinical API payloads. On macOS, writable database/upload/runtime state is rooted outside the signed `.app` under the current user's Application Support directory.

## Centre-specific first-run setup

- `GET /api/setup/status` is unauthenticated and returns `{required, centre_profile}`. `centre_profile` contains only `centre_code` and `username`, or `null` for a generic/development runtime. It never returns a password hash or setup secret.
- `POST /api/setup/complete` accepts `{password, password_confirmation}` only while the configured centre account is locked for first use. It returns `{status: "completed", username, centre_code}` and never echoes the password.
- The endpoint rejects missing profiles (`centre_profile_required`), completed setup (`setup_already_completed`), mismatched confirmation (`password_confirmation_mismatch`) and weak passwords (`strong_password_required`). Concurrent completion is resolved atomically; only one request can replace the setup-required sentinel.
- `GET /api/health.centre_profile` reports the same non-secret profile summary and `setup_required` state for packaged-runtime diagnostics.
- Portable launchers use `product_mode` plus this profile summary as the runtime
  identity. A healthy but mismatched localhost instance is not reusable.
- `POST /api/auth/login` verifies salted scrypt hashes for centre packages.
  Legacy digests are accepted only for rows explicitly marked `legacy_demo`,
  only in test/development without a locked centre profile, and are upgraded to
  scrypt after the first successful login. Production rejects them. A
  setup-required account cannot authenticate.
- The browser does not automatically log in after setup. It retains the locally
  entered password only long enough to show a one-time copy/download receipt;
  explicit continuation clears that memory after successful login. Password
  recovery is not an HTTP endpoint. The packaged local reset command rotates
  the centre account hash, revokes sessions and prints the new password once.

The Windows host preflight occurs before the HTTP application starts and therefore adds no public endpoint. Its credential-free diagnostic JSON uses stable `EDC-HOST-*` codes and boolean/nullable capability fields; it must not include raw Docker responses, API keys, credential hashes, environment variables or hardware serial numbers. Optional `docker_start` metadata is limited to `attempted`, `method`, `outcome` and `wait_seconds`, where values come from closed enumerations and contain no command output or filesystem path.

## Package-import ledger behavior

The encrypted package endpoints retain their request and response shapes while
the package receipt and attempt log are accessed through a repository contract.
Duplicate classification is authoritative only after the final transactional
receipt claim. Concurrent uploads of the same package therefore yield one
import and one or more `409 offline_package_already_imported` outcomes rather
than a server error or duplicate candidate set.

PostgreSQL support in this slice is a service-backed repository contract, not
an enabled central HTTP profile. No request is routed to PostgreSQL until the
complete central clinical write path and institutional authentication are
qualified.

## Reviewed-package import persistence

The single-file and batch encrypted-package endpoints remain HTTP-compatible.
After decryption, dictionary validation and transfer-hold evaluation, the
local route delegates the complete Companion clinical write to the SQLite
reviewed-import repository. Its returned created/duplicate counts remain the
response source. A repeated or concurrently claimed package still returns
`409 offline_package_already_imported`.

The equivalent PostgreSQL interface is contract-tested without adding an HTTP
route or enabling `COMPANION_DEPLOYMENT_PROFILE=central`. The repository accepts
no package bytes, passphrases, images, direct identity fields or external-model
credentials.

## Confirmed-data read persistence

`GET /api/exports/reviewed-recognition-data.xlsx` keeps its existing public
contract. Internally, the active SQLite application translates the authenticated
role into either one exact centre scope or an explicit all-centres scope and
queries the confirmed-data repository. The repository returns only
`human_confirmed` values in deterministic order; optional subject and visit
filters are repository contract inputs, not new HTTP query parameters in this
slice.

The PostgreSQL adapter is contract-tested for future central composition but is
not reachable from HTTP. Imported centre-package values report Authority state
as not submitted because the PostgreSQL transfer/read-back domain has not been
migrated. `COMPANION_DEPLOYMENT_PROFILE=central` remains fail-closed and the
repository status remains `clinical_data_ready=false`.

## Verified-principal authorization contract

This slice is HTTP-transparent. It adds no login, callback, metadata, logout or
token-refresh route and does not accept identity assertions through ordinary
request headers. Existing local `POST /api/auth/login` behavior is unchanged.

The internal authorization contract accepts only a principal already verified
by a future qualified identity-provider adapter and one application-controlled
study membership. MFA, authentication freshness, membership effectiveness and
role/centre invariants must pass before an existing-compatible user context can
be produced. Stable failures do not include tokens, assertions, usernames,
provider payloads or provider subjects.

`COMPANION_DEPLOYMENT_PROFILE=central` remains fail-closed. Setting
`COMPANION_AUTH_MODE=oidc|saml` or readiness evidence cannot create an identity
adapter or enable central HTTP by itself. `/api/health.production_readiness`
keeps the existing shape but its `identity_provider` gate now also requires a
runtime adapter capability; the current runtime reports it as blocked.

### Project-owned OIDC verified claims

When no hospital identity provider exists, an approved project-owned OIDC
provider may be used to establish project-account control and MFA only. This is
an internal Python contract, not an HTTP endpoint:

```python
principal_from_verified_oidc_claims(policy, verified_claims)
```

`verified_claims` must already have passed qualified OIDC Authorization Code
validation. The function requires exact `iss`, the configured `aud`, the
configured MFA `acr`, opaque `sub`, the configured username claim and numeric
`auth_time`. If `aud` has multiple values, exact `azp` is also required. It
returns a verified principal with no role or centre. Provider authorization
claims are ignored; only Study Membership can supply role and centre.

Stable failures are `project_oidc_policy_invalid`,
`project_oidc_claims_invalid`, `project_oidc_issuer_mismatch`,
`project_oidc_audience_mismatch`, `project_oidc_mfa_required` and
`project_oidc_authentication_time_invalid`. Errors do not include input values.
No callback, raw JWT, provider token, secret or new browser response is part of
this contract, and central readiness remains blocked.

### Project OIDC browser flow

These routes are defined for the future qualified central composition and are
not mounted by the current local application:

`GET /api/auth/oidc/login`

- Requires signed browser-session middleware.
- Returns a temporary redirect to the configured project OIDC provider using a
  fixed HTTPS callback, `openid`, PKCE S256, nonce, MFA ACR and bounded
  authentication age.
- Returns `Cache-Control: no-store`.

`GET /api/auth/oidc/callback`

- Completes Authlib's Authorization Code exchange and accepts only its verified
  `userinfo` mapping.
- Creates a two-minute browser-bound Login Exchange and returns `303` to the
  fixed same-origin completion URL with `oidc_exchange=<opaque-code>`.
- The Location and body never contain an IdP token or Companion bearer.

`POST /api/auth/oidc/exchange`

```json
{"exchange_code":"cdre_<43 base64url characters>"}
```

- Requires the same signed browser session that initiated login.
- Consumes the code once, verifies active Study Membership and returns the
  existing `access_token`, `token_type=bearer` and bounded user projection.
- A replay, expiry, malformed code or wrong browser returns `401` with
  `project_oidc_exchange_invalid`.

Other bounded details include `project_oidc_browser_session_required`,
`project_oidc_callback_failed`, `project_oidc_access_denied`,
`project_oidc_provider_unavailable` and `project_oidc_session_unavailable`.
No endpoint returns provider error text, raw claims, raw subject, provider
tokens, browser binding or database details. The current composition exposes
none of these routes and remains fail-closed.

### Project Companion Session authentication

This future-central module is not mounted by the current local application.
When central composition is qualified, its `current_user` dependency accepts
the existing `Authorization: Bearer <cdrs-token>` header and supplies the same
`UserContext` shape used by downstream routes.

- Missing authorization returns `401 authentication_required`.
- Malformed, unknown, expired, revoked or membership-invalid sessions return
  `401 invalid_or_expired_token`.
- Repository availability failures return `503 project_session_unavailable`.

`POST /api/auth/logout`

- Requires a currently valid Companion bearer.
- Revokes that session and returns `204` with `Cache-Control: no-store`.
- The bearer cannot authenticate a later request.

Responses never contain the bearer, its digest, repository error text,
membership identifiers or connection details. Local `POST /api/auth/login` and
the client-side Lite workflow remain unchanged until a separate composition
slice explicitly selects central authentication.

### Operator-only first membership bootstrap

This is a local OS/database-operator command contract, not an HTTP endpoint.
The JSON must be supplied through an approved protected-stdin procedure:

```powershell
$requestJson | & .\.venv\Scripts\python.exe scripts\bootstrap_central_membership.py
```

`$requestJson` must be created in a short-lived operator process and removed
from that process after execution. Do not paste the subject into the command
line or PowerShell history and do not write it to `.runtime`, the repository or
an ordinary temporary file. Managed PowerShell/Python strings are released at
process exit but are not securely erased; terminal recording, endpoint
monitoring and backup controls remain part of the approved procedure.

Bootstrap stdin is one exact JSON object:

```json
{
  "action": "bootstrap",
  "subject_id": "exact-qualified-oidc-sub",
  "operator_id": "operator:approved-admin",
  "membership_expires_at": "2027-08-24T00:00:00Z",
  "confirmation": "BOOTSTRAP_FIRST_CENTRAL_DATA_MANAGER"
}
```

Rollback stdin is one exact JSON object:

```json
{
  "action": "rollback_unused_bootstrap",
  "membership_id": "00000000-0000-0000-0000-000000000000",
  "operator_id": "operator:approved-admin",
  "reason": "Correcting the witnessed pre-login subject mapping.",
  "confirmation": "ROLLBACK_UNUSED_CENTRAL_DATA_MANAGER_BOOTSTRAP"
}
```

The command accepts no subject, DSN, provider alias or operator argument on the
command line. Bootstrap success returns only `status=granted`, membership ID,
`role=central_data_manager`, `centre_code=null`, `valid_from` and `expires_at`.
Rollback success returns only `status=rolled_back`, membership ID and
`active=false`. Failures return `status=error` plus one stable code. The raw
subject and Principal ID are never output.

The command requires `COMPANION_POSTGRES_DSN`, `COMPANION_ENV` and
`COMPANION_OIDC_PROVIDER_ID`. The subject must be the exact OIDC `sub` verified
for that configured client; email, username, IdP role/group and an unqualified
administration-console identifier are invalid substitutes. Before use, an
external qualification record must bind provider alias, issuer, client ID and
subject-mapper mode, demonstrate the mapping with a synthetic account and
record two-person verification of the real account. The command does not fetch
or validate this evidence. `operator_id` is a caller-supplied audit label, not
operator authentication, and neither it nor rollback `reason` may contain the
subject or other direct identity material.

Only the dedicated rollback event can reopen an unused bootstrap. Generic
membership deactivation does not. Any Companion Session history permanently
closes bootstrap recovery. A `granted` response proves only the atomic
membership/audit write: identity-provider readiness and central clinical-data
readiness remain false, central HTTP remains unmounted, and production remains
`BLOCK`. An audited emergency membership-deactivation path for mistakes found
after first login is still required.

This slice adds no migration, but the command calls the standard repository
prepare step before changing membership state. It can therefore apply older
versioned migrations that are not yet present and must be run under the same
database backup, migration review and change-control procedure.

## Errors

Stable detail codes include:

- `quality_blocked`
- `open_data_issue_blocks_transfer`
- `transfer_hold_active`
- `query_transition_not_allowed`
- `readback_unsupported`
- `structured_import_invalid_schema`
- `structured_import_too_large`
- `duplicate_candidate`
- `dictionary_release_not_draft`
- `production_gate_blocked`
- `recognition_job_not_found`
- `recognition_job_not_cancellable`
- `recognition_job_not_runnable`
- `recognition_job_already_running`
- `recognition_job_running`
- `recognition_job_no_failed_items`
- `recognition_job_duplicate_source`
- `recognition_job_multiple_centres`
- `offline_package_timestamp_invalid`
