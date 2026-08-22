"""Local PDF page classification without OCR or network calls."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PdfPageInspection:
    page_number: int
    width: float
    height: float
    text_char_count: int


@dataclass(frozen=True)
class PdfInspection:
    classification: str
    pages: tuple[PdfPageInspection, ...]
    warnings: tuple[str, ...]


def inspect_pdf(pdf_path: Path, *, max_pages: int = 5) -> PdfInspection:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path), strict=False)
        if reader.is_encrypted:
            return PdfInspection("pdf_invalid", (), ("pdf_encrypted",))
        if not reader.pages or len(reader.pages) > max_pages:
            return PdfInspection("pdf_invalid", (), ("pulmonary_pdf_page_limit",))
        pages: list[PdfPageInspection] = []
        for index, page in enumerate(reader.pages, start=1):
            box = page.mediabox
            text = page.extract_text() or ""
            pages.append(
                PdfPageInspection(
                    page_number=index,
                    width=round(float(box.width), 2),
                    height=round(float(box.height), 2),
                    text_char_count=len("".join(text.split())),
                )
            )
    except Exception:
        return PdfInspection("pdf_invalid", (), ("pdf_parse_failed",))
    classification = "pdf_text_layer" if all(page.text_char_count >= 20 for page in pages) else "pdf_scanned_pages"
    warnings = ("pdf_scanned_pages",) if classification == "pdf_scanned_pages" else ()
    return PdfInspection(classification, tuple(pages), warnings)
