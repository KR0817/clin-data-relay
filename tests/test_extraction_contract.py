from __future__ import annotations

from decimal import Decimal

from app.extraction_contract import EvidenceSpan, build_extraction_evidence, extraction_idempotency_key
from app.ocr_evaluation import evaluate_predictions


def test_extraction_key_is_stable_but_scoped_to_source_file() -> None:
    arguments = {
        "source_sha256": "a" * 64,
        "dictionary_id": "clinical-crf",
        "dictionary_version": "release-1",
        "selected_fields": ["ALT", "AST"],
        "engine": "local_ocr",
        "engine_version": "tesseract-test",
    }
    first = extraction_idempotency_key(source_file_id="source-1", **arguments)
    repeated = extraction_idempotency_key(source_file_id="source-1", **arguments)
    other_upload = extraction_idempotency_key(source_file_id="source-2", **arguments)
    assert first == repeated
    assert first != other_upload


def test_evidence_is_bounded_and_contains_no_binary_payload() -> None:
    _, evidence = build_extraction_evidence(
        source_file_id="source-1",
        source_sha256="a" * 64,
        dictionary_id="clinical-crf",
        dictionary_version="release-1",
        selected_fields=["ALT"],
        engine="local_ocr",
        engine_version="test",
        duration_ms=4,
        spans=(EvidenceSpan("ALT", None, "  ALT: 31\x00 U/L  "),),
    )
    assert evidence["contract_version"] == "extraction-evidence-v1"
    assert evidence["spans"] == [{"field_code": "ALT", "page_number": None, "text": "ALT: 31 U/L"}]
    assert "image_bytes" not in evidence


def test_synthetic_gold_metrics_separate_exact_and_numeric_tolerance() -> None:
    metrics = evaluate_predictions(
        {"FEV1": {"value": "2.45", "unit": "L"}, "FVC": {"value": "3.20", "unit": "L"}},
        {"FEV1": {"value": "2.450", "unit": "L"}, "FVC": {"value": "3.3", "unit": "L"}},
        numeric_tolerance=Decimal("0.01"),
    )
    assert metrics["field_count"] == 2
    assert metrics["exact_match_count"] == 0
    assert metrics["numeric_tolerance_match_count"] == 1
    assert metrics["missing_count"] == 0
