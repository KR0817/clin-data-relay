"""Create the deterministic, value-free Benchmark v1 report allocation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path


SEED = 20260901
CHALLENGES = (
    "clear_scan",
    "low_dpi_skew",
    "vendor_reprint_layout",
    "margin_handwritten_annotation",
    "reference_boundary_value",
    "cross_centre_unit_variant",
    "star_or_footnote_marker",
    "multipage_pulmonary",
)
DEVELOPMENT_QUOTAS = dict(zip(CHALLENGES, (4, 4, 4, 4, 4, 4, 3, 3), strict=True))
LOCKED_TEST_QUOTAS = {challenge: 15 for challenge in CHALLENGES}
DOUBLE_REVIEW_QUOTAS = DEVELOPMENT_QUOTAS


class AllocationError(ValueError):
    """Raised when the immutable allocation cannot be created safely."""


def _report_type(challenge: str) -> str:
    return "synthetic_pulmonary_pdf" if challenge == "multipage_pulmonary" else "synthetic_lab_image"


def _template_family(challenge: str) -> str:
    return {
        "clear_scan": "lab_table_clear_v1",
        "low_dpi_skew": "lab_table_mobile_v1",
        "vendor_reprint_layout": "lab_vendor_reprint_v1",
        "margin_handwritten_annotation": "lab_margin_annotation_v1",
        "reference_boundary_value": "lab_reference_boundary_v1",
        "cross_centre_unit_variant": "lab_unit_variant_v1",
        "star_or_footnote_marker": "lab_footnote_v1",
        "multipage_pulmonary": "pulmonary_multipage_v1",
    }[challenge]


def _allocate_split(
    *, split: str, prefix: str, quotas: dict[str, int], randomizer: random.Random
) -> list[dict[str, object]]:
    specifications = [challenge for challenge in CHALLENGES for _ in range(quotas[challenge])]
    randomizer.shuffle(specifications)
    return [
        {
            "report_id": f"{prefix}-{index:04d}",
            "split": split,
            "report_type": _report_type(challenge),
            "template_family": _template_family(challenge),
            "primary_challenge": challenge,
            "target_field_count": 8 + randomizer.randrange(8),
            "double_review_required": False,
            "source_status": "not_generated",
        }
        for index, challenge in enumerate(specifications, start=1)
    ]


def build_allocation() -> tuple[dict[str, object], dict[str, object]]:
    randomizer = random.Random(SEED)
    development = _allocate_split(
        split="development",
        prefix="SYNDEV",
        quotas=DEVELOPMENT_QUOTAS,
        randomizer=randomizer,
    )
    locked_test = _allocate_split(
        split="locked_test",
        prefix="SYNTEST",
        quotas=LOCKED_TEST_QUOTAS,
        randomizer=randomizer,
    )
    selected_ids: set[str] = set()
    review_randomizer = random.Random(SEED + 1)
    for challenge in CHALLENGES:
        eligible = [item for item in locked_test if item["primary_challenge"] == challenge]
        selected_ids.update(
            item["report_id"]
            for item in review_randomizer.sample(eligible, DOUBLE_REVIEW_QUOTAS[challenge])
        )
    for report in locked_test:
        report["double_review_required"] = report["report_id"] in selected_ids
    reports = development + locked_test
    plan = {
        "schema_version": "clin-data-relay-benchmark-allocation-v1",
        "benchmark_id": "synthetic-benchmark-v1",
        "purpose": "EXPERIMENT_ALLOCATION_ONLY_NOT_RESULTS",
        "seed": SEED,
        "counts": {
            "development": len(development),
            "locked_test": len(locked_test),
            "double_review": len(selected_ids),
        },
        "primary_challenge_quotas": {
            "development": DEVELOPMENT_QUOTAS,
            "locked_test": LOCKED_TEST_QUOTAS,
            "double_review": DOUBLE_REVIEW_QUOTAS,
        },
        "reports": reports,
        "reporting_boundary": "ALLOCATION_ONLY_NOT_SOURCE_NOT_GOLD_NOT_RESULTS",
    }
    assignments = {
        "schema_version": "clin-data-relay-benchmark-review-assignment-v1",
        "benchmark_id": "synthetic-benchmark-v1",
        "reports": [
            {
                "report_id": report["report_id"],
                "reviewers": ["reviewer_a", "reviewer_b"],
                "adjudication_required": True,
            }
            for report in reports
            if report["report_id"] in selected_ids
        ],
        "reporting_boundary": "ASSIGNMENT_ONLY_NO_ANNOTATION_NO_IDENTITY",
    }
    if Counter(item["primary_challenge"] for item in locked_test) != Counter(LOCKED_TEST_QUOTAS):
        raise AllocationError("benchmark_v1_locked_quota_mismatch")
    return plan, assignments


def _encoded(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _metadata(name: str, content: bytes) -> dict[str, object]:
    return {"name": name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def write_allocation(output_dir: Path) -> None:
    if output_dir.exists():
        raise AllocationError("benchmark_v1_allocation_output_exists")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        plan, assignments = build_allocation()
        artifacts = {
            "dataset-plan.json": _encoded(plan),
            "review-assignments.json": _encoded(assignments),
        }
        for name, content in artifacts.items():
            (temporary_dir / name).write_bytes(content)
        manifest = {
            "schema_version": "clin-data-relay-benchmark-allocation-package-v1",
            "benchmark_id": "synthetic-benchmark-v1",
            "artifacts": [_metadata(name, content) for name, content in artifacts.items()],
            "reporting_boundary": "ALLOCATION_ONLY_NOT_SOURCE_NOT_GOLD_NOT_RESULTS",
        }
        (temporary_dir / "manifest.json").write_bytes(_encoded(manifest))
        os.replace(temporary_dir, output_dir)
    except BaseException:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the value-free Benchmark v1 allocation.")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        write_allocation(args.output_dir)
    except AllocationError as error:
        print(json.dumps({"status": "error", "code": str(error)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"status": "ok", "output_dir": str(args.output_dir)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
