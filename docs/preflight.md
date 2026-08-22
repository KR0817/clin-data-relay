# Implementation preflight

- **project_id:** `iit-multicentre-edc-kimi-2026`
- **dataset_id:** `rct-data-statistics-xlsx`
- **cohort_version:** `v0.0.0-design-only`
- **raw input:** `C:/Users/glah1/Desktop/RCT数据统计.xlsx` (read-only; not copied into this project)
- **raw SHA-256:** `30DB482F8E873431BAEDDAC55429E75F2B602C3D681889385A0FB3C54698715B`

## Gate

**2026-08-14 operator input:** the distributor states that ethics and the
approved data-flow review are complete before release. This records an
operator-provided prerequisite; it does not by itself qualify the local
SQLite/LibreClinica sandbox as a production multi-centre EDC.

**BLOCK — technical production qualification.** The workbook contains direct
identity and sensitive clinical data. Even with the stated ethics/data-flow
approval, PostgreSQL multi-writer support, institution identity/MFA,
LibreClinica deployment validation, backup/restore evidence and formal
validation remain outstanding.

**PASS_WITH_WARNINGS — synthetic-data MVP.** Development may proceed only with synthetic identifiers such as `SUBJ001`, generated laboratory reports, non-production credentials and the localhost LibreClinica interface sandbox. The companion must not be configured with a real Kimi key, a remote/production EDC endpoint, or a real patient image until the blocked items are approved. The local sandbox now contains four visit-specific full-header CRFs, one dedicated SOAP account, and synthetic end-to-end interface records.

## Frozen implementation boundary

- In scope: centre-scoped account model, de-identified image intake, OCR/Kimi candidate persistence, human accept/edit/reject, auditable transfer queue, and a fail-closed SOAP/ODM adapter qualified only against the localhost synthetic sandbox.
- Out of scope: audio/ASR, follow-up recording, in-product literature search, GitHub search/execution, automated clinical conclusions, and direct EDC database writes.

## Synthetic-sandbox configuration evidence (updated 2026-08-09)

- A local sandbox administrator completed the mandatory local password reset without recording the credential in this repository.
- Generated-only study `Synthetic OCR Laboratory Workflow` (`SYNTHETIC-OCR-LAB-2026-08`) is `Available` only in the sandbox. No real account, centre, site, investigator or participant identity was created.
- A header-only read of the supplied workbook identified 164 source columns. The enrolment sequence maps to the StudySubject label, 161 source columns map to visit-specific CRF items, and patient name/name abbreviation are intentionally blocked as direct identifiers.
- Four generated CRFs contain exactly 72 `WEEK_0`, 11 `WEEK_4`, 11 `WEEK_8`, and 67 `WEEK_12` items. `SUBJ004 / WEEK_0 / WBC=4.50` was created, scheduled, reviewed, imported, and independently read back through the live localhost interface.
- The dedicated SOAP credential stays in the ignored `.runtime` directory; root recovery credentials were not retained. This is not production secret management.
- The deployed `1.4.0rc1` parser rejected the current template after it encountered style-only trailing rows and legacy Section columns. A fresh minimal workbook with no trailing rows and explicit legacy `PARENT_SECTION`/`BORDERS` columns passed LibreClinica preview with “no errors.” This is a sandbox compatibility observation, not an approved clinical CRF-generation method.
# Phase 1.2 preflight: LibreClinica synthetic interface and local OCR

| Gate | Status | Evidence / boundary |
| --- | --- | --- |
| Patient data in sandbox | PASS | No patient data are copied to the project or sandbox. The supplied workbook remains read-only and out of scope. |
| Companion test data | PASS | Tests use only generated, obviously synthetic subject references and image bytes. |
| LibreClinica host baseline | PASS_WITH_WARNINGS | Docker Desktop 4.85.0, WSL 2.7.11, and Ubuntu 22.04 are available. On 2026-08-08 the `validate_libreclinica_sandbox.ps1 -Start` script SHA-256 verified the official artifact named `LibreClinica-web-1.4.0.war`, started the localhost-only Docker Compose stack, and received HTTP 200 from `http://127.0.0.1:8081/`. The login page reports internal metadata `1.4.0rc1`; this discrepancy must be resolved before qualification. The official baseline remains Linux, Tomcat 9, OpenJDK 11, and PostgreSQL; this workstation sandbox is not a production qualification. |
| LibreClinica login surface | PASS_WITH_WARNINGS | The protected route redirects correctly; a post-reset local session created the generated study/CRF/event and dedicated SOAP account through LibreClinica workflows. The temporary administrator recovery was resealed and not retained. No real accounts, centres or clinical records were created. |
| Local OCR, redaction and Chinese table runtime | PASS_WITH_WARNINGS | Tesseract 5.5.3 with project-pinned `chi_sim+eng` data processed a generated English table-style check sheet and a generated Chinese exact-label two-column fixture through public synthetic-only endpoints; Kimi was not used. A generated Chinese-name fixture produced a local redaction derivative, returned only marker categories, required a non-cacheable authenticated preview and explicit human attestation, then entered coordinate-based Chinese parsing. The Chinese fallback uses versioned exact labels, rejects conflicting observations, excludes unresolved count/percentage concepts, never infers units and records confidence `0.55`. The original remained unchanged. A first fixture using `10^9/L` was misread as `1049/L`, so units remain unnormalized candidates and require human review. Automated redaction and alias parsing are not proof of de-identification or clinical accuracy. |
| Versioned CRF mapping guard | PASS_WITH_WARNINGS | A read-only header-only audit informed `rct-full-field-dictionary.v0.2.json` and `synthetic_lab_mapping.v0.1.json`. All 161 non-identifier CRF columns have distinct visit/field mappings across `WEEK_0`, `WEEK_4`, `WEEK_8`, and `WEEK_12`; 161 installed OIDs were read back into the sandbox ODM map. Units, ranges, controlled terminology, and clinical CRF meaning remain unapproved. |
| Authority-EDC writes | PASS_WITH_WARNINGS / BLOCK | The localhost synthetic SOAP/ODM path passed authenticated readiness and one fully successful frozen-package import. Remote/production EDC configuration and all real-data writes remain BLOCKED. Direct database writes remain prohibited. |
| Kimi access | PASS_WITH_WARNINGS / key_required | The provider client is enabled by default but requires a recipient-local key and sends only confirmed de-identified derivatives; the code reports `key_required` until configured. |

**Decision:** the local, synthetic-only sandbox and its visit-specific SOAP/ODM adapter are runnable for controlled interface testing. They do not authorise real data, validate the clinical meaning of the 161 fields, qualify a production deployment, or resolve the real-data gate above.
