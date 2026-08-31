"""Prepare blinded Benchmark v1 review, adjudication and prediction evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable, Iterable, Mapping

from app.benchmark_evaluation import (
    GOLD_SCHEMA_VERSION,
    PREDICTION_SCHEMA_VERSION,
    BenchmarkValidationError,
    load_jsonl,
    parse_gold_records,
    parse_prediction_records,
)


ALLOCATION_SCHEMA = "clin-data-relay-benchmark-allocation-v1"
ANNOTATION_SCHEMA = "clin-data-relay-annotation-v1"
KIT_MANIFEST_SCHEMA = "clin-data-relay-review-kit-manifest-v1"
KIT_CUSTODY_SCHEMA = "clin-data-relay-review-kit-custody-manifest-v1"
ANNOTATION_MANIFEST_SCHEMA = "clin-data-relay-annotation-evidence-manifest-v1"
ADJUDICATION_MANIFEST_SCHEMA = "clin-data-relay-adjudication-worklist-manifest-v1"
GOLD_MANIFEST_SCHEMA = "clin-data-relay-gold-package-manifest-v1"
PREDICTION_FREEZE_SCHEMA = "clin-data-relay-prediction-freeze-manifest-v1"
BENCHMARK_ID = "synthetic-benchmark-v1"
REVIEWERS = ("reviewer_a", "reviewer_b")
COMPARATORS = {"": "", "<": "<", "<=": "<=", "≤": "<=", ">": ">", ">=": ">=", "≥": ">="}
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
ASSIGNMENT_COLUMNS = (
    "report_id",
    "source_path",
    "source_sha256",
    "report_type",
    "primary_challenge",
    "double_review_required",
)
ADJUDICATION_COLUMNS = (
    "report_id",
    "field_code",
    "reviewer_a_json",
    "reviewer_b_json",
    "resolution",
    "custom_json",
    "reason",
)


class WorkflowError(ValueError):
    """Raised when an evidence artifact violates the frozen workflow."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _metadata(path: Path, *, name: str | None = None) -> dict[str, object]:
    return {"name": name or path.name, "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _artifact(root: Path, path: Path) -> dict[str, object]:
    relative = path.relative_to(root).as_posix()
    return {"path": relative, "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, records: Iterable[Mapping[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )


def _publish(output_dir: Path, builder: Callable[[Path], dict[str, int | str]]) -> dict[str, int | str]:
    if output_dir.exists():
        raise WorkflowError("benchmark_workflow_output_exists")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        result = builder(temporary)
        os.replace(temporary, output_dir)
        return result
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _load_json(path: Path, code: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise WorkflowError(code) from error
    if not isinstance(payload, dict):
        raise WorkflowError(code)
    return payload


def _freeze_hashes(freeze_path: Path) -> tuple[dict[str, str], str]:
    freeze = _load_json(freeze_path, "benchmark_workflow_freeze_invalid")
    inputs = freeze.get("inputs")
    local_check = freeze.get("local_reproducibility_check")
    if not isinstance(inputs, list) or not isinstance(local_check, dict):
        raise WorkflowError("benchmark_workflow_freeze_invalid")
    hashes: dict[str, str] = {}
    for item in inputs:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("sha256"), str):
            raise WorkflowError("benchmark_workflow_freeze_invalid")
        hashes[str(item["path"])] = str(item["sha256"])
    source_hash = local_check.get("source_manifest_sha256")
    if not isinstance(source_hash, str):
        raise WorkflowError("benchmark_workflow_freeze_invalid")
    return hashes, source_hash


def _verify_frozen_input(path: Path, expected_name: str, hashes: Mapping[str, str]) -> None:
    if hashes.get(expected_name) != _sha256(path):
        raise WorkflowError("benchmark_workflow_frozen_input_mismatch")


def _allocation(path: Path) -> tuple[dict[str, dict[str, object]], dict[str, set[str]], set[str]]:
    payload = _load_json(path, "benchmark_workflow_allocation_invalid")
    reports = payload.get("reports")
    if (
        payload.get("schema_version") != ALLOCATION_SCHEMA
        or payload.get("benchmark_id") != BENCHMARK_ID
        or not isinstance(reports, list)
        or len(reports) != 150
    ):
        raise WorkflowError("benchmark_workflow_allocation_invalid")
    locked: dict[str, dict[str, object]] = {}
    for raw in reports:
        if not isinstance(raw, dict) or not isinstance(raw.get("report_id"), str):
            raise WorkflowError("benchmark_workflow_allocation_invalid")
        if raw.get("split") != "locked_test":
            continue
        report_id = str(raw["report_id"])
        if (
            report_id in locked
            or not isinstance(raw.get("double_review_required"), bool)
            or not isinstance(raw.get("report_type"), str)
            or not isinstance(raw.get("primary_challenge"), str)
            or not raw["report_type"]
            or not raw["primary_challenge"]
        ):
            raise WorkflowError("benchmark_workflow_allocation_invalid")
        locked[report_id] = raw
    if len(locked) != 120:
        raise WorkflowError("benchmark_workflow_allocation_invalid")
    double_ids = {report_id for report_id, report in locked.items() if report["double_review_required"]}
    if len(double_ids) != 30:
        raise WorkflowError("benchmark_workflow_allocation_invalid")
    assignments = {reviewer: set(double_ids) for reviewer in REVIEWERS}
    non_double = sorted(set(locked) - double_ids)
    for index, report_id in enumerate(non_double):
        assignments[REVIEWERS[index % 2]].add(report_id)
    if any(len(assignments[reviewer]) != 75 for reviewer in REVIEWERS):
        raise WorkflowError("benchmark_workflow_allocation_invalid")
    return locked, assignments, double_ids


def _verified_sources(corpus_dir: Path, freeze_path: Path) -> dict[str, dict[str, object]]:
    manifest_path = corpus_dir / "manifests/source-manifest.json"
    _, expected_hash = _freeze_hashes(freeze_path)
    if _sha256(manifest_path) != expected_hash:
        raise WorkflowError("benchmark_workflow_source_manifest_mismatch")
    manifest = _load_json(manifest_path, "benchmark_workflow_source_manifest_invalid")
    artifacts = manifest.get("artifacts")
    if (
        manifest.get("benchmark_id") != BENCHMARK_ID
        or not isinstance(artifacts, list)
        or len(artifacts) != 150
    ):
        raise WorkflowError("benchmark_workflow_source_manifest_invalid")
    sources: dict[str, dict[str, object]] = {}
    for item in artifacts:
        if not isinstance(item, dict):
            raise WorkflowError("benchmark_workflow_source_manifest_invalid")
        report_id = item.get("report_id")
        relative = item.get("path")
        expected_bytes = item.get("bytes")
        expected_sha = item.get("sha256")
        if (
            not isinstance(report_id, str)
            or report_id in sources
            or not isinstance(relative, str)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or isinstance(expected_bytes, bool)
            or not isinstance(expected_bytes, int)
            or not isinstance(expected_sha, str)
        ):
            raise WorkflowError("benchmark_workflow_source_manifest_invalid")
        source = corpus_dir / Path(relative)
        if not source.is_file() or source.stat().st_size != expected_bytes or _sha256(source) != expected_sha:
            raise WorkflowError("benchmark_workflow_source_hash_mismatch")
        sources[report_id] = {**item, "absolute_path": source}
    return sources


def _csv_writer(path: Path, columns: tuple[str, ...]) -> tuple[object, csv.DictWriter]:
    handle = path.open("w", encoding="utf-8-sig", newline="")
    writer = csv.DictWriter(handle, fieldnames=columns)
    writer.writeheader()
    return handle, writer


def prepare_review_kits(
    *,
    corpus_dir: Path,
    allocation_path: Path,
    freeze_path: Path,
    lab_dictionary: Path,
    pulmonary_dictionary: Path,
    output_dir: Path,
) -> dict[str, int | str]:
    locked, assignments, _ = _allocation(allocation_path)
    frozen_hashes, _ = _freeze_hashes(freeze_path)
    _verify_frozen_input(
        allocation_path, "benchmarks/synthetic-v1/dataset-plan.json", frozen_hashes
    )
    sources = _verified_sources(corpus_dir, freeze_path)
    if not set(locked).issubset(sources):
        raise WorkflowError("benchmark_workflow_locked_sources_missing")
    if not lab_dictionary.is_file() or not pulmonary_dictionary.is_file():
        raise WorkflowError("benchmark_workflow_dictionary_missing")

    def build(root: Path) -> dict[str, int | str]:
        kit_manifests: list[dict[str, object]] = []
        for reviewer in REVIEWERS:
            kit_name = reviewer.replace("_", "-")
            kit = root / kit_name
            source_dir = kit / "sources"
            source_dir.mkdir(parents=True)
            dictionary_dir = kit / "dictionary"
            dictionary_dir.mkdir()
            for dictionary in (lab_dictionary, pulmonary_dictionary):
                shutil.copyfile(dictionary, dictionary_dir / dictionary.name)
            assignment_path = kit / "assignments.csv"
            handle, writer = _csv_writer(assignment_path, ASSIGNMENT_COLUMNS)
            with handle:
                for report_id in sorted(assignments[reviewer]):
                    report = locked[report_id]
                    source_info = sources[report_id]
                    source = source_info["absolute_path"]
                    destination = source_dir / Path(str(source_info["path"])).name
                    shutil.copyfile(source, destination)
                    writer.writerow(
                        {
                            "report_id": report_id,
                            "source_path": destination.relative_to(kit).as_posix(),
                            "source_sha256": source_info["sha256"],
                            "report_type": report["report_type"],
                            "primary_challenge": report["primary_challenge"],
                            "double_review_required": str(bool(report["double_review_required"])).lower(),
                        }
                    )
            annotation_path = kit / "annotations.csv"
            handle, _ = _csv_writer(annotation_path, ANNOTATION_COLUMNS)
            handle.close()
            instructions = kit / "README.txt"
            instructions.write_text(
                "Benchmark v1 blinded annotation kit\n"
                "\n"
                "Open assignments.csv to find your assigned synthetic reports.\n"
                "Use the supplied dictionary and enter one field per row in annotations.csv.\n"
                "Repeat report_id for every field.\n"
                "Do not obtain construction truth, the other reviewer's work or system predictions.\n"
                "Leave all four evidence columns empty together when a region cannot be represented.\n"
                "Return the complete extracted folder to the corpus custodian.\n",
                encoding="utf-8",
            )
            immutable = [
                assignment_path,
                instructions,
                *sorted(dictionary_dir.iterdir()),
                *sorted(source_dir.iterdir()),
            ]
            kit_manifest = kit / "manifest.json"
            _write_json(
                kit_manifest,
                {
                    "schema_version": KIT_MANIFEST_SCHEMA,
                    "benchmark_id": BENCHMARK_ID,
                    "reviewer_slot": reviewer,
                    "report_count": 75,
                    "immutable_artifacts": [_artifact(kit, path) for path in immutable],
                    "editable_artifact": "annotations.csv",
                    "reporting_boundary": "BLINDED_SYNTHETIC_REVIEW_KIT_NO_TRUTH_NO_PREDICTIONS",
                },
            )
            kit_manifests.append(
                {"reviewer_slot": reviewer, **_metadata(kit_manifest, name=f"{kit_name}/manifest.json")}
            )
        _write_json(
            root / "custody-manifest.json",
            {
                "schema_version": KIT_CUSTODY_SCHEMA,
                "benchmark_id": BENCHMARK_ID,
                "allocation": _metadata(allocation_path),
                "corpus_source_manifest": _metadata(corpus_dir / "manifests/source-manifest.json"),
                "review_kits": kit_manifests,
                "reporting_boundary": "CENTRAL_CUSTODY_ANCHOR_KEEP_SEPARATE_FROM_REVIEWERS",
            },
        )
        return {"status": "ok", "reviewer_count": 2, "reports_per_reviewer": 75}

    return _publish(output_dir, build)


def _read_csv(path: Path, columns: tuple[str, ...], code: str) -> list[dict[str, str]]:
    if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise WorkflowError(code)
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != columns:
                raise WorkflowError(code)
            rows = [dict(row) for row in reader if any(str(value or "").strip() for value in row.values())]
    except (OSError, csv.Error) as error:
        raise WorkflowError(code) from error
    return rows


def _verify_kit(kit: Path) -> tuple[str, dict[str, dict[str, str]], Path]:
    manifest_path = kit / "manifest.json"
    manifest = _load_json(manifest_path, "benchmark_review_kit_manifest_invalid")
    artifacts = manifest.get("immutable_artifacts")
    reviewer = manifest.get("reviewer_slot")
    if (
        manifest.get("schema_version") != KIT_MANIFEST_SCHEMA
        or manifest.get("benchmark_id") != BENCHMARK_ID
        or reviewer not in REVIEWERS
        or manifest.get("report_count") != 75
        or manifest.get("editable_artifact") != "annotations.csv"
        or not isinstance(artifacts, list)
    ):
        raise WorkflowError("benchmark_review_kit_manifest_invalid")
    for artifact in artifacts:
        if not isinstance(artifact, dict) or set(artifact) != {"path", "bytes", "sha256"}:
            raise WorkflowError("benchmark_review_kit_manifest_invalid")
        relative = artifact["path"]
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise WorkflowError("benchmark_review_kit_manifest_invalid")
        path = kit / Path(relative)
        if (
            not path.is_file()
            or path.stat().st_size != artifact["bytes"]
            or _sha256(path) != artifact["sha256"]
        ):
            raise WorkflowError("benchmark_review_kit_hash_mismatch")
    assignments = _read_csv(
        kit / "assignments.csv", ASSIGNMENT_COLUMNS, "benchmark_review_assignments_invalid"
    )
    by_id = {row["report_id"].strip(): row for row in assignments}
    if len(assignments) != 75 or len(by_id) != 75 or any(not report_id for report_id in by_id):
        raise WorkflowError("benchmark_review_assignments_invalid")
    return str(reviewer), by_id, manifest_path


def _text(value: object, *, code: str, limit: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise WorkflowError(code)
    result = value.strip()
    if (not result and not allow_empty) or len(result) > limit or any(ord(char) < 32 for char in result):
        raise WorkflowError(code)
    return result


def _annotation_field(row: Mapping[str, str]) -> dict[str, object]:
    field_code = _text(row.get("field_code"), code="benchmark_review_field_invalid", limit=64).upper()
    comparator_raw = _text(
        row.get("comparator"), code="benchmark_review_field_invalid", limit=2, allow_empty=True
    )
    if comparator_raw not in COMPARATORS:
        raise WorkflowError("benchmark_review_field_invalid")
    page_text = _text(row.get("page_number"), code="benchmark_review_field_invalid", limit=4)
    try:
        page_number = int(page_text)
    except ValueError as error:
        raise WorkflowError("benchmark_review_field_invalid") from error
    if page_number < 1:
        raise WorkflowError("benchmark_review_field_invalid")
    region_values = [
        _text(row.get(column), code="benchmark_review_field_invalid", limit=20, allow_empty=True)
        for column in ANNOTATION_COLUMNS[-4:]
    ]
    if all(not value for value in region_values):
        region: list[float] | None = None
    elif any(not value for value in region_values):
        raise WorkflowError("benchmark_review_field_invalid")
    else:
        try:
            region = [float(value) for value in region_values]
        except ValueError as error:
            raise WorkflowError("benchmark_review_field_invalid") from error
        x, y, width, height = region
        if (
            any(not 0 <= value <= 1 for value in region)
            or width <= 0
            or height <= 0
            or x + width > 1.000001
            or y + height > 1.000001
        ):
            raise WorkflowError("benchmark_review_field_invalid")
    return {
        "field_code": field_code,
        "displayed_label": _text(
            row.get("displayed_label"), code="benchmark_review_field_invalid", limit=200
        ),
        "value": _text(row.get("value"), code="benchmark_review_field_invalid", limit=200),
        "comparator": COMPARATORS[comparator_raw],
        "unit": _text(row.get("unit"), code="benchmark_review_field_invalid", limit=50, allow_empty=True),
        "reference_interval": _text(
            row.get("reference_interval"),
            code="benchmark_review_field_invalid",
            limit=100,
            allow_empty=True,
        ),
        "page_number": page_number,
        "evidence_region": region,
    }


def _validate_gold_shaped(record: Mapping[str, object]) -> None:
    parse_gold_records(
        [
            {
                "schema_version": GOLD_SCHEMA_VERSION,
                "report_id": record["report_id"],
                "visit_ref": record["visit_ref"],
                "report_type": record["report_type"],
                "challenge_classes": record["challenge_classes"],
                "privacy_gate_expected": record["privacy_gate_expected"],
                "fields": record["fields"],
            }
        ]
    )


def _verify_custody_manifest(path: Path, reviewer: str, kit_manifest: Path) -> None:
    payload = _load_json(path, "benchmark_review_custody_manifest_invalid")
    kits = payload.get("review_kits")
    if (
        payload.get("schema_version") != KIT_CUSTODY_SCHEMA
        or payload.get("benchmark_id") != BENCHMARK_ID
        or not isinstance(kits, list)
    ):
        raise WorkflowError("benchmark_review_custody_manifest_invalid")
    matching = [item for item in kits if isinstance(item, dict) and item.get("reviewer_slot") == reviewer]
    if len(matching) != 1:
        raise WorkflowError("benchmark_review_custody_manifest_invalid")
    anchor = matching[0]
    if anchor.get("bytes") != kit_manifest.stat().st_size or anchor.get("sha256") != _sha256(kit_manifest):
        raise WorkflowError("benchmark_review_custody_hash_mismatch")


def compile_review(
    *, review_kit: Path, custody_manifest: Path, output_dir: Path
) -> dict[str, int | str]:
    reviewer, assignments, manifest_path = _verify_kit(review_kit)
    _verify_custody_manifest(custody_manifest, reviewer, manifest_path)
    csv_path = review_kit / "annotations.csv"
    rows = _read_csv(csv_path, ANNOTATION_COLUMNS, "benchmark_review_csv_invalid")
    fields_by_report: dict[str, list[dict[str, object]]] = {report_id: [] for report_id in assignments}
    for row in rows:
        report_id = _text(row.get("report_id"), code="benchmark_review_report_invalid", limit=200)
        if report_id not in fields_by_report:
            raise WorkflowError("benchmark_review_report_not_assigned")
        fields_by_report[report_id].append(_annotation_field(row))
    if any(not fields for fields in fields_by_report.values()):
        raise WorkflowError("benchmark_review_report_incomplete")

    records: list[dict[str, object]] = []
    for report_id in sorted(fields_by_report):
        assignment = assignments[report_id]
        fields = sorted(fields_by_report[report_id], key=lambda item: str(item["field_code"]))
        record = {
            "schema_version": ANNOTATION_SCHEMA,
            "benchmark_id": BENCHMARK_ID,
            "report_id": report_id,
            "visit_ref": "BASELINE",
            "reviewer_slot": reviewer,
            "source_sha256": assignment["source_sha256"],
            "report_type": assignment["report_type"],
            "challenge_classes": [assignment["primary_challenge"]],
            "privacy_gate_expected": "allow",
            "annotation_status": "complete",
            "fields": fields,
        }
        _validate_gold_shaped(record)
        records.append(record)

    def build(root: Path) -> dict[str, int | str]:
        completed_csv = root / "completed-annotations.csv"
        shutil.copyfile(csv_path, completed_csv)
        annotations = root / "annotations.jsonl"
        _write_jsonl(annotations, records)
        _write_json(
            root / "manifest.json",
            {
                "schema_version": ANNOTATION_MANIFEST_SCHEMA,
                "benchmark_id": BENCHMARK_ID,
                "reviewer_slot": reviewer,
                "report_count": len(records),
                "inputs": [
                    _metadata(custody_manifest),
                    _metadata(manifest_path, name="review-kit-manifest.json"),
                    _metadata(review_kit / "assignments.csv"),
                    _metadata(csv_path),
                ],
                "outputs": [_artifact(root, completed_csv), _artifact(root, annotations)],
                "reporting_boundary": "INDEPENDENT_HUMAN_ANNOTATION_NOT_ADJUDICATED_GOLD",
            },
        )
        return {"status": "ok", "reviewer_slot": reviewer, "report_count": len(records)}

    return _publish(output_dir, build)


def _canonical_field(raw: object) -> dict[str, object]:
    if not isinstance(raw, Mapping):
        raise WorkflowError("benchmark_review_annotation_invalid")
    expected = {
        "field_code",
        "displayed_label",
        "value",
        "comparator",
        "unit",
        "reference_interval",
        "page_number",
        "evidence_region",
    }
    if set(raw) != expected:
        raise WorkflowError("benchmark_review_annotation_invalid")
    row = {
        "field_code": str(raw["field_code"]),
        "displayed_label": str(raw["displayed_label"]),
        "value": str(raw["value"]),
        "comparator": str(raw["comparator"]),
        "unit": str(raw["unit"]),
        "reference_interval": str(raw["reference_interval"]),
        "page_number": str(raw["page_number"]),
        "evidence_x": "",
        "evidence_y": "",
        "evidence_width": "",
        "evidence_height": "",
    }
    region = raw["evidence_region"]
    if region is not None:
        if not isinstance(region, list) or len(region) != 4:
            raise WorkflowError("benchmark_review_annotation_invalid")
        for column, value in zip(ANNOTATION_COLUMNS[-4:], region, strict=True):
            row[column] = str(value)
    return _annotation_field(row)


def _load_annotations(path: Path, expected_reviewer: str) -> dict[str, dict[str, object]]:
    manifest_path = path.parent / "manifest.json"
    manifest = _load_json(manifest_path, "benchmark_review_annotation_manifest_invalid")
    outputs = manifest.get("outputs")
    if (
        manifest.get("schema_version") != ANNOTATION_MANIFEST_SCHEMA
        or manifest.get("benchmark_id") != BENCHMARK_ID
        or manifest.get("reviewer_slot") != expected_reviewer
        or not isinstance(outputs, list)
    ):
        raise WorkflowError("benchmark_review_annotation_manifest_invalid")
    matching = [
        item for item in outputs if isinstance(item, dict) and item.get("path") == "annotations.jsonl"
    ]
    if (
        len(matching) != 1
        or matching[0].get("bytes") != path.stat().st_size
        or matching[0].get("sha256") != _sha256(path)
    ):
        raise WorkflowError("benchmark_review_annotation_hash_mismatch")
    required = {
        "schema_version",
        "benchmark_id",
        "report_id",
        "visit_ref",
        "reviewer_slot",
        "source_sha256",
        "report_type",
        "challenge_classes",
        "privacy_gate_expected",
        "annotation_status",
        "fields",
    }
    records: dict[str, dict[str, object]] = {}
    try:
        raw_records = load_jsonl(path)
    except BenchmarkValidationError as error:
        raise WorkflowError("benchmark_review_annotation_invalid") from error
    for raw in raw_records:
        if set(raw) != required or raw.get("schema_version") != ANNOTATION_SCHEMA:
            raise WorkflowError("benchmark_review_annotation_invalid")
        if (
            raw.get("benchmark_id") != BENCHMARK_ID
            or raw.get("reviewer_slot") != expected_reviewer
            or raw.get("visit_ref") != "BASELINE"
            or raw.get("privacy_gate_expected") != "allow"
            or raw.get("annotation_status") != "complete"
            or not isinstance(raw.get("fields"), list)
        ):
            raise WorkflowError("benchmark_review_annotation_invalid")
        report_id = raw.get("report_id")
        source_sha = raw.get("source_sha256")
        if (
            not isinstance(report_id, str)
            or report_id in records
            or not isinstance(source_sha, str)
            or len(source_sha) != 64
        ):
            raise WorkflowError("benchmark_review_annotation_invalid")
        record = dict(raw)
        record["fields"] = [_canonical_field(field) for field in raw["fields"]]
        if not record["fields"]:
            raise WorkflowError("benchmark_review_annotation_invalid")
        _validate_gold_shaped(record)
        records[report_id] = record
    return records


def _validate_review_sets(
    allocation_path: Path, reviewer_a_path: Path, reviewer_b_path: Path
) -> tuple[
    dict[str, dict[str, object]],
    set[str],
    dict[str, dict[str, object]],
    dict[str, dict[str, object]],
]:
    locked, assignments, double_ids = _allocation(allocation_path)
    reviewer_a = _load_annotations(reviewer_a_path, "reviewer_a")
    reviewer_b = _load_annotations(reviewer_b_path, "reviewer_b")
    if set(reviewer_a) != assignments["reviewer_a"] or set(reviewer_b) != assignments["reviewer_b"]:
        raise WorkflowError("benchmark_review_assignment_coverage_mismatch")
    if set(reviewer_a) & set(reviewer_b) != double_ids or set(reviewer_a) | set(reviewer_b) != set(locked):
        raise WorkflowError("benchmark_review_assignment_coverage_mismatch")
    for reviewer_records in (reviewer_a, reviewer_b):
        for report_id, record in reviewer_records.items():
            expected = locked[report_id]
            if (
                record["report_type"] != expected["report_type"]
                or record["challenge_classes"] != [expected["primary_challenge"]]
            ):
                raise WorkflowError("benchmark_review_annotation_metadata_mismatch")
    for report_id in double_ids:
        if reviewer_a[report_id]["source_sha256"] != reviewer_b[report_id]["source_sha256"]:
            raise WorkflowError("benchmark_review_source_mismatch")
    return locked, double_ids, reviewer_a, reviewer_b


def _field_maps(record: Mapping[str, object]) -> dict[str, dict[str, object]]:
    return {str(field["field_code"]): dict(field) for field in record["fields"]}  # type: ignore[index]


def _discrepancies(
    double_ids: set[str], reviewer_a: Mapping[str, Mapping[str, object]], reviewer_b: Mapping[str, Mapping[str, object]]
) -> tuple[list[dict[str, str]], int]:
    rows: list[dict[str, str]] = []
    exact_reports = 0
    for report_id in sorted(double_ids):
        a_fields = _field_maps(reviewer_a[report_id])
        b_fields = _field_maps(reviewer_b[report_id])
        if a_fields == b_fields:
            exact_reports += 1
            continue
        for field_code in sorted(set(a_fields) | set(b_fields)):
            a_field = a_fields.get(field_code)
            b_field = b_fields.get(field_code)
            if a_field == b_field:
                continue
            rows.append(
                {
                    "report_id": report_id,
                    "field_code": field_code,
                    "reviewer_a_json": "" if a_field is None else json.dumps(a_field, sort_keys=True, separators=(",", ":")),
                    "reviewer_b_json": "" if b_field is None else json.dumps(b_field, sort_keys=True, separators=(",", ":")),
                    "resolution": "",
                    "custom_json": "",
                    "reason": "",
                }
            )
    return rows, exact_reports


def prepare_adjudication(
    *, allocation_path: Path, reviewer_a_path: Path, reviewer_b_path: Path, output_dir: Path
) -> dict[str, int | str]:
    _, double_ids, reviewer_a, reviewer_b = _validate_review_sets(
        allocation_path, reviewer_a_path, reviewer_b_path
    )
    rows, exact_reports = _discrepancies(double_ids, reviewer_a, reviewer_b)
    discrepant_reports = len({row["report_id"] for row in rows})

    def build(root: Path) -> dict[str, int | str]:
        csv_path = root / "adjudication.csv"
        handle, writer = _csv_writer(csv_path, ADJUDICATION_COLUMNS)
        with handle:
            writer.writerows(rows)
        summary_path = root / "agreement-summary.json"
        _write_json(
            summary_path,
            {
                "schema_version": "clin-data-relay-annotation-agreement-summary-v1",
                "benchmark_id": BENCHMARK_ID,
                "double_review_report_count": 30,
                "exact_agreement_report_count": exact_reports,
                "discrepant_report_count": discrepant_reports,
                "discrepancy_slot_count": len(rows),
                "reporting_boundary": "ANNOTATION_REPRODUCIBILITY_NOT_CONSTRUCTION_VALIDATION",
            },
        )
        _write_json(
            root / "manifest.json",
            {
                "schema_version": ADJUDICATION_MANIFEST_SCHEMA,
                "benchmark_id": BENCHMARK_ID,
                "inputs": [_metadata(reviewer_a_path), _metadata(reviewer_b_path)],
                "outputs": [_artifact(root, csv_path), _artifact(root, summary_path)],
                "editable_artifact": "adjudication.csv",
                "reporting_boundary": "THIRD_PERSON_RESOLUTION_REQUIRED_NOT_GOLD",
            },
        )
        return {
            "status": "ok",
            "double_review_report_count": 30,
            "exact_agreement_report_count": exact_reports,
            "discrepant_report_count": discrepant_reports,
            "discrepancy_slot_count": len(rows),
        }

    return _publish(output_dir, build)


def _json_field(value: str, *, expected_code: str, code: str) -> dict[str, object]:
    try:
        raw = json.loads(value)
    except json.JSONDecodeError as error:
        raise WorkflowError(code) from error
    field = _canonical_field(raw)
    if field["field_code"] != expected_code:
        raise WorkflowError(code)
    return field


def finalize_gold(
    *,
    allocation_path: Path,
    reviewer_a_path: Path,
    reviewer_b_path: Path,
    adjudication_csv: Path,
    output_dir: Path,
) -> dict[str, int | str]:
    locked, double_ids, reviewer_a, reviewer_b = _validate_review_sets(
        allocation_path, reviewer_a_path, reviewer_b_path
    )
    expected_rows, exact_reports = _discrepancies(double_ids, reviewer_a, reviewer_b)
    returned_rows = _read_csv(
        adjudication_csv, ADJUDICATION_COLUMNS, "benchmark_adjudication_csv_invalid"
    )
    expected = {(row["report_id"], row["field_code"]): row for row in expected_rows}
    returned = {(row["report_id"], row["field_code"]): row for row in returned_rows}
    if len(returned) != len(returned_rows) or set(returned) != set(expected):
        raise WorkflowError("benchmark_adjudication_coverage_mismatch")

    resolved: dict[tuple[str, str], dict[str, object] | None] = {}
    disagreement_log: list[dict[str, object]] = []
    for key in sorted(expected):
        baseline = expected[key]
        row = returned[key]
        if any(row[column] != baseline[column] for column in ADJUDICATION_COLUMNS[:4]):
            raise WorkflowError("benchmark_adjudication_stale_or_modified")
        resolution = _text(row["resolution"], code="benchmark_adjudication_unresolved", limit=20)
        reason = _text(row["reason"], code="benchmark_adjudication_reason_required", limit=500)
        custom = row["custom_json"].strip()
        if resolution == "reviewer_a":
            if not row["reviewer_a_json"] or custom:
                raise WorkflowError("benchmark_adjudication_resolution_invalid")
            selected = _json_field(row["reviewer_a_json"], expected_code=key[1], code="benchmark_adjudication_resolution_invalid")
        elif resolution == "reviewer_b":
            if not row["reviewer_b_json"] or custom:
                raise WorkflowError("benchmark_adjudication_resolution_invalid")
            selected = _json_field(row["reviewer_b_json"], expected_code=key[1], code="benchmark_adjudication_resolution_invalid")
        elif resolution == "custom":
            if not custom:
                raise WorkflowError("benchmark_adjudication_resolution_invalid")
            selected = _json_field(custom, expected_code=key[1], code="benchmark_adjudication_resolution_invalid")
        elif resolution == "omit":
            if custom:
                raise WorkflowError("benchmark_adjudication_resolution_invalid")
            selected = None
        else:
            raise WorkflowError("benchmark_adjudication_resolution_invalid")
        resolved[key] = selected
        disagreement_log.append(
            {
                "schema_version": "clin-data-relay-adjudication-decision-v1",
                "benchmark_id": BENCHMARK_ID,
                "report_id": key[0],
                "field_code": key[1],
                "reviewer_a_field": None
                if not row["reviewer_a_json"]
                else json.loads(row["reviewer_a_json"]),
                "reviewer_b_field": None
                if not row["reviewer_b_json"]
                else json.loads(row["reviewer_b_json"]),
                "resolution": resolution,
                "resolved_field": selected,
                "reason": reason,
            }
        )

    gold: list[dict[str, object]] = []
    for report_id in sorted(locked):
        if report_id not in double_ids:
            source_record = reviewer_a.get(report_id) or reviewer_b[report_id]
            fields = [dict(field) for field in source_record["fields"]]
        else:
            a_fields = _field_maps(reviewer_a[report_id])
            b_fields = _field_maps(reviewer_b[report_id])
            fields = []
            for field_code in sorted(set(a_fields) | set(b_fields)):
                if a_fields.get(field_code) == b_fields.get(field_code):
                    fields.append(dict(a_fields[field_code]))
                else:
                    selected = resolved[(report_id, field_code)]
                    if selected is not None:
                        fields.append(dict(selected))
        report = locked[report_id]
        record = {
            "schema_version": GOLD_SCHEMA_VERSION,
            "report_id": report_id,
            "visit_ref": "BASELINE",
            "report_type": report["report_type"],
            "challenge_classes": [report["primary_challenge"]],
            "privacy_gate_expected": "allow",
            "fields": sorted(fields, key=lambda field: str(field["field_code"])),
        }
        parse_gold_records([record])
        gold.append(record)

    def build(root: Path) -> dict[str, int | str]:
        gold_path = root / "locked-gold.jsonl"
        log_path = root / "disagreement-log.jsonl"
        summary_path = root / "annotation-summary.json"
        _write_jsonl(gold_path, gold)
        _write_jsonl(log_path, disagreement_log)
        _write_json(
            summary_path,
            {
                "schema_version": "clin-data-relay-final-annotation-summary-v1",
                "benchmark_id": BENCHMARK_ID,
                "single_review_report_count": 90,
                "double_review_report_count": 30,
                "exact_agreement_report_count": exact_reports,
                "discrepant_report_count": len({row["report_id"] for row in expected_rows}),
                "adjudicated_slot_count": len(expected_rows),
                "gold_report_count": len(gold),
                "reporting_boundary": "INDEPENDENT_ANNOTATION_AND_ADJUDICATION_NOT_SYSTEM_OUTPUT",
            },
        )
        _write_json(
            root / "manifest.json",
            {
                "schema_version": GOLD_MANIFEST_SCHEMA,
                "benchmark_id": BENCHMARK_ID,
                "inputs": [
                    _metadata(reviewer_a_path),
                    _metadata(reviewer_b_path),
                    _metadata(adjudication_csv),
                ],
                "outputs": [
                    _artifact(root, gold_path),
                    _artifact(root, log_path),
                    _artifact(root, summary_path),
                ],
                "reporting_boundary": "ADJUDICATED_SYNTHETIC_GOLD_NO_PREDICTIONS_NO_RESULTS",
            },
        )
        return {
            "status": "ok",
            "gold_report_count": len(gold),
            "adjudicated_slot_count": len(expected_rows),
        }

    return _publish(output_dir, build)


def freeze_predictions(
    *,
    allocation_path: Path,
    source_manifest_path: Path,
    freeze_path: Path,
    environment_lock: Path,
    lab_dictionary: Path,
    pulmonary_dictionary: Path,
    model_contract: Path,
    application_commit: str,
    gold_path: Path,
    local_ocr_path: Path,
    assisted_path: Path,
    output_dir: Path,
) -> dict[str, int | str]:
    locked, _, _ = _allocation(allocation_path)
    commit = application_commit.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise WorkflowError("benchmark_prediction_freeze_commit_invalid")
    frozen_hashes, expected_source_hash = _freeze_hashes(freeze_path)
    if _sha256(source_manifest_path) != expected_source_hash:
        raise WorkflowError("benchmark_prediction_freeze_source_manifest_mismatch")
    for path, expected_name in (
        (allocation_path, "benchmarks/synthetic-v1/dataset-plan.json"),
        (environment_lock, "uv.lock"),
        (lab_dictionary, "config/synthetic_lab_mapping.v0.1.json"),
        (pulmonary_dictionary, "config/pulmonary-function-field-dictionary.v1.json"),
    ):
        _verify_frozen_input(path, expected_name, frozen_hashes)
    provenance_files = (
        allocation_path,
        source_manifest_path,
        environment_lock,
        lab_dictionary,
        pulmonary_dictionary,
        model_contract,
    )
    if any(not path.is_file() for path in provenance_files):
        raise WorkflowError("benchmark_prediction_freeze_provenance_missing")
    gold_manifest = _load_json(
        gold_path.parent / "manifest.json", "benchmark_prediction_freeze_gold_manifest_invalid"
    )
    gold_outputs = gold_manifest.get("outputs")
    matching_gold = (
        [
            item
            for item in gold_outputs
            if isinstance(item, dict) and item.get("path") == "locked-gold.jsonl"
        ]
        if isinstance(gold_outputs, list)
        else []
    )
    if (
        gold_manifest.get("schema_version") != GOLD_MANIFEST_SCHEMA
        or len(matching_gold) != 1
        or matching_gold[0].get("bytes") != gold_path.stat().st_size
        or matching_gold[0].get("sha256") != _sha256(gold_path)
    ):
        raise WorkflowError("benchmark_prediction_freeze_gold_manifest_invalid")
    gold_raw = load_jsonl(gold_path)
    gold = parse_gold_records(gold_raw)
    gold_keys = {(record.report_id, record.visit_ref) for record in gold}
    expected_keys = {(report_id, "BASELINE") for report_id in locked}
    if gold_keys != expected_keys:
        raise WorkflowError("benchmark_prediction_freeze_gold_coverage_mismatch")
    arm_paths = {
        "local_ocr": local_ocr_path,
        "local_ocr_plus_model": assisted_path,
    }
    for arm, path in arm_paths.items():
        raw = load_jsonl(path)
        if any(record.get("schema_version") != PREDICTION_SCHEMA_VERSION for record in raw):
            raise WorkflowError("benchmark_prediction_freeze_requires_v2")
        parsed = parse_prediction_records(raw, expected_arm=arm)
        if {(record.report_id, record.visit_ref) for record in parsed} != gold_keys:
            raise WorkflowError("benchmark_prediction_freeze_coverage_mismatch")

    def build(root: Path) -> dict[str, int | str]:
        destinations = {
            "locked-gold.jsonl": gold_path,
            "local-ocr.jsonl": local_ocr_path,
            "local-ocr-plus-model.jsonl": assisted_path,
        }
        for name, source in destinations.items():
            shutil.copyfile(source, root / name)
        _write_json(
            root / "manifest.json",
            {
                "schema_version": PREDICTION_FREEZE_SCHEMA,
                "benchmark_id": BENCHMARK_ID,
                "report_count": 120,
                "application_commit": commit,
                "provenance": [_metadata(path) for path in provenance_files],
                "inputs": [
                    {"role": role, **_metadata(source)}
                    for role, source in (
                        ("gold", gold_path),
                        ("local_ocr", local_ocr_path),
                        ("local_ocr_plus_model", assisted_path),
                    )
                ],
                "frozen_artifacts": [
                    _artifact(root, root / name) for name in sorted(destinations)
                ],
                "reporting_boundary": "PREDICTIONS_FROZEN_NOT_SCORED_NOT_RESULTS",
            },
        )
        return {"status": "ok", "report_count": 120, "arm_count": 2}

    return _publish(output_dir, build)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare Benchmark v1 human-review evidence.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare-review-kits")
    prepare.add_argument("--corpus-dir", type=Path, required=True)
    prepare.add_argument("--allocation", type=Path, required=True)
    prepare.add_argument(
        "--freeze", type=Path, default=Path("benchmarks/synthetic-v1/corpus-freeze.json")
    )
    prepare.add_argument(
        "--lab-dictionary",
        type=Path,
        default=Path("config/synthetic_lab_mapping.v0.1.json"),
    )
    prepare.add_argument(
        "--pulmonary-dictionary",
        type=Path,
        default=Path("config/pulmonary-function-field-dictionary.v1.json"),
    )
    prepare.add_argument("--output-dir", type=Path, required=True)

    compile_parser = subparsers.add_parser("compile-review")
    compile_parser.add_argument("--review-kit", type=Path, required=True)
    compile_parser.add_argument("--custody-manifest", type=Path, required=True)
    compile_parser.add_argument("--output-dir", type=Path, required=True)

    adjudication = subparsers.add_parser("prepare-adjudication")
    adjudication.add_argument("--allocation", type=Path, required=True)
    adjudication.add_argument("--reviewer-a", type=Path, required=True)
    adjudication.add_argument("--reviewer-b", type=Path, required=True)
    adjudication.add_argument("--output-dir", type=Path, required=True)

    finalize = subparsers.add_parser("finalize-gold")
    finalize.add_argument("--allocation", type=Path, required=True)
    finalize.add_argument("--reviewer-a", type=Path, required=True)
    finalize.add_argument("--reviewer-b", type=Path, required=True)
    finalize.add_argument("--adjudication-csv", type=Path, required=True)
    finalize.add_argument("--output-dir", type=Path, required=True)

    freeze = subparsers.add_parser("freeze-predictions")
    freeze.add_argument("--allocation", type=Path, required=True)
    freeze.add_argument("--source-manifest", type=Path, required=True)
    freeze.add_argument(
        "--freeze", type=Path, default=Path("benchmarks/synthetic-v1/corpus-freeze.json")
    )
    freeze.add_argument("--environment-lock", type=Path, default=Path("uv.lock"))
    freeze.add_argument(
        "--lab-dictionary",
        type=Path,
        default=Path("config/synthetic_lab_mapping.v0.1.json"),
    )
    freeze.add_argument(
        "--pulmonary-dictionary",
        type=Path,
        default=Path("config/pulmonary-function-field-dictionary.v1.json"),
    )
    freeze.add_argument("--model-contract", type=Path, default=Path("app/model_provider.py"))
    freeze.add_argument("--application-commit", required=True)
    freeze.add_argument("--gold", type=Path, required=True)
    freeze.add_argument("--local-ocr", type=Path, required=True)
    freeze.add_argument("--assisted", type=Path, required=True)
    freeze.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "prepare-review-kits":
            result = prepare_review_kits(
                corpus_dir=args.corpus_dir,
                allocation_path=args.allocation,
                freeze_path=args.freeze,
                lab_dictionary=args.lab_dictionary,
                pulmonary_dictionary=args.pulmonary_dictionary,
                output_dir=args.output_dir,
            )
        elif args.command == "compile-review":
            result = compile_review(
                review_kit=args.review_kit,
                custody_manifest=args.custody_manifest,
                output_dir=args.output_dir,
            )
        elif args.command == "prepare-adjudication":
            result = prepare_adjudication(
                allocation_path=args.allocation,
                reviewer_a_path=args.reviewer_a,
                reviewer_b_path=args.reviewer_b,
                output_dir=args.output_dir,
            )
        elif args.command == "finalize-gold":
            result = finalize_gold(
                allocation_path=args.allocation,
                reviewer_a_path=args.reviewer_a,
                reviewer_b_path=args.reviewer_b,
                adjudication_csv=args.adjudication_csv,
                output_dir=args.output_dir,
            )
        else:
            result = freeze_predictions(
                allocation_path=args.allocation,
                source_manifest_path=args.source_manifest,
                freeze_path=args.freeze,
                environment_lock=args.environment_lock,
                lab_dictionary=args.lab_dictionary,
                pulmonary_dictionary=args.pulmonary_dictionary,
                model_contract=args.model_contract,
                application_commit=args.application_commit,
                gold_path=args.gold,
                local_ocr_path=args.local_ocr,
                assisted_path=args.assisted,
                output_dir=args.output_dir,
            )
    except (WorkflowError, BenchmarkValidationError) as error:
        print(json.dumps({"status": "error", "code": str(error)}, sort_keys=True), file=sys.stderr)
        return 2
    except (OSError, KeyError, TypeError):
        print(
            json.dumps({"status": "error", "code": "benchmark_workflow_io_error"}, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
