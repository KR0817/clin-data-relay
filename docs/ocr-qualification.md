# Synthetic OCR qualification

The qualification input is intentionally synthetic. Do not put participant reports, direct identifiers, API keys or provider responses in the gold set.

Create a prediction file with the same `{ "fields": { ... } }` shape and run:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_ocr.py tests\fixtures\synthetic_ocr_gold.json predictions.json
```

The command prints aggregate counts and rates only: exact matches, numeric-tolerance matches, unit matches, missing fields and extra fields. It does not print source values. Every new OCR engine or model must be compared against the same gold manifest and remain behind a feature gate until its review rate and field-level errors are accepted by the study team.

The current production path remains the existing local parser/Tesseract boundary. PaddleOCR is a future adapter candidate, not an automatic dependency or a second authoritative EDC.
