# Synthetic Benchmark v1 allocation

**Status: `ALLOCATION_ONLY`. No source report, gold annotation, extractor
prediction or benchmark result exists in this directory.**

The deterministic allocation contains 30 development IDs and 120 locked-test
IDs across eight prespecified primary challenge strata. Thirty locked reports
are marked for masked double review and later adjudication. Report entries
contain only generated identifiers, split/stratum metadata, template family and
target field count; they contain no clinical value or source bytes.

Regenerate the allocation into a new directory:

```powershell
uv run python scripts/prepare_benchmark_v1_allocation.py `
  --output-dir .runtime/benchmark-v1-allocation-check
```

The tracked hashes are recorded in `manifest.json`. See the
[protocol](../../docs/eval/v1/protocol.md),
[reproduction gates](../../docs/eval/v1/reproduce.md) and
[unrun report](../../docs/eval/v1/REPORT.md).

Do not create a `bench-v1` tag from this allocation. That tag requires the
frozen source, gold/adjudication, both prediction arms and final result package.
