# ClinData Relay

ClinData Relay is the image/OCR/Kimi clinical-data companion described in the
architecture plan. It is not an EDC. Development and automated validation use
synthetic localhost data; its LibreClinica connection remains an interface
qualification boundary until the required institutional controls are complete.

## What runs now

- investigator demo accounts scoped to `SITE_A` and `SITE_B`, a central data-management role, and centrally provisioned read-only monitor/auditor roles; the former entry-only accounts are inactive and retained only as historical audit identities;
- source-image/PDF provenance with a SHA-256 digest and synthetic-or-approved-local-use attestation;
- candidate creation, human accept/edit/reject, split current-batch confirmation for recommended versus other reviewable candidates, and append-only audit events;
- an inline reviewer panel for accept/edit/reject and manual reconciliation, avoiding browser-native prompts while preserving explicit reason entry and server-side role checks;
- a fail-closed Authority-EDC boundary with a frozen canonical JSON package, deterministic request replay protection, a separately hashed immutable request receipt, and package-integrity verification immediately before any network call;
- a LibreClinica 1.4 SOAP/ODM adapter that is disabled by default, uses a dedicated Web Service account, resolves the study-subject OID through the supported SOAP service, and imports only approved event/form/group/item OIDs;
- an independently gated upload-time provisioning seam which, when explicitly enabled for the localhost sandbox, idempotently creates a pseudonymous research code and schedules the selected mapped visit before the source image is registered;
- a centre-scoped reconciliation ledger with `queued`, `submitting`, `submitted`, `failed`, and `reconciled` states, structured errors, explicit failed-record requeue, cumulative attempt/retry counts, reviewer-only manual reconciliation, Authority-EDC references and response hashes;
- a public adapter-readiness endpoint that performs a read-only authenticated LibreClinica probe before displaying `ready`;
- a local Tesseract OCR endpoint for attested synthetic laboratory-report images, which parses both `field: result unit` and `field result reference-range unit` and can remain fully local when Kimi is disabled;
- a local text-layer PDF parser for pulmonary-function reports, backed by the 21 headers in `肺功能.xlsx`; it creates 18 measured-value candidates, excludes name/hospital/test identifiers and never calls Kimi;
- a local de-identification draft workflow that uses OCR bounding boxes to cover entire lines containing known direct-identifier labels, strips image metadata by producing a new PNG, serves the derivative preview only through an authenticated non-cacheable endpoint, and requires an explicit human-review attestation before the derivative may enter local OCR;
- a conservative Chinese laboratory-table fallback that runs only when plain OCR has no mapped English codes, uses versioned exact labels and word coordinates, rejects conflicting values and ambiguous count/percentage concepts, and never infers a missing unit;
- a server-side Kimi K3 multimodal adapter that is enabled by default at the configuration seam but remains fail-closed until the recipient enters a local key. It accepts only a human-confirmed de-identification derivative plus local OCR evidence and the active visit's versioned CRF field dictionary, enforces strict structured output, and records agreement/conflict/fallback provenance;
- deterministic `PASS|WARN|BLOCK` quality checks, companion data issues, visit/subject/centre/dataset transfer holds, and append-only visit attestations that become invalid after candidate-state changes;
- bounded UTF-8 CSV import that validates the complete file before persisting normal review candidates, reports ignored headers, and retains only a source hash and provenance;
- centre-scoped dashboards and tasks for issue responses, failed transfers and read-back mismatches;
- draft/publish/rollback dictionary releases, immutable analysis snapshots with SHA-256 verification, and searchable role-scoped audit events;
- one-click, role-scoped Excel export of submitted values with formula-injection-safe string handling and a packaged openpyxl fallback;
- a Windows x64 PyInstaller onedir distribution with the local OCR runtime, integrity manifest, recipient setup guides and no copied credentials or runtime database;
- Windows x64 centre-specific Lite ZIPs that contain one centre profile, require local first-run password setup and exclude central/other-centre accounts from the runtime repository;
- a compact responsive browser workbench at the root page, including central account lifecycle and dictionary controls.

The browser can first call `/api/source-files/{source_file_id}/deidentification-drafts`, display the authenticated derivative, and confirm the draft through `/api/deidentification-drafts/{draft_id}/confirm`. Confirmation only records that the operator viewed the redacted derivative; it is not candidate review and does not prove that every identifier was detected. The original upload is never modified, automatically deleted, or sent to Kimi. An unconfirmed derivative is rejected by both local and hybrid extraction.

The browser's batch recognition step calls `/api/source-files/{source_file_id}/hybrid-extract` only after an image de-identification derivative is confirmed. Pulmonary-function PDFs use `/api/source-files/{source_file_id}/pulmonary-function-extract`, remain local and bypass Kimi. Candidate persistence is guarded by the versioned `WEEK_0`, `WEEK_4`, `WEEK_8`, and `WEEK_12` source-header mapping. Agreement, conflict, Kimi-only, local-only and provider-fallback states remain visible in candidate provenance. Repeating the same source/event request returns the saved candidates without rerunning extraction. Every persisted value remains `candidate` until a reviewer accepts or edits it. Pulmonary fields remain companion candidates until matching LibreClinica CRF items and verified OIDs are installed; the adapter fails closed instead of inventing mappings. This workflow is not validated for clinical use and must not be used with real patient data until institutional, ethics, privacy, and validation gates are resolved.

After accept or edit, the candidate moves out of the review queue and appears in the browser's “伴随模块已确认数据” table with its final value, site, subject/event references, reviewer, time and reason. The table provides a “创建冻结传输包” action. Package creation still does not write the EDC; a second explicit submit action is required, and only a `submitted` ledger row with an Authority-EDC reference represents a confirmed interface response.

## Run locally

From this folder in PowerShell:

```powershell
.\scripts\start_companion_live.ps1
```

This starts the already-provisioned localhost synthetic sandbox connection. To run fail-closed without any Authority-EDC client, omit `COMPANION_EDC_MODE` and start Uvicorn directly. Open `http://127.0.0.1:8000`. The demonstration password for all listed companion accounts is `demo-password`.

Run the verified behavior tests with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The automated suite covers the candidate, PDF/image intake, privacy, dictionary, quality, transfer and portable-runtime boundaries. Transfer creation accepts an optional bounded `Idempotency-Key`; without one, the server derives a deterministic candidate/package/target key. An exact retry returns the original transfer with HTTP 200 and `replayed: true`, while conflicting reuse returns HTTP 409. A historical simulation request can never be submitted through a later live adapter; a new target-specific request must be created instead. The transfer and reconciliation endpoints are:

- `GET /api/transfers` — list current authorised-centre transfer state, reconciliation metadata, and successful Authority-EDC references;
- `GET /api/transfers/{transfer_id}/package` — retrieve the frozen canonical package;
- `GET /api/transfers/{transfer_id}/integrity` — recompute and compare its SHA-256;
- `GET /api/transfers/{transfer_id}/receipt` — download the immutable request receipt and its independent SHA-256;
- `POST /api/transfers/{transfer_id}/submit` — atomically claim a `queued` request, recheck package integrity, call the configured adapter, and persist either `submitted` plus Authority reference/response hash or a structured `failed` state;
- `POST /api/transfers/{transfer_id}/retry` — explicitly requeue a `failed` transfer and increment its retry count;
- `POST /api/transfers/{transfer_id}/reconcile` — allow an investigator or central data manager to record a bounded manual reconciliation note for `failed`.

All endpoints enforce the same centre boundary as candidates. SOAP credentials are server-side only in `.runtime/libreclinica-soap-credentials.json`, which is ignored by version control. Neither the browser nor the SQLite companion database stores those credentials.

## Build the Windows portable package

For a recipient who only needs local PDF/image recognition, human review and
Excel export, build the Docker-free Lite package:

```powershell
.\scripts\build_windows_lite.ps1
```

This creates `dist/ClinicalReportExtractorLite-windows-x64.zip`. The recipient
extracts the complete folder and double-clicks
`Start-Clinical-EDC-Lite.cmd`; Python, Docker Desktop, WSL2, a Linux engine and
LibreClinica are not required. Kimi is enabled by default after the recipient
enters a local key; without a key the health state is `key_required` and local
pulmonary PDF parsing works without a network connection. See
`docs/windows-lite-distribution.md` for the exact data boundary and recipient
steps.

The same Lite workflow also has native macOS build support for Apple Silicon
and Intel Macs. A matching Mac build host runs:

```bash
TARGET_ARCH="$(uname -m)" bash ./scripts/build_macos_lite.sh
```

This creates `ClinicalReportExtractorLite-macos-arm64.zip` or
`ClinicalReportExtractorLite-macos-x86_64.zip`, containing a double-clickable
`.app` with Python, Tesseract and the Excel exporter. PyInstaller cannot build
a macOS application on Windows, so each artifact is built and black-box tested
on its matching architecture. External frictionless distribution additionally
requires Developer ID signing and Apple notarization. See
`docs/macos-lite-distribution.md`.

The original full package remains available for a separately administered
LibreClinica sandbox:

Run the reproducible Windows x64 build from the project root:

```powershell
.\scripts\build_windows_portable.ps1
```

The build creates `dist/ClinicalEdcCompanion-windows-x64.zip`, a sibling verification JSON file and an expanded folder under `dist/windows-x64/ClinicalEdcCompanion`. It rejects credential/database/log files, bundles Tesseract plus the pinned language data, writes `MANIFEST.sha256`, launches the built EXE with an isolated data directory, uploads an obviously synthetic check sheet, verifies four OCR candidates and verifies Excel generation before creating the ZIP. The recipient must extract and keep the complete folder; the EXE is not a standalone one-file application.

Kimi and LibreClinica are fail-closed in a fresh package. Recipient-specific setup scripts create new local credential files under `.runtime`; those files are never included in the archive. LibreClinica itself remains a separate Docker/Tomcat/PostgreSQL deployment. See `docs/windows-portable-distribution.md` for recipient and production boundaries.

After the browser workbench creates or safely replays a transfer, it displays the frozen JSON package, recorded and recomputed hashes, and the integrity result. The request receipt does not prove Authority-EDC delivery. When readiness is `ready`, the submit button names LibreClinica explicitly; otherwise it remains a blocked-gate test. The reconciliation panel exposes requeue and reviewer-only manual reconciliation and shows the Authority reference only after a confirmed response.

To run the synthetic, end-to-end local OCR verification, install Tesseract and its required language data first, then run:

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_local_ocr.py
```

This workstation has verified Tesseract 5.5.3 with project-pinned `chi_sim+eng` language data. The generated English table-style check sheet still parses four mapped fields, persists them, retrieves the same candidate IDs through the public list endpoint, and confirms that Kimi was not used. A separate generated Chinese direct-identifier regression image is rejected before candidate persistence. The Chinese model is a privacy-screening safeguard only; Chinese laboratory-name mapping and clinical check-sheet accuracy are not qualified.

The default language files and their SHA-256 values are recorded in `vendor/tessdata_fast/README.md`. Run the privacy gate independently with:

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_local_ocr_privacy_gate.py
```

Run the real Tesseract redaction-draft and human-confirmation verification with:

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_local_deidentification.py
```

Run the real Tesseract Chinese exact-label table verification with:

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_local_chinese_lab.py
```

The Chinese fallback contract and excluded ambiguities are documented in `docs/chinese-lab-alias-mapping.md`. The mapping is a versioned synthetic fit-gap artifact, not an approved clinical terminology standard.

The automated detector currently covers known labels for patient name, inpatient/outpatient/medical-record/national-ID/patient identifiers, phone number, birth date and bed number. It covers the full OCR line rather than attempting to retain adjacent content. Human preview remains mandatory because an OCR miss cannot be safely interpreted as proof that the image is de-identified.

## LibreClinica synthetic sandbox

Docker Desktop and checksum-verified official web and SOAP/ODM WARs are used only for a localhost, synthetic-data sandbox. The companion uses the SOAP/ODM interface and never writes LibreClinica tables directly. The deployed login page currently displays internal version metadata `1.4.0rc1`; treat this as a fit-gap warning to resolve with the vendor before any production qualification. See [infrastructure/libreclinica/README.md](infrastructure/libreclinica/README.md) and run:

```powershell
.\scripts\validate_libreclinica_sandbox.ps1 -Start -UseCachedImages
```

The script verifies Docker availability, both pinned WAR checksums, Compose configuration, protected-login routing, and the data-import WSDL. A successful start is sandbox fit-gap evidence only; it does not authorise real data.

Create and restore-check a local SQLite backup with:

```powershell
.\scripts\backup_companion_database.ps1
```

The script uses SQLite online backup, records a SHA-256 and restores into a temporary database for `PRAGMA integrity_check`. `start_companion_live.ps1` exposes only the latest evidence status to the health endpoint. Backup evidence is one production-readiness gate; localhost still remains `BLOCK` because synthetic-only operation, HTTPS, managed secrets, approved identity, formal validation and institutional controls are not satisfied.

The current local sandbox contains one generated-only study in `Available`, four visit-specific full-header CRFs for `WEEK_0`, `WEEK_4`, `WEEK_8`, and `WEEK_12`, 161 installed CRF items, the earlier two-field compatibility CRF, and a dedicated `companion_soap` Web Service account. The full-header count comes from a header-only read of the original 164-column workbook: the enrolment sequence becomes the LibreClinica StudySubject label, while patient name and name abbreviation are blocked as direct identifiers. A verified live proof created `SUBJ004`, scheduled the full `WEEK_0` event, OCR-extracted `WBC=4.50`, passed human review/frozen-package gates, imported it through SOAP/ODM, and independently read the same value back from LibreClinica. All of these are synthetic interface-test records, not clinical records. See `docs/libreclinica-sandbox-fit-gap.md` before reusing this test approach.

The installed sandbox OIDs are versioned in `config/libreclinica-sandbox-odm-map.json` as a visit-specific field map. Remote hosts are blocked by default; enabling one requires an explicit flag and HTTPS. Subject provisioning is a separate adapter method from clinical-value submission and requires `LIBRECLINICA_ALLOW_SUBJECT_PROVISIONING=true`. The browser upload always supplies the research code and visit; the localhost synthetic caller uses a prior-day synthetic enrollment date because LibreClinica requires a past date. Production must use the protocol-defined enrollment date and must not derive it from upload time.

## Kimi K3 configuration

Kimi is enabled by default at the application seam, but a local server-side
key is still required before any outbound request. Without the key, health
reports `key_required` and local OCR remains available. An explicit
`KIMI_ENABLED=false` opt-out forces local-only extraction. The current
companion still reports its storage/production boundary separately; an ethics
and data-flow approval does not turn a local SQLite deployment into a
qualified multi-centre EDC.

When authorised for synthetic interface testing, enter the key through the masked PowerShell prompt; do not paste it into source, the browser, a database, or a chat:

```powershell
.\scripts\configure_kimi.ps1
.\scripts\start_companion_live.ps1
```

The prompt writes the key to ignored `.runtime/kimi-api-key.txt`, restricts its Windows ACL to the current account, and never echoes it. The start script selects `kimi-k3` and reports `ready` only when that file exists. The adapter allow-lists the official Moonshot API base URLs, rejects obvious direct identifiers in both OCR text and coordinate evidence, and sends only a human-confirmed derivative image. These safeguards do not remove the need to follow the approved data-flow and retention controls.

For the centre-to-central offline exchange procedure, including BitLocker/FileVault preparation, encrypted package generation, batch import, backup/restore checks and retention cleanup, see [docs/centre-package-operations.zh-CN.md](docs/centre-package-operations.zh-CN.md).

## Offline centre exchange

When a centre cannot reach the hospital EDC, use the encrypted centre-package
export after human review. The AES-256-GCM envelope contains only pseudonymous
confirmed values, review timestamps and SHA-256 source hashes. A central data
manager can select multiple packages in one batch; the import is audited,
idempotent and explicitly reports `authority_submission=not_attempted`. It
never writes LibreClinica directly. Each result is logged with its package
SHA-256, centre code and dictionary-version decision.

## Boundaries

See `docs/preflight.md` for the data boundary, `CONTEXT.md` for clinical terms, `docs/testing-seams.md` for verified behavior seams, `docs/edc-adapter-contract.md` for the transfer boundary, and `docs/adr/` for the authority-EDC decisions.
