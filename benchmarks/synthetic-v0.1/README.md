# Synthetic benchmark metric-engine examples

**Status: `DEMONSTRATION_ONLY`. These files are not extractor performance
results and are not clinical validation evidence.**

This directory exercises the versioned benchmark contract described in
[`docs/evaluation/benchmark-protocol-v0.1.md`](../../docs/evaluation/benchmark-protocol-v0.1.md).
It contains three obviously synthetic report records and deliberately constructed
prediction errors. It is not the planned 30-report development set or locked
100-report test set.

Run the deterministic demonstration from the repository root:

```powershell
uv run python scripts/evaluate_extraction_benchmark.py `
  --gold benchmarks/synthetic-v0.1/gold.example.jsonl `
  --predictions local_ocr=benchmarks/synthetic-v0.1/local_ocr.example.jsonl `
  --predictions local_ocr_plus_model=benchmarks/synthetic-v0.1/assisted.example.jsonl `
  --output-dir .runtime/benchmark-example `
  --bootstrap-samples 2000 `
  --seed 20260831
```

The command refuses to overwrite the output directory. Delete or choose a new
path only after preserving any evaluation package that matters.
