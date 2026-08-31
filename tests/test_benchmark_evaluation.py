from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.benchmark_evaluation import (
    BenchmarkValidationError,
    evaluate_benchmark,
    parse_gold_records,
    parse_prediction_records,
)


def _gold(
    report_id: str,
    fields: list[dict[str, object]],
    *,
    privacy_gate_expected: str = "allow",
) -> dict[str, object]:
    return {
        "schema_version": "clin-data-relay-gold-v1",
        "report_id": report_id,
        "visit_ref": "BASELINE",
        "report_type": "synthetic_lab_image",
        "challenge_classes": ["clear"],
        "privacy_gate_expected": privacy_gate_expected,
        "fields": [
            {
                "displayed_label": str(field["field_code"]),
                "page_number": 1,
                "evidence_region": [0.1, 0.1, 0.2, 0.05],
                **field,
            }
            for field in fields
        ],
    }


def _prediction(
    report_id: str,
    arm: str,
    fields: list[dict[str, object]],
    *,
    status: str = "completed",
    privacy_gate_decision: str = "allow",
    schema_version: str = "clin-data-relay-prediction-v1",
    review_outcome: dict[str, int] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "report_id": report_id,
        "visit_ref": "BASELINE",
        "arm": arm,
        "status": status,
        "privacy_gate_decision": privacy_gate_decision,
        "fields": [{"page_number": 1, **field} for field in fields],
        "latency_ms": 10,
        "provider_calls": int(arm == "assisted"),
        "token_usage": {"input": 5 if arm == "assisted" else 0, "output": 2 if arm == "assisted" else 0},
        "cost_usd": "0.001" if arm == "assisted" else "0",
        "fallback_reason": "",
        "review_outcome": review_outcome,
    }


def _field(code: str, value: str, unit: str = "U/L", comparator: str = "", reference: str = "9-50") -> dict[str, object]:
    return {
        "field_code": code,
        "value": value,
        "comparator": comparator,
        "unit": unit,
        "reference_interval": reference,
    }


def _records() -> tuple[tuple, tuple, tuple]:
    gold = parse_gold_records(
        [
            _gold("synthetic-lab-001", [_field("ALT", "31"), _field("K", "3.9", "mmol/L", reference="3.5-5.3")]),
            _gold("synthetic-pft-001", [_field("FEV1", "2.45", "L", reference="")]),
            _gold("synthetic-privacy-001", [], privacy_gate_expected="block"),
        ]
    )
    local = parse_prediction_records(
        [
            _prediction("synthetic-lab-001", "local", [_field("ALT", "3l"), _field("HGB", "129", "g/L", reference="115-150")]),
            _prediction("synthetic-pft-001", "local", [_field("FEV1", "2.450", "L", reference="")]),
            _prediction("synthetic-privacy-001", "local", []),
        ],
        expected_arm="local",
    )
    assisted = parse_prediction_records(
        [
            _prediction("synthetic-lab-001", "assisted", [_field("ALT", "31"), _field("K", "3.9", "mmol/L", reference="3.5-5.3")]),
            _prediction("synthetic-pft-001", "assisted", [_field("FEV1", "2.45", "L", reference="")]),
            _prediction("synthetic-privacy-001", "assisted", [], privacy_gate_decision="block"),
        ],
        expected_arm="assisted",
    )
    return gold, local, assisted


def test_benchmark_scores_fields_errors_and_paired_report_bootstrap() -> None:
    gold, local, assisted = _records()

    summary, errors = evaluate_benchmark(
        gold,
        {"local": local, "assisted": assisted},
        bootstrap_samples=100,
        seed=17,
    )

    local_metrics = summary["arms"]["local"]["metrics"]
    assert local_metrics["gold_field_count"] == 3
    assert local_metrics["strict_accuracy"] == 0.0
    assert local_metrics["numeric_normalized_accuracy"] == pytest.approx(1 / 3, abs=1e-6)
    assert local_metrics["field_detection_precision"] == pytest.approx(2 / 3, abs=1e-6)
    assert local_metrics["field_detection_recall"] == pytest.approx(2 / 3, abs=1e-6)
    assert local_metrics["privacy_gate_false_negative_rate"] == 1.0
    assert summary["arms"]["assisted"]["metrics"]["privacy_gate_false_negative_rate"] == 0.0
    assert summary["arms"]["assisted"]["metrics"]["strict_accuracy"] == 1.0
    assert summary["arms"]["local"]["strata"]["report_type"]["synthetic_lab_image"]["metrics"]["report_count"] == 3
    assert summary["arms"]["local"]["strata"]["challenge_class"]["clear"]["metrics"]["report_count"] == 3
    assert summary["paired_comparisons"] == [
        {
            "comparison": "assisted_minus_local",
            "metric": "strict_accuracy",
            "absolute_difference": 1.0,
            "confidence_interval_95": {"lower": 1.0, "upper": 1.0},
            "field_transitions": {
                "evaluable_slot_count": 4,
                "corrected_error_count": 4,
                "introduced_error_count": 0,
                "unchanged_correct_count": 0,
                "unchanged_incorrect_count": 0,
                "corrected_error_rate": 1.0,
                "introduced_error_rate": 0.0,
                "net_corrected_minus_introduced_count": 4,
                "net_corrected_minus_introduced_rate": 1.0,
                "confidence_intervals_95": {
                    "corrected_error_rate": {"lower": 1.0, "upper": 1.0},
                    "introduced_error_rate": {"lower": 0.0, "upper": 0.0},
                    "net_corrected_minus_introduced_rate": {"lower": 1.0, "upper": 1.0},
                },
            },
        }
    ]
    assert {(error.field_code, error.primary_category) for error in errors} >= {
        ("ALT", "character_or_digit_recognition"),
        ("K", "required_field_missed"),
        ("HGB", "unsupported_or_hallucinated_value"),
        ("", "direct_identifier_privacy_gate_failure"),
    }


def test_benchmark_rejects_duplicate_candidates_and_incomplete_report_coverage() -> None:
    duplicate = _prediction("synthetic-lab-001", "local", [_field("ALT", "31"), _field("ALT", "31")])
    with pytest.raises(BenchmarkValidationError, match="duplicate_candidate"):
        parse_prediction_records([duplicate], expected_arm="local")

    gold, local, _ = _records()
    with pytest.raises(BenchmarkValidationError, match="coverage_mismatch"):
        evaluate_benchmark(gold, {"local": local[:1]}, bootstrap_samples=100)


def test_prediction_v2_separates_abstention_and_validates_review_denominator() -> None:
    abstained_v1 = _prediction("synthetic-lab-001", "assisted", [], status="abstained")
    with pytest.raises(BenchmarkValidationError, match="prediction_status_invalid"):
        parse_prediction_records([abstained_v1], expected_arm="assisted")

    abstained_v2 = _prediction(
        "synthetic-lab-001",
        "assisted",
        [],
        status="abstained",
        schema_version="clin-data-relay-prediction-v2",
    )
    parsed = parse_prediction_records([abstained_v2], expected_arm="assisted")
    assert parsed[0].status == "abstained"
    abstention_summary, _ = evaluate_benchmark(
        parse_gold_records([_gold("synthetic-lab-001", [_field("ALT", "31")])]),
        {"assisted": parsed},
        bootstrap_samples=100,
        seed=19,
    )
    availability = abstention_summary["arms"]["assisted"]["availability"]
    assert availability["abstention_count"] == 1
    assert availability["abstention_rate"] == 1.0
    assert availability["rate_confidence_intervals_95"]["abstention_rate"] == {
        "lower": 1.0,
        "upper": 1.0,
    }

    abstained_with_value = _prediction(
        "synthetic-lab-001",
        "assisted",
        [_field("ALT", "31")],
        status="abstained",
        schema_version="clin-data-relay-prediction-v2",
    )
    with pytest.raises(BenchmarkValidationError, match="abstained_fields_forbidden"):
        parse_prediction_records([abstained_with_value], expected_arm="assisted")

    impossible_review = _prediction(
        "synthetic-lab-001",
        "local",
        [_field("ALT", "31")],
        review_outcome={"edits": 1, "rejects": 1, "review_time_ms": 100},
    )
    with pytest.raises(BenchmarkValidationError, match="review_outcome_exceeds_candidates"):
        parse_prediction_records([impossible_review], expected_arm="local")


def test_benchmark_reports_human_correction_rate_and_directional_new_errors() -> None:
    gold = parse_gold_records([_gold("synthetic-lab-001", [_field("ALT", "31")])])
    local = parse_prediction_records(
        [
            _prediction(
                "synthetic-lab-001",
                "local",
                [_field("ALT", "31")],
                review_outcome={"edits": 0, "rejects": 0, "review_time_ms": 40},
            )
        ],
        expected_arm="local",
    )
    assisted = parse_prediction_records(
        [
            _prediction(
                "synthetic-lab-001",
                "assisted",
                [_field("ALT", "3l"), _field("HGB", "129", "g/L", reference="115-150")],
                schema_version="clin-data-relay-prediction-v2",
                review_outcome={"edits": 1, "rejects": 1, "review_time_ms": 90},
            )
        ],
        expected_arm="assisted",
    )

    summary, _ = evaluate_benchmark(
        gold,
        {"local": local, "assisted": assisted},
        bootstrap_samples=100,
        seed=23,
    )

    assisted_summary = summary["arms"]["assisted"]
    assert assisted_summary["human_review"] == {
        "observed_report_count": 1,
        "observed_report_visit_count": 1,
        "reviewed_candidate_count": 2,
        "unchanged_accept_count": 0,
        "edit_count": 1,
        "reject_count": 1,
        "correction_count": 2,
        "correction_rate": 1.0,
        "correction_rate_confidence_interval_95": {"lower": 1.0, "upper": 1.0},
        "total_review_time_ms": 90,
    }
    assert assisted_summary["availability"]["abstention_count"] == 0
    assert assisted_summary["availability"]["abstention_rate"] == 0.0
    assert assisted_summary["availability"]["rate_confidence_intervals_95"]["abstention_rate"] == {
        "lower": 0.0,
        "upper": 0.0,
    }
    transitions = summary["paired_comparisons"][0]["field_transitions"]
    assert transitions["evaluable_slot_count"] == 2
    assert transitions["corrected_error_count"] == 0
    assert transitions["introduced_error_count"] == 2
    assert transitions["net_corrected_minus_introduced_count"] == -2


def test_review_and_availability_counts_distinguish_reports_from_visits() -> None:
    gold_records = [
        _gold("synthetic-lab-001", [_field("ALT", "31")]),
        _gold("synthetic-lab-001", [_field("ALT", "32")]),
        _gold("synthetic-lab-002", [_field("ALT", "33")]),
    ]
    gold_records[1]["visit_ref"] = "FOLLOWUP"
    prediction_records = [
        _prediction(
            "synthetic-lab-001",
            "local",
            [_field("ALT", "31")],
            review_outcome={"edits": 1, "rejects": 0, "review_time_ms": 10},
        ),
        _prediction(
            "synthetic-lab-001",
            "local",
            [_field("ALT", "32")],
            review_outcome={"edits": 1, "rejects": 0, "review_time_ms": 20},
        ),
        _prediction(
            "synthetic-lab-002",
            "local",
            [_field("ALT", "33")],
            review_outcome={"edits": 0, "rejects": 0, "review_time_ms": 30},
        ),
    ]
    prediction_records[1]["visit_ref"] = "FOLLOWUP"

    summary, _ = evaluate_benchmark(
        parse_gold_records(gold_records),
        {"local": parse_prediction_records(prediction_records, expected_arm="local")},
        bootstrap_samples=100,
        seed=29,
    )

    availability = summary["arms"]["local"]["availability"]
    review = summary["arms"]["local"]["human_review"]
    assert availability["report_count"] == 2
    assert availability["report_visit_count"] == 3
    assert availability["rate_denominator_report_visit_count"] == 3
    assert review["observed_report_count"] == 2
    assert review["observed_report_visit_count"] == 3
    assert review["reviewed_candidate_count"] == 3


def test_benchmark_command_writes_new_value_free_package_and_refuses_overwrite(tmp_path: Path) -> None:
    gold, local, assisted = _records()
    gold_path = tmp_path / "gold.jsonl"
    local_path = tmp_path / "local.jsonl"
    assisted_path = tmp_path / "assisted.jsonl"
    source_payloads = [
        (gold_path, [_gold(
            report.report_id,
            [
                _field(field.field_code, field.value, field.unit, field.comparator, field.reference_interval)
                for field in report.fields
            ],
            privacy_gate_expected=report.privacy_gate_expected,
        ) for report in gold]),
        (local_path, [_prediction(report.report_id, "local", [
            _field(field.field_code, field.value, field.unit, field.comparator, field.reference_interval)
            for field in report.fields
        ], privacy_gate_decision=report.privacy_gate_decision) for report in local]),
        (assisted_path, [_prediction(report.report_id, "assisted", [
            _field(field.field_code, field.value, field.unit, field.comparator, field.reference_interval)
            for field in report.fields
        ], privacy_gate_decision=report.privacy_gate_decision) for report in assisted]),
    ]
    for path, payloads in source_payloads:
        path.write_text("".join(json.dumps(payload) + "\n" for payload in payloads), encoding="utf-8")
    output_dir = tmp_path / "evaluation-package"
    command = [
        sys.executable,
        "scripts/evaluate_extraction_benchmark.py",
        "--gold",
        str(gold_path),
        "--predictions",
        f"local={local_path}",
        "--predictions",
        f"assisted={assisted_path}",
        "--output-dir",
        str(output_dir),
        "--bootstrap-samples",
        "100",
        "--seed",
        "17",
    ]

    completed = subprocess.run(command, check=False, capture_output=True, text=True)

    assert completed.returncode == 0, completed.stderr
    assert {path.name for path in output_dir.iterdir()} == {"summary.json", "errors.csv", "manifest.json"}
    error_text = (output_dir / "errors.csv").read_text(encoding="utf-8")
    assert "character_or_digit_recognition" in error_text
    assert "3l" not in error_text
    assert "129" not in error_text
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["schema_version"] == "clin-data-relay-benchmark-summary-v2"
    assert manifest["schema_version"] == "clin-data-relay-benchmark-package-v2"
    assert manifest["reporting_boundary"] == "SYNTHETIC_METRIC_ENGINE_ONLY_NOT_CLINICAL_VALIDATION"
    assert all(len(item["sha256"]) == 64 for item in manifest["outputs"])

    repeated = subprocess.run(command, check=False, capture_output=True, text=True)
    assert repeated.returncode == 2
    assert json.loads(repeated.stderr)["code"] == "benchmark_output_exists"


def test_synthetic_metric_engine_fixture_manifest_matches_tracked_bytes() -> None:
    fixture_root = Path("benchmarks/synthetic-v0.1")
    manifest = json.loads((fixture_root / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["purpose"] == "DEMONSTRATION_ONLY"
    assert manifest["report_count"] == 3
    for artifact in manifest["artifacts"]:
        content = (fixture_root / artifact["name"]).read_bytes()
        assert len(content) == artifact["bytes"]
        assert hashlib.sha256(content).hexdigest() == artifact["sha256"]
