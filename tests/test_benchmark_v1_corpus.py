from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from PIL import Image

from app.pulmonary_function import LocalPulmonaryFunctionPdfParser


ALLOCATION = Path("benchmarks/synthetic-v1/dataset-plan.json")


def _run(output_dir: Path, *, allocation: Path = ALLOCATION) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/generate_benchmark_v1_corpus.py",
            "--allocation",
            str(allocation),
            "--output-dir",
            str(output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _assert_manifest(root: Path, manifest_path: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for artifact in manifest["artifacts"]:
        content = (root / artifact["path"]).read_bytes()
        assert artifact["bytes"] == len(content)
        assert artifact["sha256"] == hashlib.sha256(content).hexdigest()
    return manifest


def test_corpus_is_deterministic_separated_and_manifest_covered(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_run = _run(first)
    second_run = _run(second)

    assert first_run.returncode == 0, first_run.stderr
    assert second_run.returncode == 0, second_run.stderr
    assert _files(first) == _files(second)
    response = json.loads(first_run.stdout)
    assert response == {
        "annotation_template_count": 150,
        "construction_record_count": 150,
        "report_count": 150,
        "status": "ok",
    }

    source_manifest = _assert_manifest(first, first / "manifests/source-manifest.json")
    construction_manifest = _assert_manifest(
        first, first / "manifests/construction-manifest.json"
    )
    annotation_manifest = _assert_manifest(first, first / "manifests/annotation-manifest.json")
    package_manifest = _assert_manifest(first, first / "manifest.json")
    assert source_manifest["reporting_boundary"] == "IDENTIFIER_FREE_SYNTHETIC_SOURCES_NOT_RESULTS"
    assert construction_manifest["reporting_boundary"] == "CONSTRUCTION_TRUTH_NOT_ADJUDICATED_GOLD"
    assert annotation_manifest["reporting_boundary"] == "VALUE_FREE_TEMPLATES_NOT_ANNOTATIONS"
    assert package_manifest["reporting_boundary"] == "CORPUS_MATERIALS_ONLY_EXPERIMENT_NOT_RUN"
    assert len(source_manifest["artifacts"]) == 150
    assert len(construction_manifest["artifacts"]) == 2
    assert len(annotation_manifest["artifacts"]) == 2
    assert len(package_manifest["artifacts"]) == 3

    freeze = json.loads(Path("benchmarks/synthetic-v1/corpus-freeze.json").read_text(encoding="utf-8"))
    checked_hashes = freeze["local_reproducibility_check"]
    assert checked_hashes == {
        "annotation_manifest_sha256": hashlib.sha256(
            (first / "manifests/annotation-manifest.json").read_bytes()
        ).hexdigest(),
        "construction_manifest_sha256": hashlib.sha256(
            (first / "manifests/construction-manifest.json").read_bytes()
        ).hexdigest(),
        "package_manifest_sha256": hashlib.sha256((first / "manifest.json").read_bytes()).hexdigest(),
        "source_manifest_sha256": hashlib.sha256(
            (first / "manifests/source-manifest.json").read_bytes()
        ).hexdigest(),
    }
    for item in freeze["inputs"]:
        assert hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest() == item["sha256"]

    suffix_counts = Counter(Path(item["path"]).suffix for item in source_manifest["artifacts"])
    assert suffix_counts == Counter({".png": 132, ".pdf": 18})
    split_counts = Counter(item["split"] for item in source_manifest["artifacts"])
    assert split_counts == Counter({"development": 30, "locked_test": 120})

    allocation = json.loads(ALLOCATION.read_text(encoding="utf-8"))
    plan_by_id = {item["report_id"]: item for item in allocation["reports"]}
    construction = _jsonl(first / "construction-truth/development.jsonl") + _jsonl(
        first / "construction-truth/locked-test.jsonl"
    )
    assert len(construction) == 150
    assert {item["schema_version"] for item in construction} == {
        "clin-data-relay-construction-truth-v1"
    }
    assert all(item["privacy_gate_expected"] == "allow" for item in construction)
    assert all(
        len(item["fields"]) == plan_by_id[item["report_id"]]["target_field_count"]
        for item in construction
    )

    reviewer_a = _jsonl(first / "annotation-templates/reviewer-a.jsonl")
    reviewer_b = _jsonl(first / "annotation-templates/reviewer-b.jsonl")
    assert len(reviewer_a) == len(reviewer_b) == 75
    assert all(item["annotation_status"] == "not_started" for item in reviewer_a + reviewer_b)
    assert all(item["fields"] == [] for item in reviewer_a + reviewer_b)
    assert all("target_field_count" not in item for item in reviewer_a + reviewer_b)
    assert sum(item["double_review_required"] for item in reviewer_a) == 30
    assert sum(item["double_review_required"] for item in reviewer_b) == 30
    assert {
        item["report_id"] for item in reviewer_a if item["double_review_required"]
    } == {
        item["report_id"] for item in reviewer_b if item["double_review_required"]
    }

    repeated = _run(first)
    assert repeated.returncode == 2
    assert json.loads(repeated.stderr)["code"] == "benchmark_v1_corpus_output_exists"


def test_development_images_and_all_pulmonary_pdfs_are_structurally_usable(tmp_path: Path) -> None:
    output = tmp_path / "corpus"
    completed = _run(output)
    assert completed.returncode == 0, completed.stderr

    for image_path in sorted((output / "sources/development").glob("*.png")):
        with Image.open(image_path) as image:
            image.verify()
            assert image.format == "PNG"
            assert image.width >= 850
            assert image.height >= 650

    construction = {
        item["report_id"]: item
        for item in _jsonl(output / "construction-truth/development.jsonl")
        + _jsonl(output / "construction-truth/locked-test.jsonl")
    }
    parser = LocalPulmonaryFunctionPdfParser()
    pdf_paths = sorted((output / "sources").rglob("*.pdf"))
    assert len(pdf_paths) == 18
    for pdf_path in pdf_paths:
        expected = construction[pdf_path.stem]
        extracted = parser.extract(pdf_path)
        expected_values = {
            field["field_code"]: field["value"] for field in expected["fields"]
        }
        assert {candidate.field_code: candidate.proposed_value for candidate in extracted.candidates} == (
            expected_values
        )


def test_corpus_rejects_changed_or_incomplete_allocation(tmp_path: Path) -> None:
    allocation = json.loads(ALLOCATION.read_text(encoding="utf-8"))
    allocation["reports"][0]["target_field_count"] = 7
    invalid_path = tmp_path / "invalid-allocation.json"
    invalid_path.write_text(json.dumps(allocation), encoding="utf-8")

    completed = _run(tmp_path / "output", allocation=invalid_path)

    assert completed.returncode == 2
    assert json.loads(completed.stderr)["code"] == "benchmark_v1_corpus_allocation_invalid"
