from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path


ALLOCATION = Path("benchmarks/synthetic-v1/dataset-plan.json")
ANNOTATION_COLUMNS = (
    "report_id",
    "field_code",
    "displayed_label",
    "value",
    "comparator",
    "unit",
    "reference_interval",
    "page_number",
    "evidence_x",
    "evidence_y",
    "evidence_width",
    "evidence_height",
)


def _run(*arguments: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/benchmark_v1_workflow.py", *(str(item) for item in arguments)],
        check=False,
        capture_output=True,
        text=True,
    )


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_completed_csv(
    *, kit: Path, construction: dict[str, dict[str, object]], changed_report: str | None = None
) -> None:
    with (kit / "assignments.csv").open(encoding="utf-8-sig", newline="") as handle:
        assignments = list(csv.DictReader(handle))
    with (kit / "annotations.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ANNOTATION_COLUMNS)
        writer.writeheader()
        for assignment in assignments:
            report_id = assignment["report_id"]
            for index, field in enumerate(construction[report_id]["fields"]):
                region = field["evidence_region"] or ["", "", "", ""]
                value = field["value"]
                if report_id == changed_report and index == 0:
                    value = f"{value}9"
                writer.writerow(
                    {
                        "report_id": report_id,
                        "field_code": field["field_code"],
                        "displayed_label": field["displayed_label"],
                        "value": value,
                        "comparator": field["comparator"],
                        "unit": field["unit"],
                        "reference_interval": field["reference_interval"],
                        "page_number": field["page_number"],
                        "evidence_x": region[0],
                        "evidence_y": region[1],
                        "evidence_width": region[2],
                        "evidence_height": region[3],
                    }
                )


def _prediction_records(gold: list[dict[str, object]], arm: str) -> list[dict[str, object]]:
    return [
        {
            "schema_version": "clin-data-relay-prediction-v2",
            "report_id": record["report_id"],
            "visit_ref": record["visit_ref"],
            "arm": arm,
            "status": "completed",
            "privacy_gate_decision": record["privacy_gate_expected"],
            "fields": [
                {
                    key: field[key]
                    for key in (
                        "field_code",
                        "value",
                        "comparator",
                        "unit",
                        "reference_interval",
                        "page_number",
                    )
                }
                for field in record["fields"]
            ],
            "latency_ms": 1,
            "provider_calls": int(arm == "local_ocr_plus_model"),
            "token_usage": {
                "input": int(arm == "local_ocr_plus_model"),
                "output": int(arm == "local_ocr_plus_model"),
            },
            "cost_usd": "0",
            "fallback_reason": "",
            "review_outcome": None,
        }
        for record in gold
    ]


def test_review_adjudication_prediction_freeze_workflow(tmp_path: Path) -> None:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    corpus = tmp_path / "corpus"
    generated = subprocess.run(
        [
            sys.executable,
            "scripts/generate_benchmark_v1_corpus.py",
            "--allocation",
            str(ALLOCATION),
            "--output-dir",
            str(corpus),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert generated.returncode == 0, generated.stderr

    kits = tmp_path / "review-kits"
    prepared = _run(
        "prepare-review-kits",
        "--corpus-dir",
        corpus,
        "--allocation",
        ALLOCATION,
        "--output-dir",
        kits,
    )
    assert prepared.returncode == 0, prepared.stderr
    assert json.loads(prepared.stdout)["reports_per_reviewer"] == 75
    assert not list(kits.rglob("construction-truth"))
    assert not list(kits.rglob("*prediction*"))
    assert len(list((kits / "reviewer-a/sources").iterdir())) == 75
    assert len(list((kits / "reviewer-b/sources").iterdir())) == 75
    assert len(list((kits / "reviewer-a/dictionary").iterdir())) == 2
    assert len(list((kits / "reviewer-b/dictionary").iterdir())) == 2

    allocation = json.loads(ALLOCATION.read_text(encoding="utf-8"))
    changed_report = next(
        item["report_id"] for item in allocation["reports"] if item["double_review_required"]
    )
    construction = {
        item["report_id"]: item
        for item in _jsonl(corpus / "construction-truth/locked-test.jsonl")
    }
    _write_completed_csv(kit=kits / "reviewer-a", construction=construction)
    _write_completed_csv(
        kit=kits / "reviewer-b", construction=construction, changed_report=changed_report
    )

    tampered_source = next((kits / "reviewer-a/sources").iterdir())
    original = tampered_source.read_bytes()
    tampered_source.write_bytes(original + b"tampered")
    rejected = _run(
        "compile-review",
        "--review-kit",
        kits / "reviewer-a",
        "--custody-manifest",
        kits / "custody-manifest.json",
        "--output-dir",
        tmp_path / "rejected-review",
    )
    assert rejected.returncode == 2
    assert json.loads(rejected.stderr)["code"] == "benchmark_review_kit_hash_mismatch"
    tampered_source.write_bytes(original)

    reviewer_a = tmp_path / "reviewer-a-evidence"
    reviewer_b = tmp_path / "reviewer-b-evidence"
    for kit, output in (
        (kits / "reviewer-a", reviewer_a),
        (kits / "reviewer-b", reviewer_b),
    ):
        compiled = _run(
            "compile-review",
            "--review-kit",
            kit,
            "--custody-manifest",
            kits / "custody-manifest.json",
            "--output-dir",
            output,
        )
        assert compiled.returncode == 0, compiled.stderr
        assert json.loads(compiled.stdout)["report_count"] == 75

    adjudication = tmp_path / "adjudication"
    compared = _run(
        "prepare-adjudication",
        "--allocation",
        ALLOCATION,
        "--reviewer-a",
        reviewer_a / "annotations.jsonl",
        "--reviewer-b",
        reviewer_b / "annotations.jsonl",
        "--output-dir",
        adjudication,
    )
    assert compared.returncode == 0, compared.stderr
    comparison = json.loads(compared.stdout)
    assert comparison["double_review_report_count"] == 30
    assert comparison["discrepancy_slot_count"] == 1

    unresolved = _run(
        "finalize-gold",
        "--allocation",
        ALLOCATION,
        "--reviewer-a",
        reviewer_a / "annotations.jsonl",
        "--reviewer-b",
        reviewer_b / "annotations.jsonl",
        "--adjudication-csv",
        adjudication / "adjudication.csv",
        "--output-dir",
        tmp_path / "unresolved-gold",
    )
    assert unresolved.returncode == 2
    assert json.loads(unresolved.stderr)["code"] == "benchmark_adjudication_unresolved"

    rows: list[dict[str, str]]
    with (adjudication / "adjudication.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    rows[0]["resolution"] = "reviewer_a"
    rows[0]["reason"] = "Third-person source review selected reviewer A."
    with (adjudication / "adjudication.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    gold_dir = tmp_path / "gold"
    finalized = _run(
        "finalize-gold",
        "--allocation",
        ALLOCATION,
        "--reviewer-a",
        reviewer_a / "annotations.jsonl",
        "--reviewer-b",
        reviewer_b / "annotations.jsonl",
        "--adjudication-csv",
        adjudication / "adjudication.csv",
        "--output-dir",
        gold_dir,
    )
    assert finalized.returncode == 0, finalized.stderr
    assert json.loads(finalized.stdout)["gold_report_count"] == 120
    gold = _jsonl(gold_dir / "locked-gold.jsonl")
    assert len(gold) == 120
    assert len(_jsonl(gold_dir / "disagreement-log.jsonl")) == 1

    predictions: dict[str, Path] = {}
    for arm in ("local_ocr", "local_ocr_plus_model"):
        path = tmp_path / f"{arm}.jsonl"
        path.write_text(
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in _prediction_records(gold, arm)),
            encoding="utf-8",
        )
        predictions[arm] = path

    frozen = tmp_path / "frozen-inputs"
    freeze = _run(
        "freeze-predictions",
        "--allocation",
        ALLOCATION,
        "--source-manifest",
        corpus / "manifests/source-manifest.json",
        "--application-commit",
        commit,
        "--gold",
        gold_dir / "locked-gold.jsonl",
        "--local-ocr",
        predictions["local_ocr"],
        "--assisted",
        predictions["local_ocr_plus_model"],
        "--output-dir",
        frozen,
    )
    assert freeze.returncode == 0, freeze.stderr
    assert json.loads(freeze.stdout)["report_count"] == 120
    assert (frozen / "manifest.json").is_file()
    assert (frozen / "local-ocr.jsonl").is_file()
    assert (frozen / "local-ocr-plus-model.jsonl").is_file()

    legacy_path = tmp_path / "legacy-local.jsonl"
    legacy_records = _prediction_records(gold, "local_ocr")
    for record in legacy_records:
        record["schema_version"] = "clin-data-relay-prediction-v1"
    legacy_path.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in legacy_records),
        encoding="utf-8",
    )
    legacy_rejected = _run(
        "freeze-predictions",
        "--allocation",
        ALLOCATION,
        "--source-manifest",
        corpus / "manifests/source-manifest.json",
        "--application-commit",
        commit,
        "--gold",
        gold_dir / "locked-gold.jsonl",
        "--local-ocr",
        legacy_path,
        "--assisted",
        predictions["local_ocr_plus_model"],
        "--output-dir",
        tmp_path / "legacy-rejected",
    )
    assert legacy_rejected.returncode == 2
    assert json.loads(legacy_rejected.stderr)["code"] == "benchmark_prediction_freeze_requires_v2"

    repeated = _run(
        "freeze-predictions",
        "--allocation",
        ALLOCATION,
        "--source-manifest",
        corpus / "manifests/source-manifest.json",
        "--application-commit",
        commit,
        "--gold",
        gold_dir / "locked-gold.jsonl",
        "--local-ocr",
        predictions["local_ocr"],
        "--assisted",
        predictions["local_ocr_plus_model"],
        "--output-dir",
        frozen,
    )
    assert repeated.returncode == 2
    assert json.loads(repeated.stderr)["code"] == "benchmark_workflow_output_exists"
