from __future__ import annotations

import pytest

import app.pdf_safety as pdf_safety
from app.pdf_safety import PdfSafetyError, validate_pdf_structure


def test_minimal_pdf_container_passes_preflight() -> None:
    validate_pdf_structure(b"%PDF-1.7\n%%EOF")


def test_missing_eof_marker_is_rejected() -> None:
    with pytest.raises(PdfSafetyError, match="pdf_eof_marker_required"):
        validate_pdf_structure(b"%PDF-1.7\n")


def test_object_count_limit_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf_safety, "MAX_PDF_OBJECTS", 1)
    content = b"%PDF-1.7\n1 0 obj\nendobj\n2 0 obj\nendobj\n%%EOF"

    with pytest.raises(PdfSafetyError, match="pdf_structure_too_complex"):
        validate_pdf_structure(content)


def test_dictionary_depth_limit_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf_safety, "MAX_PDF_DICTIONARY_DEPTH", 1)

    with pytest.raises(PdfSafetyError, match="pdf_structure_too_complex"):
        validate_pdf_structure(b"%PDF-1.7\n<<<<>>>>\n%%EOF")
