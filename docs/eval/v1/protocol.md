# Synthetic Extraction Benchmark v1 protocol

**Status: allocation frozen; experiment not run.**

## Objective and systems

Measure whether optional model assistance changes controlled synthetic
report-to-candidate extraction relative to the same local OCR/PDF pipeline.
The paired arms are `local_ocr` and `local_ocr_plus_model`; they must use the
same application commit, field dictionary, report bytes and normalization.

This is a software measurement study, not a diagnostic, prognostic or clinical
validation study.

## Dataset allocation

- Development: 30 reports, available for pipeline debugging.
- Locked test: 120 different reports, unavailable for tuning after freeze.
- Double review: 30 prespecified locked reports, independently annotated by
  masked `reviewer_a` and `reviewer_b`, then adjudicated.
- Target fields: 8–15 per report.

The eight primary challenge strata are:

1. clear scan;
2. low-DPI skewed mobile capture;
3. vendor/reprint layout variation;
4. margin handwritten annotation;
5. result exactly on a reference boundary;
6. cross-centre unit variant;
7. star or footnote marker; and
8. multipage pulmonary-function report.

The locked set contains exactly 15 reports per primary stratum. The allocation
is value-free and hashed under `benchmarks/synthetic-v1/`. Source documents and
their values do not yet exist and must receive a separate immutable manifest.

Source generation keeps three access layers separate: identifier-free report
bytes for extractors and reviewers, construction truth for the corpus
custodian, and value-free annotation templates for reviewers. Construction
truth is never substituted for independently reviewed and adjudicated gold.
The locked source set may receive automated structure/hash checks before
annotation, but it is not used for prompt, parser or threshold tuning.

## Gold and annotation

Both reviewers transcribe field code, displayed label, comparator, value, unit,
reference interval, page and evidence region without seeing either system
output. A third adjudicator resolves every discrepancy before locked prediction
files are opened. Application accept/edit/reject logs remain workflow outcomes,
not gold evidence.

Reviewers use separate custody kits and identify themselves only as the frozen
slots `reviewer_a` and `reviewer_b`. They do not receive construction truth,
the other reviewer's file or either prediction arm. The adjudicator receives
only the two completed annotation records and generated discrepancy table.
Automated consensus means exact tuple equality; it is not a substitute for the
third-person resolution of a difference.

Report exact tuple agreement and adjudication count for the double-reviewed
subset. Agreement measures annotation reproducibility; it does not independently
validate the constructed synthetic truth.

## Frozen measurements

Primary outcome:

- strict field-code/comparator/value/unit accuracy on the locked set.

Secondary and safety outcomes:

- numeric-normalized accuracy, detection precision/recall/F1 and report exact
  match;
- missing, unsupported, unit, comparator and reference-interval errors;
- paired `local wrong → assisted correct` corrected errors;
- paired `local correct → assisted wrong` introduced errors, including a field
  produced only by the assisted arm;
- unchanged-correct and unchanged-incorrect paired field slots;
- observed review candidates, unchanged accepts, edits, rejects, correction
  rate and review time;
- deliberate abstention, fallback, provider error and timeout as separate
  outcomes; and
- privacy-gate false negatives on prespecified synthetic identifier challenges.

The 150-report extraction allocation is identifier-free, so it cannot provide
that privacy-gate denominator. Privacy performance remains undefined until a
separate, frozen identifier-safety allocation is created and run; absence of a
denominator must not be rendered as zero or success.

Every rate is accompanied by numerator and denominator counts. Confidence
intervals resample reports, never fields. The 120-report target is a portfolio
size rather than a powered clinical superiority design; no powered claim is
made without a separately approved precision/power analysis.

Report the same content metrics and report-clustered intervals by frozen report
type and challenge class. Availability-rate and human-correction intervals use
the same report cluster, retaining every visit when a sampled report has more
than one visit.

## Unit boundary

Normalization version `benchmark-normalization-v1` performs no unit inference
or conversion. Unit-variant reports test recognition and faithful capture only.
Any future equivalence table must be frozen under a new normalization version
before locked predictions are inspected.

## Execution and publication gates

Before test execution, record hashes for source reports, environment lock,
dictionary, prompt/schema, reviewer inputs, adjudicated gold and exclusions.
Run each arm once per report under a frozen retry policy. Keep provider failure
as availability evidence rather than silently dropping the report.

Freeze gold before either formal prediction file is generated. Freeze both
prediction files before scoring. A manifest and no-overwrite directory make
later changes detectable; they do not create WORM storage, so custody copies
must remain read-only under the study's normal controlled storage process.

Create `bench-v1` only after the immutable v2 result package and this report are
complete, reviewed and internally consistent. The tag must never be created
from the allocation or metric-engine demonstration alone.
