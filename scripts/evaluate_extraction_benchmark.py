"""Build an immutable, value-free synthetic benchmark evaluation package."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.benchmark_evaluation import (
    PACKAGE_SCHEMA_VERSION,
    BenchmarkValidationError,
    evaluate_benchmark,
    load_jsonl,
    parse_gold_records,
    parse_prediction_records,
)


def _file_metadata(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(block)
            digest.update(block)
    return {"name": path.name, "sha256": digest.hexdigest(), "bytes": size}


def _prediction_argument(value: str) -> tuple[str, Path]:
    arm, separator, raw_path = value.partition("=")
    if not separator or not arm.strip() or not raw_path.strip():
        raise argparse.ArgumentTypeError("expected ARM=PATH")
    return arm.strip(), Path(raw_path)


def _write_package(
    *,
    output_dir: Path,
    summary: dict[str, object],
    errors,
    gold_path: Path,
    prediction_paths: list[tuple[str, Path]],
    bootstrap_samples: int,
    seed: int,
) -> None:
    if output_dir.exists():
        raise BenchmarkValidationError("benchmark_output_exists")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        summary_path = temporary_dir / "summary.json"
        errors_path = temporary_dir / "errors.csv"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        with errors_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=("report_id", "visit_ref", "arm", "field_code", "error_kind", "primary_category"),
            )
            writer.writeheader()
            for error in errors:
                writer.writerow(
                    {
                        "report_id": error.report_id,
                        "visit_ref": error.visit_ref,
                        "arm": error.arm,
                        "field_code": error.field_code,
                        "error_kind": error.error_kind,
                        "primary_category": error.primary_category,
                    }
                )
        manifest = {
            "schema_version": PACKAGE_SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "parameters": {"bootstrap_samples": bootstrap_samples, "seed": seed},
            "inputs": {
                "gold": _file_metadata(gold_path),
                "predictions": [
                    {"arm": arm, **_file_metadata(path)} for arm, path in prediction_paths
                ],
            },
            "outputs": [_file_metadata(summary_path), _file_metadata(errors_path)],
            "reporting_boundary": "SYNTHETIC_METRIC_ENGINE_ONLY_NOT_CLINICAL_VALIDATION",
        }
        (temporary_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temporary_dir, output_dir)
    except BaseException:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Score versioned synthetic extraction predictions.")
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--predictions", type=_prediction_argument, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=2_000)
    parser.add_argument("--seed", type=int, default=20260831)
    args = parser.parse_args()
    try:
        prediction_paths = list(args.predictions)
        arms = [arm for arm, _ in prediction_paths]
        if len(arms) != len(set(arms)):
            raise BenchmarkValidationError("benchmark_arm_duplicate")
        gold = parse_gold_records(load_jsonl(args.gold))
        predictions = {
            arm: parse_prediction_records(load_jsonl(path), expected_arm=arm)
            for arm, path in prediction_paths
        }
        summary, errors = evaluate_benchmark(
            gold,
            predictions,
            bootstrap_samples=args.bootstrap_samples,
            seed=args.seed,
        )
        _write_package(
            output_dir=args.output_dir,
            summary=summary,
            errors=errors,
            gold_path=args.gold,
            prediction_paths=prediction_paths,
            bootstrap_samples=args.bootstrap_samples,
            seed=args.seed,
        )
    except BenchmarkValidationError as error:
        print(json.dumps({"status": "error", "code": str(error)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"status": "ok", "output_dir": str(args.output_dir)}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
