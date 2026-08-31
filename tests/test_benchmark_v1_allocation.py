from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path


CHALLENGES = {
    "clear_scan",
    "low_dpi_skew",
    "vendor_reprint_layout",
    "margin_handwritten_annotation",
    "reference_boundary_value",
    "cross_centre_unit_variant",
    "star_or_footnote_marker",
    "multipage_pulmonary",
}


def _run(output_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/prepare_benchmark_v1_allocation.py",
            "--output-dir",
            str(output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_benchmark_v1_allocation_is_deterministic_stratified_and_value_free(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_run = _run(first)
    second_run = _run(second)

    assert first_run.returncode == 0, first_run.stderr
    assert second_run.returncode == 0, second_run.stderr
    assert {path.name for path in first.iterdir()} == {
        "dataset-plan.json",
        "review-assignments.json",
        "manifest.json",
    }
    for name in ("dataset-plan.json", "review-assignments.json", "manifest.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
        assert (first / name).read_bytes() == (Path("benchmarks/synthetic-v1") / name).read_bytes()

    plan = json.loads((first / "dataset-plan.json").read_text(encoding="utf-8"))
    reports = plan["reports"]
    assert plan["purpose"] == "EXPERIMENT_ALLOCATION_ONLY_NOT_RESULTS"
    assert plan["counts"] == {"development": 30, "locked_test": 120, "double_review": 30}
    assert len(reports) == 150
    assert len({report["report_id"] for report in reports}) == 150
    assert all(8 <= report["target_field_count"] <= 15 for report in reports)
    assert all("value" not in report for report in reports)
    assert {report["primary_challenge"] for report in reports} == CHALLENGES

    locked_counts = Counter(
        report["primary_challenge"] for report in reports if report["split"] == "locked_test"
    )
    assert locked_counts == Counter({challenge: 15 for challenge in CHALLENGES})

    assignments = json.loads((first / "review-assignments.json").read_text(encoding="utf-8"))
    assert len(assignments["reports"]) == 30
    assert all(item["reviewers"] == ["reviewer_a", "reviewer_b"] for item in assignments["reports"])
    assert all(item["adjudication_required"] is True for item in assignments["reports"])
    assert all(
        next(report for report in reports if report["report_id"] == item["report_id"])["split"]
        == "locked_test"
        for item in assignments["reports"]
    )

    manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["reporting_boundary"] == "ALLOCATION_ONLY_NOT_SOURCE_NOT_GOLD_NOT_RESULTS"
    assert {artifact["name"] for artifact in manifest["artifacts"]} == {
        "dataset-plan.json",
        "review-assignments.json",
    }
    for artifact in manifest["artifacts"]:
        content = (first / artifact["name"]).read_bytes()
        assert artifact["bytes"] == len(content)
        assert artifact["sha256"] == hashlib.sha256(content).hexdigest()

    repeated = _run(first)
    assert repeated.returncode == 2
    assert json.loads(repeated.stderr)["code"] == "benchmark_v1_allocation_output_exists"
