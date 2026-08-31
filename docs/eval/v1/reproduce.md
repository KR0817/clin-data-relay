# Reproduce Synthetic Benchmark v1

## 1. Verify the frozen allocation

Generate into a new ignored directory:

```powershell
uv run python scripts/prepare_benchmark_v1_allocation.py `
  --output-dir .runtime/benchmark-v1-allocation-check
```

Compare the generated files with `benchmarks/synthetic-v1/`. The command is
deterministic and refuses to overwrite an existing directory.

## 2. Required pre-run artifacts

Generate offline source material into a new ignored directory:

```powershell
uv run python scripts/generate_benchmark_v1_corpus.py `
  --allocation benchmarks/synthetic-v1/dataset-plan.json `
  --output-dir .runtime/benchmark-v1-corpus
```

Keep `construction-truth/` under the corpus custodian. Give each reviewer only
the identifier-free sources and their own value-free template. Do not expose
either extractor prediction arm before annotation and adjudication close.

The tracked `benchmarks/synthetic-v1/corpus-freeze.json` records the expected
same-environment manifest hashes for a clean generation using the locked
dependencies. Verify them before custody transfer. The file is not a source
archive and does not establish cross-platform byte identity.

Do not run or publish the locked analysis until all of these exist with hashes:

- synthetic source reports;
- independent reviewer A and B annotations for the assigned subset;
- adjudication log and final gold JSONL;
- local-OCR prediction-v2 JSONL; and
- OCR-plus-model prediction-v2 JSONL.

This repository does not currently provide a paid-provider batch runner. That
omission prevents an accidental live model call or an unbounded cost from being
mistaken for a reproducible experiment.

## 3. Prepare blinded review and adjudication

Follow the detailed
[Chinese operator guide](annotation-and-freeze-guide.zh-CN.md). The bounded CLI
sequence is:

```text
prepare-review-kits -> compile-review (A and B)
-> prepare-adjudication -> finalize-gold -> freeze-predictions
```

The central custodian must retain `custody-manifest.json` separately from the
reviewers. Each reviewer receives only their own 75-report kit. The third
adjudicator sees both completed annotations only after they are compiled and
hash-covered. No command substitutes construction truth for human gold.

The current repository freezes completed prediction-v2 files but deliberately
does not provide a paid-provider 120-report batch runner. Do not assemble a
formal arm from repeated interactive attempts.

## 4. Run the frozen scorer

```powershell
uv run python scripts/evaluate_extraction_benchmark.py `
  --gold PATH/frozen-inputs/locked-gold.jsonl `
  --predictions local_ocr=PATH/frozen-inputs/local-ocr.jsonl `
  --predictions local_ocr_plus_model=PATH/frozen-inputs/local-ocr-plus-model.jsonl `
  --output-dir PATH/NEW-evaluation-package `
  --bootstrap-samples 2000 `
  --seed 20260901
```

The output directory is immutable and contains aggregate `summary.json`, a
value-free `errors.csv` and `manifest.json`. Preserve the raw governed inputs
separately; do not add participant data, credentials or provider error bodies.

## 5. Publication gate

Populate `REPORT.md` only from the immutable result package and annotation
evidence. Keep the 19-candidate release smoke test separate. Create `bench-v1`
only after report review, hash verification and CI pass.
