"""Cheap PDF structure limits applied before the full text parser."""

from __future__ import annotations

import re


MAX_PDF_OBJECTS = 20_000
MAX_PDF_DICTIONARY_DEPTH = 64
_OBJECT_RE = re.compile(rb"(?m)^\s*\d+\s+\d+\s+obj\b")
_DICTIONARY_TOKEN_RE = re.compile(rb"<<|>>")


class PdfSafetyError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def validate_pdf_structure(content: bytes) -> None:
    """Reject obviously malformed or pathologically nested PDF containers."""

    if not content.startswith(b"%PDF-"):
        raise PdfSafetyError("pulmonary_pdf_required")
    if b"%%EOF" not in content[-4096:]:
        raise PdfSafetyError("pdf_eof_marker_required")
    if len(_OBJECT_RE.findall(content)) > MAX_PDF_OBJECTS:
        raise PdfSafetyError("pdf_structure_too_complex")
    depth = 0
    for token in _DICTIONARY_TOKEN_RE.findall(content):
        if token == b"<<":
            depth += 1
            if depth > MAX_PDF_DICTIONARY_DEPTH:
                raise PdfSafetyError("pdf_structure_too_complex")
        else:
            depth = max(0, depth - 1)
