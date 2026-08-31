# Synthetic Benchmark v1 corpus preparation

**Status: `CORPUS_GENERATOR_READY; EXPERIMENT_NOT_RUN`. No source report,
adjudicated gold annotation, extractor prediction or benchmark result exists in
this tracked directory.**

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

Generate the deterministic, identifier-free source corpus into an ignored
directory:

```powershell
uv run python scripts/generate_benchmark_v1_corpus.py `
  --allocation benchmarks/synthetic-v1/dataset-plan.json `
  --output-dir .runtime/benchmark-v1-corpus
```

The generator creates 150 source reports, construction records and value-free
reviewer templates. Construction records are retained by the corpus custodian;
they are not adjudicated gold. The tracked `corpus-freeze.json` records the
generator inputs and same-environment reproducibility hashes, but it is not a
source archive and does not claim byte identity across operating systems or
library versions.

Do not create a `bench-v1` tag from this preparation state. That tag requires
an archived immutable source package, gold/adjudication, both prediction arms
and the final result package.
