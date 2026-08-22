"""Engine-neutral, bounded evidence records for local extraction runs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Iterable, Mapping


CONTRACT_VERSION = "extraction-evidence-v1"
PREPROCESSING_VERSION = "local-normalize-v1"
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True)
class EvidenceSpan:
    field_code: str
    page_number: int | None
    text: str
    bbox: tuple[float, float, float, float] | None = None


def _bounded_text(value: object, limit: int = 500) -> str:
    text = _CONTROL_RE.sub(" ", str(value or ""))
    return " ".join(text.split())[:limit]


def extraction_idempotency_key(
    *,
    source_file_id: str | None = None,
    source_sha256: str,
    derivative_sha256: str | None = None,
    dictionary_id: str,
    dictionary_version: str,
    selected_fields: Iterable[str],
    engine: str,
    engine_version: str,
    model_ids: Iterable[str] = (),
    preprocessing_version: str = PREPROCESSING_VERSION,
) -> str:
    payload = {
        "source_file_id": source_file_id,
        "source_sha256": source_sha256,
        "derivative_sha256": derivative_sha256 or source_sha256,
        "dictionary_id": dictionary_id,
        "dictionary_version": dictionary_version,
        "selected_fields": sorted({str(field).upper() for field in selected_fields}),
        "engine": engine,
        "engine_version": engine_version,
        "model_ids": sorted({str(model) for model in model_ids if str(model)}),
        "preprocessing_version": preprocessing_version,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_extraction_evidence(
    *,
    source_file_id: str | None = None,
    source_sha256: str,
    derivative_sha256: str | None = None,
    dictionary_id: str,
    dictionary_version: str,
    selected_fields: Iterable[str],
    engine: str,
    engine_version: str,
    model_ids: Iterable[str] = (),
    duration_ms: int,
    page_dimensions: Iterable[Mapping[str, object]] = (),
    spans: Iterable[EvidenceSpan] = (),
    warnings: Iterable[str] = (),
    preprocessing_version: str = PREPROCESSING_VERSION,
) -> tuple[str, dict[str, object]]:
    model_list = sorted({str(model) for model in model_ids if str(model)})
    selected_field_list = sorted({str(field).upper() for field in selected_fields})
    key = extraction_idempotency_key(
        source_file_id=source_file_id,
        source_sha256=source_sha256,
        derivative_sha256=derivative_sha256,
        dictionary_id=dictionary_id,
        dictionary_version=dictionary_version,
        selected_fields=selected_field_list,
        engine=engine,
        engine_version=engine_version,
        model_ids=model_list,
        preprocessing_version=preprocessing_version,
    )
    evidence = {
        "contract_version": CONTRACT_VERSION,
        "engine": engine,
        "engine_version": engine_version,
        "model_ids": model_list,
        "source_sha256": source_sha256,
        "derivative_sha256": derivative_sha256 or source_sha256,
        "dictionary_id": dictionary_id,
        "dictionary_version": dictionary_version,
        "preprocessing_version": preprocessing_version,
        "selected_fields": selected_field_list,
        "duration_ms": max(0, int(duration_ms)),
        "page_dimensions": [
            {
                "page_number": int(page.get("page_number", 0)),
                "width": float(page.get("width", 0) or 0),
                "height": float(page.get("height", 0) or 0),
                "text_char_count": int(page.get("text_char_count", 0) or 0),
            }
            for page in page_dimensions
        ],
        "spans": [
            {
                "field_code": span.field_code,
                "page_number": span.page_number,
                "text": _bounded_text(span.text),
                **({"bbox": list(span.bbox)} if span.bbox is not None else {}),
            }
            for span in spans
        ],
        "warnings": sorted({_bounded_text(warning, 120) for warning in warnings if str(warning).strip()}),
    }
    return key, evidence


def canonical_evidence_json(evidence: Mapping[str, object]) -> str:
    return json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_evidence(value: str | None) -> dict[str, object] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None
