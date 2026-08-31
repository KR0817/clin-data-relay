# Synthetic Extraction Benchmark v1 report

**Status: `EXPERIMENT_NOT_RUN`**

No extraction accuracy, model benefit, human correction rate or annotator
agreement result is reported here. The repository currently contains the
metric engine, the value-free 150-report allocation, a deterministic source
generator and a hash-only local reproducibility record.

## Evidence gate

| Required artifact | Status |
| --- | --- |
| Prespecified 30 development + 120 locked-test allocation | Complete |
| Deterministic source generator and same-environment hash check | Complete |
| Archived immutable source report bytes and source manifest | Missing |
| Independent reviewer A annotations | Missing |
| Independent reviewer B annotations | Missing |
| Adjudicated gold records and disagreement log | Missing |
| Frozen local-OCR predictions | Missing |
| Frozen OCR-plus-model predictions | Missing |
| Immutable v2 evaluation package | Missing |

The report remains unrun while any row is missing. Missing evidence is not
represented by zero, `PASS`, an estimated value or a constructed fixture.
The construction records produced by the generator are input truth for corpus
assembly, not independent or adjudicated gold annotations.

## Smoke-test separation

The `v0.3.0` Windows release exercised two obviously synthetic documents and 19
reviewed candidates. That is a packaged workflow smoke test, not this
benchmark's report count, field count, accuracy estimate or model comparison.

## Intended analyses

When every gate is complete, this report will include strict and
numeric-normalized extraction accuracy, report exact-match rate, the frozen
error taxonomy, report-clustered confidence intervals, paired corrected versus
introduced errors, explicit abstention/availability outcomes, human correction
rate and double-review agreement. Counts will be shown beside every rate.

Synthetic results will be described only as controlled document-extraction
performance. They will not establish clinical validation, site generalization,
participant benefit or production readiness.
