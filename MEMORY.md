# Project Memory

## Stable decisions

- LibreClinica 1.4 is the authority EDC; this project is an AI-assisted data-capture companion.
- The companion uses supported SOAP/ODM interfaces and never writes LibreClinica tables directly.
- Site investigators and central data managers have write-capable sessions; centrally provisioned monitor/auditor accounts are read-only. Historical entry-only accounts remain inactive for audit provenance.
- Source images are locally de-identified, presented for human confirmation and then processed by local OCR. Kimi K3 is optional and receives only confirmed derivatives plus bounded evidence.
- Pulmonary-function PDFs use a separate local text-layer parser and are never sent to Kimi. Name, hospital number and test number are source identifiers and never become candidates.
- Recipient distribution has two profiles backed by the same application modules: the full companion may use the separately administered Authority EDC, while `product_mode=lite` is a local-only PDF/image recognition, human-review and Excel-export utility with no EDC adapter or container runtime.
- The Lite profile is platform-neutral. Windows and macOS use `app.portable_launcher`; Finder starts a dedicated macOS entry point that forces Lite, while writable Mac state lives under `~/Library/Application Support/ClinicalReportExtractorLite` outside the signed app bundle.
- Runtime configuration now has a tested `app.runtime_config.RuntimeConfig` seam. The supported `local` profile reports only `deployment_profile=local` and `database_backend=sqlite`; `COMPANION_DEPLOYMENT_PROFILE=central` fails closed with an explicit PostgreSQL-adapter diagnostic instead of silently starting a multi-writer SQLite deployment.
- SQLite connection setup, schema bootstrap, compatibility-column upgrades, indexes and synthetic demo-account seeding now live in `app.persistence.Database`; `main.py` imports this persistence seam and retains the same HTTP behavior.
- The application factory adds baseline security headers (`nosniff`, `DENY`, no-referrer, restrictive permissions and same-origin CSP). After the frontend extraction, `script-src` is same-origin only and no longer permits inline workbench JavaScript.
- The workbench stylesheet and behavior bundle are served as `/static/css/app.css` and `/static/js/workbench.js` with no-store headers. The bundle keeps compatibility handler names while the page contains no inline script; packaged builds collect the whole `app/static` directory.
- The local SQLite repository now includes a durable `recognition_jobs` / `recognition_job_items` ledger. It snapshots source-file IDs, subject/visit, selected fields and the Kimi preference without storing raw bytes or credentials; role-scoped create/list/detail/cancel/retry routes preserve audit history.
- `POST /api/recognition-jobs/{id}/run` is a bounded caller-triggered recovery bridge into the existing local PDF/OCR/Kimi extraction handlers. It updates each item independently and never writes LibreClinica; a distributed worker remains a later qualification target.
- The workbench now projects the latest role-scoped durable recognition job in a single-page panel. Refresh restores the job after reload, while run, cancel and retry actions remain explicit caller-triggered controls; per-file status and sanitized errors stay visible without introducing Redis/Celery.
- Recognition-job execution is now single-flight at the SQLite state boundary: an atomic claim rejects duplicate `/run` calls with `recognition_job_already_running`, and `/cancel` cannot race an active run or mark running extraction as cancelled. The browser disables run/cancel during active extraction.
- Candidates require human review before an immutable transfer package can be created and explicitly submitted.
- LibreClinica availability is never an intake gate: upload, local recognition, human review and reviewed-recognition Excel export continue while Authority subject/visit provisioning is deferred. Explicit Authority submission retries deferred provisioning before the clinical-value write.
- All current data and infrastructure are synthetic localhost qualification artifacts, not clinical records or a production deployment.

## Current capabilities

- Kimi K3 is now enabled by default at the configuration seam. A missing
  recipient-local key reports `kimi_integration=key_required` and remains
  fail-closed; `KIMI_ENABLED=false` is still an explicit local-only opt-out.
- Centres without hospital EDC connectivity can export a passphrase-protected
  AES-256-GCM `clinical-edc-reviewed-package-encrypted` envelope containing
  only human-confirmed pseudonymous values. A central data manager can batch
  import up to 100 files through `/api/imports/reviewed-packages`; each file is
  SHA-256 checked, dictionary-version checked, duplicate-protected and logged
  with bounded failure details. Plain JSON imports are rejected.
- Package construction collapses exact historical duplicates to the latest
  review timestamp but blocks same-source conflicting values with
  `offline_package_conflicting_record`; never auto-resolve a clinical conflict.
  A 2026-08-14 SITE_B synthetic interface drill verified encrypted export,
  first central import and second-import duplicate rejection.

- Multi-image upload, redaction preview, local OCR/Kimi hybrid extraction and candidate provenance.
- The intake workbench has a session-only multi-subject queue: each file snapshots its own pseudonymous subject, visit, recognition scope and Kimi preference before upload; one batch then prepares and recognizes all queued reports, and pending candidates are grouped by subject/visit for review. The HTTP and database contracts remain item-level and unchanged. The queue behavior is now in the external `workbench.js` module rather than the HTML document.
- Upload preparation now persists a resumable recognition job before the queue is cleared. This preserves each queued file's subject/visit/scope/Kimi snapshot and prevents a cleared client queue from losing the server-side recognition context.
- Accept/edit/reject review plus two always-enabled current-batch bulk actions and append-only audit events. Both current-batch actions include every non-BLOCK pending candidate, including `conflict` and `kimi_only`, after the reviewer explicitly clicks. Empty groups return visible no-op messages; quality BLOCK and transfer holds remain fail-closed.
- LibreClinica subject provisioning, visit scheduling, frozen package submission and reconciliation ledger.
- Central-manager display-header management for the original 164 source columns plus 21 pulmonary-function workbook headers projected across four visits (239 dictionary rows total).
- Local pulmonary-function PDF intake maps 18 measured fields per selected visit, including `REF` as the workbook label for report `PEF`, and still requires human review.
- Role-scoped one-click Excel export of submitted values.
- Reviewer-scoped recognition-field selection is loaded from the active visit dictionary. A batch snapshots the chosen codes, supports all/pulmonary-only/custom scope, and filters PDF plus hybrid OCR/Kimi candidate creation before persistence.
- The primary workbench Excel action exports only actually recognized, human-confirmed fields and labels aggregate LibreClinica submission state. The submitted-only export endpoint remains available separately for authority-confirmed workflows.
- Deterministic quality rules, companion data issues, effective transfer holds and state-hashed visit attestations.
- Structured CSV import, centre-scoped dashboard/tasks, searchable audit, immutable dictionary releases and analysis snapshots.
- Central account lifecycle controls for synthetic investigator/monitor/auditor accounts; production provisioning remains blocked pending an approved identity provider.
- SQLite online backup with SHA-256 and verified temporary restore evidence surfaced through fail-closed readiness gates.
- Portable startup performs an application-level backup/restore check for an
  existing database; `GET /api/security/disk-encryption` reports the local
  BitLocker/FileVault preflight and the Chinese centre-package runbook covers
  operator enablement and explicit retention cleanup.
- Only `principal_investigator` and `central_data_manager` are global repository
  roles; centre accounts are unique `site_investigator` users bound to a unique
  centre code.
- Light clinical-operations workbench with a navy command header at
  `http://127.0.0.1:8000/`.
- The confirmed-transfer workbench uses a pending-first single-column list, shows five records by default and exposes an accessible expand/collapse control for additional records.
- A Windows x64 PyInstaller onedir package includes the Python app, static/config assets, OCR/Tesseract runtime, openpyxl export fallback, pinned offline LibreClinica/PostgreSQL/MailCrab images and a subject-free synthetic study seed. `Start-Clinical-EDC.cmd` is the recipient entry point; after a recipient Kimi key is entered it starts both localhost applications and enables the SOAP adapter.
- A separate `ClinicalReportExtractorLite` Windows x64 onedir package includes only the companion app, local PDF parser, OCR/Tesseract runtime and Excel exporter. The icon-bearing `Start-Clinical-EDC-Lite.exe` is its only root start entry and infers Lite mode from its packaged name; `compatibility/Start-Clinical-EDC-Lite.cmd` is the secondary command entry point. Docker Desktop, WSL2, Linux, LibreClinica and Python are not required, and Kimi remains optional.
- Centre-specific Windows Lite packages carry one non-secret versioned profile and seed exactly one locked `site_investigator`. First-run setup uses browser-generated randomness and stores only a salted scrypt hash; no password, central account, other-centre account, database or runtime data enters the ZIP. The builder black-box tests a freshly extracted archive through setup, PDF review, Excel and encrypted centre-package export.
- Centre Lite users can now configure or replace their recipient-local Kimi key from the authenticated web workbench. The endpoint writes the launcher-owned `.runtime/kimi-api-key.txt` atomically with current-user-only permissions, hot-reloads the existing Kimi client and returns status only; the key never enters SQLite, audit details or HTTP responses.
- Centre first-run setup now stops at a one-time credential receipt with copy/download actions instead of logging in immediately. `Reset-Centre-Password.cmd` rotates a lost password locally, revokes sessions and prints the replacement once. The centre-package blackbox covers both web Kimi configuration and the reset command.
- Centre-package launcher reuse now validates `product_mode` plus the exact centre code and username from `/api/health`. If port 8000 belongs to the full product, another centre or an unrelated process, the requested centre package selects the next bounded free localhost port instead of opening the wrong UI.
- Recognition-job items persist the exact candidate IDs returned by successful extraction. The workbench restores the latest batch from those IDs before rendering candidates after login; succeeded legacy jobs derive the same relation only from exact centre, subject, visit, field and original/confirmed-derivative source lineage. This keeps both bulk-review controls usable after refresh without weakening quality BLOCK, role, centre or transfer-hold gates.
- The in-page de-identification confirmation path restores the active batch directly from each completed recognition-job item's persisted `candidate_ids` before refreshing candidates. Do not reconstruct image batches by comparing the original source-file ID with candidate source IDs: image candidates belong to the confirmed de-identified derivative, and that mismatch empties both bulk-review groups even when Kimi correctly falls back to local OCR.
- The 2026-08-14 icon-bearing rebuild passed 165 automated tests and fresh-extraction black-box setup, missing-key Kimi-to-local-OCR fallback, one fallback plus 18 pulmonary candidates, bulk human review, web Kimi configuration, reviewed Excel and encrypted-package export. The blackbox starts the named EXE without `--lite` to verify real double-click profile inference. Hidden files are included in both forbidden-artifact scans and `MANIFEST.sha256`; the compatibility CMD is a visible manifest-covered file under `compatibility/` because Windows `Compress-Archive` omits hidden files. Generic Lite SHA-256 is `723d10044f492058fba85ac25b0c6637d45eedd0b987c57316710b86a009d246`; SITE_A is `cc52d15528afcc01df8a3c0ff6139501cc08604407e2a573948acb015f1b9f8e`; SITE_B is `b54fbd3ce37c85d91a0d13514ccfa8c8c77a0c0bbd5f3b91c098ed719ef656e6`.
- Bulk review now preserves an active batch while any of its candidate IDs are pending, then advances to the newest recognition job that still has pending candidates. This prevents a fully reviewed newest job from stranding older candidates behind item-level buttons after login, refresh or a prior bulk accept. A three-job browser blackbox accepted the middle job through “review-needed” and automatically advanced to accept the oldest job through “without item-by-item review”; pending count moved `2 -> 1 -> 0`. The versioned UI token is `20260814-pending-batch-v2`. The subsequent 165-test and fresh-extraction rebuild supersedes the hashes above: generic Lite `d5e350595790f24333d6e4fd7ba9774702fd5e3803420be7c2a578f05f9f828b`, SITE_A `b7569666d2703406f06b89a1dff3d287fb0f5da62684823edde5920a0b5a7b44`, SITE_B `d7ff5c832dd6427b7bab0a42b0b378aaa505f9e48c89b4de025da65a266c5e9c`.
- A second 2026-08-14 regression found that legacy succeeded recognition items could persist the JSON value `[]`, which the prior compatibility path treated as authoritative even though linked pending candidates still existed. Both SQL `NULL` and JSON `[]` now trigger the exact lineage recovery query; non-empty stored arrays remain authoritative. The browser blackbox used a real `[]` row and verified “accept review-needed items” changed pending `1 -> 0` with one confirmed record and an audit event. Full verification passed 166 tests. Current rebuilt hashes supersede earlier Lite hashes: generic `6ba4ed42522f574bf94ddefc4341cafcaaeb0b8a780d8a77e536478a631f5e9c`, SITE_A `9764d0b4b123503a01a8a90fe5c00346f45a04de0ec02c77d18cfa649523494b`, SITE_B `2b71958043c5193a0ec77939683a9fba040568dddb5e5f441048ea4a60a6a766`.
- The bulk controls were also exposed before the asynchronous login candidate/quality refresh completed. An immediate click therefore computed an empty group, emitted a no-candidate warning, and left the candidates actionable when they appeared seconds later. Both bulk handlers now perform one bounded recognition-job plus candidate refresh when their first projection is empty, recompute the requested group and continue the same click. A local-only, Kimi-disabled test with an approved report image verified the red state (`0` at click, then `7` pending) and the fixed state (the same immediate click confirmed all `7` with `7` bulk audit events); all isolated original/derivative/database copies were then removed. UI token is `20260814-bulk-click-refresh-v3`; 166 tests passed. Current hashes supersede prior Lite hashes: generic `7abb1722e3de85ff12b27fea3f46c20934f52ee4de7b52aa24bc41b1cb9bee34`, SITE_A `15aa59ccc6c2d9cb0a35a6b639fdb5686d908ac6b42a4d229b8c48e98be8c791`, SITE_B `f8e5b50b2fdcecd7aa55acd7f95121250a117bf0b2025a5dc53271f9c7b00e0a`.
- The Kimi batch-accept repair aligns the bulk endpoint with the existing individual reviewer decision: explicit bulk actions accept all current-batch non-BLOCK candidates, including `conflict` and `kimi_only`. The local derivative redactor now also covers clinical staff labels/signatures and collection, receipt and review timestamp lines before visual confirmation. A real Kimi K3 black-box using a confirmed derivative produced 17 candidates (6 agreement, 11 Kimi-only); the browser “accept review-needed items” action confirmed 17/17, skipped 0 and wrote 17 bulk audit events. Test copies of the original, derivative and database were removed after verification. UI token is `20260814-kimi-bulk-all-v4`; 169 tests passed. Current hashes supersede prior Lite hashes: generic `146eca451f3285bcf226192170c397f29a1df8db6825c1cfd3838e1394f11a14`, SITE_A `46102a8c4fd4e709d71c7fd3b8db04f200084b4be1b1e7925b373cf4d954166e`, SITE_B `80f6ce089c8d3d6d9aa112415f450b6591f12dee0bc4b75ff6618bd406a440b7`.
- The Windows Lite icon uses one audited Dreamina 5.0 submission (3 credits) as its conceptual source. The provider-labelled source is preserved with a credential-free ledger; the delivery SVG/PNG/ICO is a text-free, patient-free simplified derivative verified at 16–256 px and embedded directly in the launcher EXE.
- The patient upload queue now re-renders when recognition fields finish loading. This fixes the disabled `加入病人队列` action caused by the initial empty-state render. Public-screen initialization also refuses to re-show the login card after a faster login completes.
- Native macOS Lite packaging targets separate `arm64` and `x86_64` `.app` bundles. The recipient installs no Python/Tesseract/container runtime; external frictionless distribution still requires the owner's Apple Developer ID and Apple notarization.
- The portable seed preserves the synthetic study, event/CRF/item metadata and predefined roles while containing zero subjects, event CRFs, item values, login audit rows or sender password hashes. LibreClinica creates a random recipient-local password, stores the browser copy with Windows DPAPI and stores only the legacy SOAP SHA-1 digest in the ACL-restricted adapter file.

## Known boundaries and lessons

- On 2026-08-14 the distributor stated that ethics and the data-flow review
  are approved before distribution. Keep that as an operator prerequisite;
  technical production readiness remains BLOCK until the qualified shared
  repository, institution identity/MFA, backup/restore and validation gates
  are evidenced.

- Public Kimi terms do not provide a zero-retention or no-training guarantee. Real participant images remain blocked without an approved agreement and data-flow review.
- OCR and automated redaction are aids, not proof of accuracy or de-identification. Preserve evidence and require human confirmation.
- A successful interface response is not sufficient proof of final EDC state; read-back reconciliation is the preferred next control.
- The qualified LibreClinica SOAP surface may report clinical-value read-back as unsupported; mismatch/unsupported states must stay visible and never be converted to success.
- Companion issues, attestations and transfer holds do not replace LibreClinica Query, SDV, electronic-signature, freeze or lock workflows.
- The supplied workbook has 164 columns: one subject label, 161 CRF items and two direct-identifier exclusions.
- `肺功能.xlsx` has 21 headers: 18 candidate fields, two direct-identifier exclusions and one source-report identifier exclusion. These pulmonary fields are companion-only until matching LibreClinica CRF items and verified OIDs are installed; Authority submission must fail closed meanwhile.
- Text-layer PDF extraction uses `pypdf`; encrypted, malformed, textless, over-five-page and unsupported-layout PDFs fail closed. Scanned-image PDF fallback is intentionally not implemented.
- PyInstaller is not a cross-compiler. Windows can validate the shared code and produce a credential-free macOS build-source ZIP, but each macOS application artifact must be built and black-box tested on a matching native Mac runner. Ad-hoc signing is internal QA only.
- A Windows `.cmd` cannot carry an embedded icon. A `.lnk` experiment was rejected after the copied-path black-box resolved back to the build machine's absolute target; use the icon-bearing `Start-Clinical-EDC-Lite.exe` instead of shipping a path-dependent shortcut.
- A browser may keep the pre-PDF inline workbench after an application update, and drag-and-drop may report a PDF as `application/octet-stream`. The homepage now sends no-store headers, Windows launchers open a versioned UI entrypoint, and generic-MIME PDFs are accepted only when both the `.pdf` suffix and `%PDF-` signature match.
- Human-confirmed companion values can legitimately remain absent from a submitted-only workbook when LibreClinica mapping or submission has not completed. Keep reviewed-recognition and submitted-only exports distinct, label authority state explicitly, and derive reviewed workbook columns from actual recognized fields rather than the full dictionary.
- Store only a stable sanitized LibreClinica provisioning error code on deferred source files. Display the report as locally ready, preserve accepted values as `not_submitted` in the reviewed workbook, and fail only the explicit Authority submission when the service remains unavailable.
- LibreClinica release naming and embedded `1.4.0rc1` metadata remain a production qualification warning.
- Docker Desktop is not redistributed: its current subscription agreement restricts third-party transfer and the recipient must install it, accept its terms and meet subscription eligibility. The archive contains the product's offline Docker images, not the Docker Desktop installer.
- A recipient machine exposed an opaque `dockerDesktopLinuxEngine ... 500` because Docker Desktop could not detect virtualization. The portable launcher now runs a locale-independent firmware/hypervisor, SLAT, Windows-feature, WSL and Docker-engine preflight before Docker operations, emits stable `EDC-HOST-*` remediation codes and writes a credential-free `.runtime/portable-host-diagnostic.json`.
- On hosts where Hyper-V is already active, `Win32_Processor.SecondLevelAddressTranslationExtensions` may report false; `HypervisorPresent=true` takes precedence to prevent a false SLAT block. Native Docker stderr is captured through temporary redirected files and reduced to a category so raw named-pipe errors do not escape.

## Non-secret operations

- The external-review baseline is `docs/external-app-review-guide.zh-CN.md`.
  It inventories current features, architecture, roles, core code entry points,
  data tables, API groups, security controls, 169-test evidence, current Lite
  hashes and prioritized review risks. It explicitly records that the source
  folder has no Git history or project-level LICENSE and that the 2026-08-11
  integrated Windows ZIP predates the latest 2026-08-14 bulk-review fix.
- Kimi and LibreClinica credentials are stored only under ignored `.runtime/` files with restricted local access. Do not copy their values into code, logs, documentation or this file.
- The centre web Kimi status proves that a bounded key was stored and the local model/base-URL allow-list is valid; it does not make a provider network call. Provider authentication or connectivity errors remain bounded extraction-time failures with local OCR fallback.
- Start the workbench with `scripts/start_companion_live.ps1`; it replaces only an existing matching project Uvicorn process on port 8000.
- Start/validate the localhost EDC with `scripts/validate_libreclinica_sandbox.ps1 -Start -UseCachedImages` when Docker Desktop is available.
- Create restore-checked local evidence with `scripts/backup_companion_database.ps1`; the live launcher and health endpoint use `.runtime/backups`.
- Rebuild and self-test the transferable folder/ZIP with `scripts/build_windows_portable.ps1`; the build verifies fail-closed raw-EXE behavior, four OCR values, Excel export, a clean LibreClinica restore, Kimi/adapter readiness, synthetic subject provisioning, human review, SOAP submission and authority database read-back before writing the archive and verification report.
- Rebuild and self-test the Docker-free recipient ZIP with `scripts/build_windows_lite.ps1`; it generates an identifier-free pulmonary PDF fixture, verifies 18 local candidates, human review and reviewed-value Excel export, then writes `dist/ClinicalReportExtractorLite-windows-x64.zip` and its sibling verification report.
- On a matching Mac, build and self-test an architecture-specific app with `TARGET_ARCH="$(uname -m)" bash scripts/build_macos_lite.sh`; optional `MACOS_CODESIGN_IDENTITY` and `MACOS_NOTARY_KEYCHAIN_PROFILE` reference local Keychain material without storing secrets in source.
- From Windows, `scripts/build_macos_source_bundle.ps1` writes `dist/ClinicalReportExtractorLite-macos-build-source.zip`; this is a build handoff, not a recipient application. The checked-in GitHub Actions workflow defines native Apple Silicon and Intel jobs for a future private repository.
- The PyInstaller spec explicitly collects `pypdf`, and the portable build copies its license. A focused packaged-EXE check on port 8011 parsed the representative pulmonary PDF into 18 local candidates without a remote model call.
- Current integrated artifact: `dist/ClinicalEdcCompanion-windows-x64.zip`; its verification report is `dist/ClinicalEdcCompanion-windows-x64.verification.json`. Always report the hash from the current build output rather than relying on this memory.
- Recipient troubleshooting entry points are `Diagnose-This-PC.cmd` and the explicit elevated `Repair-Docker-Prerequisites.cmd`. The latter enables WSL/Virtual Machine Platform and hypervisor startup but cannot enable BIOS/UEFI virtualization or VDI nested virtualization.
- `Start-Clinical-EDC.cmd` now starts an installed but stopped Docker Desktop and polls the sanitized Linux-engine probe for up to 180 seconds. It prefers the supported Desktop CLI, falls back to documented per-user/all-users executable locations, and leaves Docker's first-run agreement visible for the recipient.
- Windows PowerShell 5.1 promotes some native stderr to terminating `NativeCommandError` under the launcher's fail-fast policy. Expected missing-image/database-readiness probes and normal Compose progress therefore run through `Invoke-PortableProcessQuiet`, which redirects native output and returns only a bounded exit code/category. A 2026-08-11 clean-host blackbox removed the LibreClinica image, restored it from the bundled offline archive, then reached companion `status=ok` and `edc_adapter=libreclinica_soap`.

## 2026-08-17 external audit remediation

- Default bulk review is deliberately narrow again: only `agreement`,
  `local_only`, and `local_fallback` candidates may be accepted without
  item-by-item review. `conflict` and `kimi_only` require protected evidence,
  an explicit source choice, and evidence acknowledgement. Quality `BLOCK`
  and unknown extraction states never pass, including through override.
- A central-only API override exists for exceptional bulk review, but requires
  a written reason, explicit evidence identifiers, and a source decision. The
  browser workbench does not expose this as an ordinary shortcut.
- Candidate review audit events now distinguish `individual` and `bulk`, record
  the selected source and evidence reference, and participate in a canonical
  SHA-256 hash chain. Verification and external-anchor endpoints, backup and
  reviewed-package anchor checks are fail-closed. The chain detects mutation
  and deletion but is not WORM storage; anchors must be exported to independent
  approved storage for stronger tamper evidence.
- SQLite connections use WAL, foreign keys, a 30-second connection timeout and
  a 5-second busy timeout. Interrupted recognition work is marked failed on
  restart with stable evidence rather than remaining indefinitely queued or
  running.
- PNG/JPEG uploads now require matching signatures and successful bounded image
  decoding. PDF uploads receive signature, EOF, indirect-object, nesting,
  size, and page checks. Tesseract uses a temporary output file with timeout and
  output-size limits. These controls reduce parser exposure but do not replace
  helper-process sandboxing for production document ingestion.
- New centre packages use per-package salts/nonces and scrypt `N=2^17`, while
  remaining able to read earlier `N=2^15` packages. Audit anchors are
  authenticated inside reviewed packages and their AAD.
- Legacy demo password hashes are accepted only in development/test without a
  centre profile and are immediately upgraded to scrypt after successful
  login. Production rejects them.
- Old distributable files were moved under
  `dist/outdated-before-review-gate-2026-08-17/` and must not be distributed.
  No replacement recipient build was produced by this remediation pass.
- Verification passed 204 tests, JavaScript syntax checking, `uv lock --check`,
  and desktop/mobile browser review of the conflict-evidence flow. One upstream
  Starlette TestClient/httpx deprecation warning remains.
- Production release remains blocked on project licensing and Git provenance,
  institutional public-key lifecycle/signature decisions, a qualified central
  multi-writer database, an approved PI/delegation role model, independent
  audit-anchor retention, and a rebuilt black-box-tested recipient artifact.
  Track these explicitly in
  `docs/release-governance-blockers-2026-08.md` rather than inferring policy in
  code.

## 2026-08-18 workbench visual redesign

- `design-system/clinical-edc-companion/MASTER.md` is the visual source of
  truth. The workbench uses a light clinical-operations palette, navy command
  header, system fonts, inline SVG and semantic status colors. Remote fonts,
  UI frameworks and animation runtimes remain intentionally absent so portable
  offline startup and the same-origin CSP are unchanged.
- The authenticated page adds same-page workflow navigation. Operations and
  encrypted data-exchange controls are native `details` disclosures; the
  recognition-field selector is collapsed by default. Navigation opens a
  targeted disclosure before scrolling but does not add routing or shared
  state.
- Existing DOM IDs, API payloads, review gates, role scopes and audit behavior
  are unchanged. Presentation acceptance covers 375 portrait, 812 landscape,
  768, 1024 and 1440 CSS-pixel viewports, visible keyboard focus, 44-pixel
  targets, reduced motion, no page/session overflow and no console warnings.
- Verification passed 204 tests, JavaScript syntax checking, `uv lock --check`
  and browser interaction/visual regression. The existing upstream
  Starlette/httpx deprecation warning remains.

## 2026-08-18 role-aware central and site workspaces

- The authenticated browser now projects one shared DOM as `central`, `site`
  or `oversight` from the server-authenticated role. The research run strip is
  the visual signature and states the workspace, centre scope, operational
  focus and permission boundary before any workflow action.
- Central data managers land on the open central operations view and retain
  write-authorized intake, cross-centre review and dictionary navigation. Site
  investigators land on centre-bound report intake. The principal investigator
  receives central read/oversight navigation without intake or the write-flow
  stepper; monitor/auditor projections use explicit read-only wording.
- Role projection changes labels, default disclosures and presentation only.
  Existing section IDs, API contracts, server authorization, centre scoping,
  review policy and audit behavior remain unchanged; hidden UI is never an
  authorization control.
- `design-system/clinical-edc-companion/pages/workbench.md` is the page-specific
  visual override. The selected guidance set is recorded in
  `docs/ui-skill-selection-2026-08.md`: installed `ui-ux-pro-max` remains the
  primary design system, with Anthropic `frontend-design` and Vercel Labs
  `web-design-guidelines` added as design and audit references.
- Browser QA covered SITE_A at 1280 and 375 CSS pixels, central data management
  at 768 pixels, principal-investigator projection, same-page navigation,
  44-pixel controls, no page overflow and an empty console warning/error log.
  Verification passed 204 tests, JavaScript syntax checking and
  `uv lock --check`; the existing Starlette/httpx deprecation warning remains.

## 2026-08-22 Dreamina-assisted workbench assets

- Dreamina is a development-time visual provider only. Two model-5.0 2k source
  images cost six credits and produced three audited shipping derivatives:
  central/oversight context, site report-intake context and candidate-review
  empty state. The empty-state derivative is a crop of the central source after
  a separate provider request repeatedly timed out before task creation.
- Provider source marks were removed only by fixed geometric crop; there was no
  inpainting or semantic edit. Shipping WebP files contain no people, patient
  data, readable text, hospital marks or clinical images and total about 45 KB.
  Prompts, credential-free task metadata, SHA-256 values and human review are
  recorded under `packaging/assets/generated/dreamina-workbench/`.
- The application serves only three explicitly allow-listed `/static/img/`
  filenames. It does not expose a general static directory and has no runtime
  Dreamina SDK, API call, provider URL, credential or feature flag.
- Context art is decorative, has an empty accessible name and never determines
  role, status or authorization. Role projection selects a closed local asset;
  narrow mobile layouts hide context art, and the review illustration appears
  only when the candidate collection is empty.
- Browser QA covered central and site views at 1440, 1024, 768 and 375 CSS
  pixels with correct asset selection, successful image decoding, no page-level
  horizontal overflow and no frontend error logs. Verification passed 204
  tests, JavaScript syntax checking, Python compilation and `uv lock --check`;
  the existing Starlette/httpx deprecation warning remains.

## 2026-08-22 production architecture tranche 1

- ADR 0007 fixes a modular monolith with two deployment shapes: centre Lite
  keeps local SQLite, while central web must use a separately qualified
  PostgreSQL repository and institutional identity. Central mode remains
  fail-closed; it must never silently reuse SQLite.
- `app/main.py` remains the composition root. Closed static delivery moved to
  `app/api/static_delivery.py`; local HTTP authentication moved to
  `app/api/authentication.py`; framework-free credential/session behavior moved
  to `app/local_auth.py`. Public paths, role checks, eight-hour sessions and the
  legacy-demo credential-upgrade audit event are unchanged.
- `app.version.__version__` is the package/runtime version source and is
  currently `0.2.0.dev0`. SQLite now records converged schema version 1 in
  `schema_migrations`; `/api/health` exposes application and schema versions
  without disclosing paths or credentials.
- Python package data explicitly includes only the workbench HTML, CSS,
  JavaScript and approved WebP assets. The verified wheel contains all six
  closed static artifacts; do not replace this with a general project-tree
  include.
- Verification passed 205 tests, Python compilation, wheel construction and
  live localhost health/page checks. The live service reported Kimi ready and
  the LibreClinica SOAP adapter selected. The upstream Starlette/httpx
  deprecation warning remains.
- The root license and Git baseline were completed in the subsequent governance
  tranches. PostgreSQL migration tooling must be added only with the first
  executable central repository slice, not as an unused parallel schema source.

## 2026-08-22 canonical root and private Git baseline

- `C:\ClinData Relay` is the canonical development root. The former Codex
  workspace is retained only as a rollback copy and must not receive new
  project changes.
- The canonical root was created as a clean source copy. It excludes `.runtime`,
  local databases, uploaded or derived reports, API keys, credentials, backups,
  virtual environments, build output, distributions, scratch work, bundled
  third-party binaries and Docker release artifacts.
- The private GitHub repository is
  `https://github.com/KR0817/clin-data-relay`. It remains private under the
  later owner-approved proprietary license; any public source release requires
  explicit relicensing and a separate release review.
- A fresh Python 3.12 environment was created from `uv.lock` in the canonical
  root. Python compilation, JavaScript syntax checking and 205 tests passed;
  `uv.lock` was refreshed to record the dynamic `0.2.0.dev0` package version.
- Existing Kimi and LibreClinica secrets were deliberately not migrated. They
  must be configured again through approved local runtime setup if the new
  checkout is used as the live service.
- `.github/workflows/quality.yml` is the required source CI gate for pushes and
  pull requests. It recreates the frozen Python 3.12 environment and runs
  compilation, JavaScript syntax and the full pytest suite without secrets.
- First-party GitHub Actions use major version 7 for checkout, Python, Node and
  artifact upload. The initial v4/v5 run passed but emitted GitHub's Node 20
  deprecation warning, so those majors must not be restored.

## 2026-08-22 Kimi settings module extraction

- `app/api/kimi_settings.py` owns the validated local-key payload, redacted
  capability status and `GET|PUT /api/settings/kimi` router. `app/main.py`
  remains the composition root and reuses the same status projection for
  `/api/health`; the clinical extraction pipeline is intentionally unchanged.
- Eligibility is unchanged: only the authenticated investigator bound to the
  Lite centre profile can use the settings interface. The API key is written to
  the configured local credential file and is never stored in SQLite, audit
  details, logs or HTTP responses.
- The `kimi_credential_configured` audit event records only the selected model.
  Its test now asserts both the exact audit payload and absence of credential
  material.
- Router-factory dependencies use explicit `Depends(current_user)` defaults.
  With postponed annotations, an `Annotated` dependency referring to the local
  factory parameter cannot be resolved by FastAPI when routes are registered.
- Verification passed Python compilation, JavaScript syntax checking,
  `uv lock --check`, 205 tests and a live localhost health/page smoke test. The
  existing upstream Starlette/httpx deprecation warning remains.

## 2026-08-22 proprietary source license

- The owner selected the root proprietary license with `Copyright (c) 2026
  Xinbo Yu`. The private GitHub repository remains private; source access or
  distribution requires separate written authorization and is not open source.
- The license permits only the sites, period, systems, protocol and purposes in
  the owner's written authorization. It does not replace ethics, privacy,
  security, validation, data-flow or institutional approval and does not grant
  rights to participant data.
- Third-party components retain their own licenses. A future public source
  release requires an explicit relicensing decision and a new release review.

## 2026-08-22 PostgreSQL repository bootstrap

- `app/postgres_repository.py` is the first executable PostgreSQL seam. It owns
  DSN policy, connection handling, a transaction-scoped advisory migration
  lock, the `companion_schema_migrations` ledger and a redacted immutable
  status. It deliberately creates no clinical or participant-data table.
- Psycopg 3 is isolated in the optional `central` dependency group. Centre Lite
  and the current SQLite application do not import it or gain a PostgreSQL
  runtime prerequisite.
- Production-like environments require `sslmode=verify-full`; development and
  test may use non-verifying TLS only on localhost or a Unix socket. Provider
  exceptions and connection material are reduced to bounded error codes.
- `scripts/check_postgres_repository.py` is the operator/developer preflight.
  Success proves connection, PostgreSQL 16-or-newer compatibility and migration
  privileges only; `clinical_data_ready` stays false and central application
  startup remains fail-closed.
- The source-quality workflow has a separate Ubuntu/PostgreSQL 16 contract job
  with a run-specific ephemeral credential. Local verification passed 207
  tests with the two service-backed cases skipped because the workstation
  Docker engine and PostgreSQL client were unavailable.

## 2026-08-22 atomic package-import ledger

- `app/package_import_repository.py` is the database-neutral domain boundary
  for encrypted centre-package receipt claims and bounded append-only attempt
  logs. The active HTTP application composes its SQLite adapter; centre Lite
  gains no PostgreSQL dependency.
- The route's early duplicate lookup is only an optimization. The authoritative
  claim now occurs inside the same SQLite transaction as source metadata,
  imported candidates, audit/quality rows and the successful import log. A
  stale pre-check therefore produces the existing 409 duplicate response and
  cannot create a second candidate set.
- PostgreSQL schema version 2 adds receipt and attempt-log metadata tables under
  the existing advisory migration lock. The PostgreSQL adapter has the same
  claim/find/append/list contract and is exercised by the service-backed CI
  job. It stores no package bytes, passphrases, images, identifiers or clinical
  values, so `clinical_data_ready` remains false and central HTTP stays BLOCK.
- Local verification passed 210 tests with three PostgreSQL service-backed
  cases skipped on this workstation, plus Python compilation, JavaScript syntax
  checking and `uv lock --check`. The upstream Starlette/httpx deprecation
  warning remains.
