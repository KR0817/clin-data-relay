"""Local-only extraction of pulmonary-function values from text-layer PDFs."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class PulmonaryFunctionExtractionFailed(RuntimeError):
    """Raised when a PDF cannot be safely parsed into supported pulmonary fields."""


@dataclass(frozen=True)
class PulmonaryFieldDefinition:
    field_code: str
    source_header: str
    report_labels: tuple[str, ...]
    value_selector: str
    unit: str | None


@dataclass(frozen=True)
class PulmonaryFunctionDictionary:
    dictionary_id: str
    dictionary_version: str
    events: tuple[str, ...]
    identifier_headers: tuple[dict[str, object], ...]
    fields: tuple[PulmonaryFieldDefinition, ...]
    raw_fields: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class PulmonaryFunctionCandidate:
    field_code: str
    proposed_value: str
    unit: str | None
    evidence_text: str


@dataclass(frozen=True)
class PulmonaryFunctionExtraction:
    candidates: tuple[PulmonaryFunctionCandidate, ...]
    engine_version: str


NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])[-+]?(?:\d+(?:[.,]\d+)?|\.\d+)")


def load_pulmonary_function_dictionary(
    path: Path | None = None,
) -> PulmonaryFunctionDictionary:
    dictionary_path = path or (
        Path(__file__).resolve().parent.parent
        / "config"
        / "pulmonary-function-field-dictionary.v1.json"
    )
    try:
        payload = json.loads(dictionary_path.read_text(encoding="utf-8"))
        if payload["data_boundary"] != "local_candidate_only":
            raise ValueError("unexpected data boundary")
        fields = tuple(
            PulmonaryFieldDefinition(
                field_code=str(item["field_code"]).upper(),
                source_header=str(item["source_header"]),
                report_labels=tuple(str(label) for label in item["report_labels"]),
                value_selector=str(item["value_selector"]),
                unit=str(item["unit"]) if item.get("unit") else None,
            )
            for item in payload["fields"]
        )
        identifier_headers = tuple(dict(item) for item in payload["identifier_headers"])
        events = tuple(str(event_ref) for event_ref in payload["events"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise PulmonaryFunctionExtractionFailed(
            "pulmonary_function_dictionary_unavailable"
        ) from error
    if len(identifier_headers) != 3 or len(fields) != 18 or len({field.field_code for field in fields}) != 18:
        raise PulmonaryFunctionExtractionFailed("pulmonary_function_dictionary_unavailable")
    if any(field.value_selector not in {"single", "measured", "measured_predicted_percent"} for field in fields):
        raise PulmonaryFunctionExtractionFailed("pulmonary_function_dictionary_unavailable")
    return PulmonaryFunctionDictionary(
        dictionary_id=str(payload["dictionary_id"]),
        dictionary_version=str(payload["dictionary_version"]),
        events=events,
        identifier_headers=identifier_headers,
        fields=fields,
        raw_fields=tuple(dict(item) for item in payload["fields"]),
    )


def _normalise_line(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def _label_pattern(label: str) -> re.Pattern[str]:
    normalized = _normalise_line(label)
    parts = [re.escape(part) for part in normalized.split(" ")]
    flexible_label = r"\s*".join(parts)
    return re.compile(rf"^{flexible_label}(?=\s|[-+]?\d|$)", re.IGNORECASE)


def _select_value(values: list[str], selector: str) -> str | None:
    index = {
        "single": 0,
        "measured": 1,
        "measured_predicted_percent": 2,
    }[selector]
    if index >= len(values):
        return None
    return values[index].replace(",", ".")


def parse_pulmonary_function_text(
    text: str,
    dictionary: PulmonaryFunctionDictionary,
) -> PulmonaryFunctionExtraction:
    """Parse only anchored result rows and return no demographic or report identifiers."""
    lines = tuple(line for raw_line in text.splitlines() if (line := _normalise_line(raw_line)))
    candidates: list[PulmonaryFunctionCandidate] = []
    for field in dictionary.fields:
        selected_value: str | None = None
        matched_label: str | None = None
        for line in lines:
            for label in field.report_labels:
                match = _label_pattern(label).match(line)
                if match is None:
                    continue
                values = NUMBER_RE.findall(line[match.end() :])
                selected_value = _select_value(values, field.value_selector)
                if selected_value is not None:
                    matched_label = label
                    break
            if selected_value is not None:
                break
        if selected_value is None or matched_label is None:
            continue
        candidates.append(
            PulmonaryFunctionCandidate(
                field_code=field.field_code,
                proposed_value=selected_value,
                unit=field.unit,
                evidence_text=(
                    f"PDF pulmonary row={matched_label}; selected_column={field.value_selector}"
                ),
            )
        )
    if not candidates:
        raise PulmonaryFunctionExtractionFailed("pulmonary_report_values_not_found")
    return PulmonaryFunctionExtraction(
        candidates=tuple(candidates),
        engine_version="pulmonary-text-parser-v1",
    )


class LocalPulmonaryFunctionPdfParser:
    """Reads a local PDF text layer and never invokes a network service."""

    def __init__(
        self,
        dictionary: PulmonaryFunctionDictionary | None = None,
        *,
        max_pages: int = 5,
    ) -> None:
        self.dictionary = dictionary or load_pulmonary_function_dictionary()
        self.max_pages = max_pages

    def extract(self, pdf_path: Path) -> PulmonaryFunctionExtraction:
        if not pdf_path.is_file():
            raise PulmonaryFunctionExtractionFailed("synthetic_upload_not_found")
        try:
            from pypdf import PdfReader, __version__ as pypdf_version

            reader = PdfReader(str(pdf_path), strict=False)
            if reader.is_encrypted:
                raise PulmonaryFunctionExtractionFailed("pdf_encrypted")
            if not reader.pages or len(reader.pages) > self.max_pages:
                raise PulmonaryFunctionExtractionFailed("pulmonary_pdf_page_limit")
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except PulmonaryFunctionExtractionFailed:
            raise
        except Exception as error:
            raise PulmonaryFunctionExtractionFailed("pulmonary_pdf_parse_failed") from error
        if len(re.sub(r"\s+", "", text)) < 40:
            raise PulmonaryFunctionExtractionFailed("pdf_text_layer_required")
        extraction = parse_pulmonary_function_text(text, self.dictionary)
        return PulmonaryFunctionExtraction(
            candidates=extraction.candidates,
            engine_version=f"pypdf-{pypdf_version};pulmonary-text-parser-v1",
        )


def pulmonary_dictionary_columns(
    dictionary: PulmonaryFunctionDictionary,
) -> tuple[dict[str, object], ...]:
    """Project workbook headers into visit-specific candidate dictionary rows."""
    columns: list[dict[str, object]] = []
    for item in dictionary.identifier_headers:
        columns.append(
            {
                **item,
                "source_group": "肺功能.xlsx",
                "source_dataset": dictionary.dictionary_id,
            }
        )
    for event_ref in dictionary.events:
        for item in dictionary.raw_fields:
            columns.append(
                {
                    "column": item["column"],
                    "source_group": "肺功能.xlsx",
                    "source_dataset": dictionary.dictionary_id,
                    "source_header": item["source_header"],
                    "target_kind": "candidate_field",
                    "uploadable": True,
                    "event_ref": event_ref,
                    "field_code": str(item["field_code"]).upper(),
                    "data_type": item["data_type"],
                    "authority_transfer": "pending_crf_installation",
                }
            )
    return tuple(columns)
