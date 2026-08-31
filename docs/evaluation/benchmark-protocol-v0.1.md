# Extraction benchmark protocol v0.1

**Status:** protocol and metric engine implemented; no extractor benchmark
result has been generated.

The versioned JSONL contracts, report-clustered scorer and deliberately
constructed demonstration fixtures are documented in
[`benchmarks/synthetic-v0.1/README.md`](../../benchmarks/synthetic-v0.1/README.md).
The demonstration proves only that the metric engine detects known errors. It
is not part of the development or locked test set.

## Objective

Measure whether optional model assistance improves report-to-candidate
extraction over local OCR without increasing unsupported values, unit errors,
privacy failures or human review burden. This benchmark evaluates data
extraction, not diagnosis, prognosis, treatment or EDC validation.

## Prespecified systems

1. `local_ocr`: current deterministic local OCR/PDF extraction and field map.
2. `local_ocr_plus_model`: the same local evidence and dictionary with the
   configured multimodal provider enabled.

Both arms use the same application commit, field-dictionary version, report
bytes and normalization rules. Record provider/model identifier, prompt/schema
version, date, latency, token usage and cost without storing credentials or raw
provider errors. Provider failure remains an observed fallback outcome.

## Dataset

- **Development set:** 30 synthetic reports available for parser, mapping and
  prompt development.
- **Locked test set:** 100 different synthetic reports that remain inaccessible
  to implementation tuning until the protocol, code and manifest are frozen.
- Stratify both sets across laboratory images and pulmonary-function PDFs,
  clear/blurred/skewed captures, multi-column or multi-page layout, decimal and
  comparison symbols, unit variants, missing fields and out-of-range values.
- Use generated identities and pseudonymous subject codes only. Do not use real
  reports, participant data or reconstructed patient documents.
- Publish a manifest containing each file's SHA-256, template family, challenge
  strata and split. Never move a report between splits after unblinding.

The counts define a portfolio-scale benchmark, not a formal clinical sample
size calculation. Results must report uncertainty and avoid powered superiority
claims unless a separate statistical design is approved.

## Gold standard

Two annotators independently transcribe `field_code`, displayed label, result,
comparator, unit, reference interval, page and evidence region without seeing
either system output. A third adjudicator resolves disagreements before the
test set is run. Gold records and adjudication decisions are versioned and
hashed.

Application accept/edit/reject logs are secondary workflow outcomes, not the
gold standard, because reviewers can be anchored by displayed model values.

## Unit of analysis and matching

The primary unit is a gold field instance within a report. Match predictions by
report, visit and versioned field code. Report two value rules:

- **strict:** exact normalized comparator, numeric/text value and unit;
- **numeric-normalized:** numerically equal after prespecified decimal and unit
  normalization, with no inferred unit or unsupported conversion.

Normalization code and accepted unit conversions must be frozen before test
unblinding. Reference intervals are scored separately and never substituted for
the reported result.

## Outcomes

Primary outcome:

- strict `field_code + comparator + value + unit` accuracy on the locked test
  set.

Secondary outcomes:

- field detection precision, recall and F1;
- numeric-normalized accuracy;
- missing-field and unsupported-value (hallucination) rates;
- unit, comparator and reference-interval error rates;
- reports with every required field correct;
- human edits, rejects and review time per report;
- extraction latency, provider calls, fallback rate and cost per report; and
- direct-identifier privacy-gate false-negative rate on a separate synthetic
  identifier challenge subset.

Use report-clustered bootstrap 95% confidence intervals. For paired arm
comparisons, resample reports rather than individual fields. Report absolute
counts beside percentages and stratify by report type and challenge class.

## Error taxonomy

Every false positive, false negative or incorrect value receives one primary
category and optional contributing categories:

1. character or digit recognition;
2. decimal, sign or comparison-symbol error;
3. unit missing, incorrect or unjustifiably converted;
4. field/dictionary mapping error;
5. row, column, page or reading-order error;
6. reference interval mistaken for result;
7. required field missed;
8. unsupported or hallucinated value;
9. duplicate candidate;
10. direct-identifier privacy-gate failure; or
11. source genuinely unreadable/ambiguous.

## Freeze and execution gates

Before running the locked test set, commit and record:

- repository commit and environment lock hash;
- field dictionary, normalization and prompt/schema versions;
- dataset/gold/adjudication manifest hashes;
- the exact evaluation command and output schema; and
- the analysis plan and all exclusions.

Run each arm once per report unless a retry policy is frozen in advance. A
timeout or provider error is not a negative finding about extraction content;
it is reported as availability/fallback evidence. Keep raw predictions,
normalized matches and errors in an append-only evaluation package.

## Reporting boundary

The future report must distinguish `LOCAL_RECOMPUTED`, provider-returned and
human-adjudicated evidence. Do not claim clinical validation, site
generalization or patient benefit from a synthetic benchmark. Any later real
data evaluation requires its own protocol, approvals, access controls and
statistical design.

## Frozen metric-engine command

```text
python scripts/evaluate_extraction_benchmark.py \
  --gold GOLD.jsonl \
  --predictions local_ocr=LOCAL.jsonl \
  --predictions local_ocr_plus_model=ASSISTED.jsonl \
  --output-dir NEW_EVALUATION_DIRECTORY \
  --bootstrap-samples 2000 \
  --seed 20260831
```

The command creates a value-free error CSV, aggregate summary and input/output
hash manifest. It refuses to overwrite an existing directory. The initial
normalization version performs no unit inference or unit conversion.
