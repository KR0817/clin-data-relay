# Conservative Chinese laboratory alias mapping

**Status:** `PASS_WITH_WARNINGS` for the synthetic-data companion only. This is not a clinically validated terminology map.

The machine-readable source is `config/chinese_lab_aliases.v0.1.json`, version `zh-lab-v0.1-exact-labels`. It is used only after plain OCR produces no field codes allowed by the active CRF mapping.

## Guardrails

- The image must already be an explicitly human-confirmed de-identification derivative when that workflow is used.
- OCR preprocessing is local grayscale, 2× LANCZOS enlargement and autocontrast.
- A field requires an exact versioned Chinese label found in the OCR word stream.
- The candidate value is the first single numeric token to the right of that label on the same OCR line and within a bounded horizontal distance.
- Reference-range tokens are rejected as values.
- Units are not inferred; an absent unit remains `null` for human review.
- Multiple different values for one code make that code ambiguous and remove it from the candidate set.
- Every output code is filtered again through the active event-specific CRF mapping.
- `NEUT`, `LYMPH` and `MONO` remain excluded because the workbook headers do not resolve absolute-count versus percentage semantics.
- Short aliases that could occur inside unrelated tests are not accepted: examples include sodium within natriuretic peptide, calcium within troponin, and haemoglobin within red-cell indices.

## Provenance

Structured candidates record the Tesseract version, language, preprocessing recipe, page-segmentation mode, CRF mapping version and Chinese alias mapping version. Their initial confidence is `0.55`, below the plain-code path, and every candidate remains subject to review by a site investigator or central data manager.

## Verified behavior

- A generated Chinese identifier line is redacted before structured extraction.
- A generated two-column Chinese laboratory fixture yields four exact-label mapped candidates through the public HTTP endpoint without Kimi.
- The locally supplied check-sheet reproduction yields seven unambiguous codes after redaction and human confirmation; diagnostics expose only codes and status, never patient identifiers or values.
