"""Strict parser for synthetic structured laboratory CSV imports."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass


MAX_STRUCTURED_CSV_BYTES = 5 * 1024 * 1024
MAX_STRUCTURED_CSV_ROWS = 5_000
REQUIRED_HEADERS = frozenset({"subject_ref", "event_ref", "field_code", "value"})
ALLOWED_HEADERS = REQUIRED_HEADERS | {"unit"}


class StructuredImportError(ValueError):
    """Raised when a structured import cannot be accepted as one transaction."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class StructuredImportRow:
    row_number: int
    subject_ref: str
    event_ref: str
    field_code: str
    value: str
    unit: str | None


@dataclass(frozen=True)
class StructuredImportResult:
    rows: tuple[StructuredImportRow, ...]
    ignored_headers: tuple[str, ...]


def parse_structured_csv(content: bytes) -> StructuredImportResult:
    """Parse a bounded UTF-8 CSV and fail before any database write."""

    if not content:
        raise StructuredImportError("structured_import_empty_file")
    if len(content) > MAX_STRUCTURED_CSV_BYTES:
        raise StructuredImportError("structured_import_file_too_large")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise StructuredImportError("structured_import_utf8_required") from error

    reader = csv.DictReader(io.StringIO(text, newline=""))
    headers = [str(header or "").strip() for header in (reader.fieldnames or [])]
    if (
        not REQUIRED_HEADERS.issubset(headers)
        or len(headers) != len(set(headers))
    ):
        raise StructuredImportError("structured_import_invalid_schema")
    ignored_headers = tuple(header for header in headers if header not in ALLOWED_HEADERS)

    parsed: list[StructuredImportRow] = []
    for row_number, raw in enumerate(reader, start=2):
        if row_number > MAX_STRUCTURED_CSV_ROWS + 1:
            raise StructuredImportError("structured_import_too_many_rows")
        subject_ref = str(raw.get("subject_ref") or "").strip().upper()
        event_ref = str(raw.get("event_ref") or "").strip().upper()
        field_code = str(raw.get("field_code") or "").strip().upper()
        value = str(raw.get("value") or "").strip()
        unit = str(raw.get("unit") or "").strip() or None
        if not all((subject_ref, event_ref, field_code, value)):
            raise StructuredImportError("structured_import_blank_required_value")
        if len(value) > 200 or (unit is not None and len(unit) > 50):
            raise StructuredImportError("structured_import_value_too_long")
        parsed.append(
            StructuredImportRow(
                row_number=row_number,
                subject_ref=subject_ref,
                event_ref=event_ref,
                field_code=field_code,
                value=value,
                unit=unit,
            )
        )
    if not parsed:
        raise StructuredImportError("structured_import_no_rows")
    return StructuredImportResult(rows=tuple(parsed), ignored_headers=ignored_headers)
