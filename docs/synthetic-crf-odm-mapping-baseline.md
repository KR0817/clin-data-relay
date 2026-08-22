# Synthetic CRF/ODM full-header mapping (Phase 1.3)

**Status:** `PASS_WITH_WARNINGS` for localhost, synthetic-only interface coverage. This is not an investigator-approved clinical CRF or a production validation specification.

## Read-only source-structure audit

On 2026-08-08, the supplied workbook was opened read-only to inspect only header rows 1 and 2. No participant row, cell value, or image was copied into this repository.

- One worksheet with a two-row header layout and 164 columns was observed.
- Column 1 (enrolment sequence) maps to the LibreClinica StudySubject label rather than a duplicated CRF item.
- Columns 3 and 4 (patient name and name abbreviation) are explicit non-uploadable exclusions and must never be sent to Kimi or LibreClinica through this companion.
- Every other source column has a visit-specific, deterministic item mapping. The resulting counts are 72 baseline, 11 week-4, 11 week-8, and 67 week-12 CRF items.

## Versioned synthetic mapping

The source-column ledger is [`config/rct-full-field-dictionary.v0.2.json`](../config/rct-full-field-dictionary.v0.2.json). Candidate validation uses [`config/synthetic_lab_mapping.v0.1.json`](../config/synthetic_lab_mapping.v0.1.json), and installed LibreClinica identities use [`config/libreclinica-sandbox-odm-map.json`](../config/libreclinica-sandbox-odm-map.json).

| Mapping property | Value |
| --- | --- |
| Mapping ID | `iit-pss-rct-full-header-map` |
| Mapping version | `v0.2-synthetic-sandbox` |
| Events accepted by the companion | `WEEK_0`, `WEEK_4`, `WEEK_8`, `WEEK_12` |
| Source columns represented | 164 total: 1 StudySubject label, 161 CRF items, 2 blocked direct identifiers |
| Installed CRF items | 161 across four visit-specific CRFs |
| Candidate source | Attested synthetic image or synthetic text only |

Synthetic manual creation and the currently disabled Kimi route reject any field/event combination absent from this mapping. Local OCR continues to recognize only its qualified exact laboratory labels; mapping a non-laboratory source header makes that field transfer-capable after explicit candidate creation and human review, but does not claim that OCR can extract it. Candidate provenance includes the mapping version; the health endpoint publishes the active mapping ID and version.

## Explicitly unresolved items

- The source header `CI` remains unresolved. It is preserved as the non-inferred code `SOURCE_CI`; it is not silently converted to chloride (`CL`).
- The source headers do not supply units, reference intervals, assay methods, value types (for example, count versus percentage), or lower/upper data constraints. The companion can preserve a recognized unit as a candidate, but cannot infer, normalize, or range-check it.
- The two identical week-12 vitality headers are not merged. Column 163 is preserved separately as `SF36_VITALITY_DUP_C163` until the investigator confirms whether it is a duplicate or a different intended construct.
- All generated item data types are `ST` in this interface sandbox so source qualifiers such as `<0.5` are not destroyed. This is not a clinically approved data-type decision.
- The mapping does not establish CDISC, OMOP, SNOMED CT, LOINC, or validated scale scoring identities.

## Required synthetic-only continuation

1. Obtain investigator-approved labels, data types, units, controlled terminology, missing-value codes, scale algorithms, and source-document rules for every intended field.
2. Resolve `SOURCE_CI`, the duplicate week-12 vitality column, and all free-text/coded-value semantics before treating the generated forms as protocol CRFs.
3. Keep the generated `ST` forms and OIDs as interface fixtures only; replace them with a validated versioned CRF specification before real-data use.
4. Independently inspect queries, signatures, locks, timeout/duplicate behavior, change control, validation evidence, backup/restore, and audit retention before production qualification.
5. Continue to prohibit direct database writes. The mapping generator reads installed metadata only; clinical values enter through SOAP/ODM after human confirmation.
