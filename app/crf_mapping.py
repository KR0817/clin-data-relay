"""Fail-closed synthetic CRF mapping for laboratory OCR candidates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.pulmonary_function import (
    load_pulmonary_function_dictionary,
    pulmonary_dictionary_columns,
)


class CrfMappingError(RuntimeError):
    """Raised when the local, versioned mapping is incomplete or invalid."""


@dataclass(frozen=True)
class SyntheticLabMapping:
    mapping_id: str
    mapping_version: str
    allowed_fields_by_event: dict[str, frozenset[str]]
    field_labels_by_event: dict[str, dict[str, str]]
    dictionary_columns: tuple[dict[str, object], ...]

    @classmethod
    def from_default_file(cls) -> "SyntheticLabMapping":
        config_directory = Path(__file__).resolve().parent.parent / "config"
        mapping_path = config_directory / "synthetic_lab_mapping.v0.1.json"
        dictionary_path = config_directory / "rct-full-field-dictionary.v0.2.json"
        try:
            payload = json.loads(mapping_path.read_text(encoding="utf-8"))
            if payload["data_boundary"] != "synthetic_only":
                raise ValueError("unexpected data boundary")
            allowed_field_sets = {
                str(event_ref): {str(field_code).upper() for field_code in definition["allowed_field_codes"]}
                for event_ref, definition in payload["events"].items()
            }
            dictionary = json.loads(dictionary_path.read_text(encoding="utf-8"))
            if (
                dictionary["data_boundary"] != "synthetic_only"
                or dictionary["dictionary_id"] != payload["mapping_id"]
                or dictionary["dictionary_version"] != payload["mapping_version"]
            ):
                raise ValueError("field dictionary does not match CRF mapping")
            pulmonary_dictionary = load_pulmonary_function_dictionary()
            if set(pulmonary_dictionary.events) != set(allowed_field_sets):
                raise ValueError("pulmonary events do not match CRF events")
            for event_ref in pulmonary_dictionary.events:
                allowed_field_sets[event_ref].update(
                    field.field_code for field in pulmonary_dictionary.fields
                )
            allowed_fields_by_event = {
                event_ref: frozenset(field_codes)
                for event_ref, field_codes in allowed_field_sets.items()
            }
            dictionary_columns = (
                tuple(dict(column) for column in dictionary["columns"])
                + pulmonary_dictionary_columns(pulmonary_dictionary)
            )
            field_labels_by_event: dict[str, dict[str, str]] = {
                event_ref: {} for event_ref in allowed_fields_by_event
            }
            for column in dictionary_columns:
                if column.get("target_kind") not in {"crf_item", "candidate_field"} or column.get("uploadable") is not True:
                    continue
                event_ref = str(column["event_ref"])
                field_code = str(column["field_code"]).upper()
                if event_ref in field_labels_by_event and field_code in allowed_fields_by_event[event_ref]:
                    field_labels_by_event[event_ref][field_code] = str(column["source_header"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise CrfMappingError("synthetic_crf_mapping_unavailable") from error
        if not allowed_fields_by_event or any(not fields for fields in allowed_fields_by_event.values()):
            raise CrfMappingError("synthetic_crf_mapping_unavailable")
        if any(
            set(field_labels_by_event[event_ref]) != set(allowed_fields)
            for event_ref, allowed_fields in allowed_fields_by_event.items()
        ):
            raise CrfMappingError("synthetic_crf_mapping_unavailable")
        return cls(
            mapping_id=f"{payload['mapping_id']}+{pulmonary_dictionary.dictionary_id}",
            mapping_version=f"{payload['mapping_version']}+{pulmonary_dictionary.dictionary_version}",
            allowed_fields_by_event=allowed_fields_by_event,
            field_labels_by_event=field_labels_by_event,
            dictionary_columns=dictionary_columns,
        )

    def assert_allowed(self, event_ref: str, field_codes: Iterable[str]) -> None:
        allowed_fields = self.allowed_fields_by_event.get(event_ref)
        if allowed_fields is None or any(field_code.upper() not in allowed_fields for field_code in field_codes):
            raise CrfMappingError("field_not_in_crf_mapping")

    def field_dictionary_for_event(self, event_ref: str) -> dict[str, str]:
        field_dictionary = self.field_labels_by_event.get(event_ref)
        if field_dictionary is None:
            raise CrfMappingError("event_not_in_crf_mapping")
        return dict(field_dictionary)

    def all_dictionary_columns(self) -> list[dict[str, object]]:
        return [dict(column) for column in self.dictionary_columns]
