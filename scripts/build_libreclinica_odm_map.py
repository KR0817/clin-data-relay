"""Build the synthetic LibreClinica ODM map from installed, read-only metadata."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DICTIONARY_PATH = PROJECT_ROOT / "config" / "rct-full-field-dictionary.v0.2.json"
OUTPUT_PATH = PROJECT_ROOT / "config" / "libreclinica-sandbox-odm-map.json"
CONTAINER = "libreclinica-synthetic-sandbox-db-1"
EVENT_NAMES = {
    "WEEK_0": "Synthetic week 0 full validation",
    "WEEK_4": "Synthetic week 4 validation",
    "WEEK_8": "Synthetic week 8 validation",
    "WEEK_12": "Synthetic week 12 validation",
}


def psql_rows(query: str) -> list[list[str]]:
    completed = subprocess.run(
        [
            "docker",
            "exec",
            CONTAINER,
            "psql",
            "-U",
            "clinica",
            "-d",
            "libreclinica",
            "-A",
            "-t",
            "-F",
            "\t",
            "-c",
            query,
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line.split("\t") for line in completed.stdout.splitlines() if line.strip()]


def main() -> None:
    dictionary = json.loads(DICTIONARY_PATH.read_text(encoding="utf-8"))
    study_rows = psql_rows(
        "SELECT unique_identifier,oc_oid FROM study WHERE study_id=3;"
    )
    if len(study_rows) != 1:
        raise RuntimeError("synthetic_study_not_found")

    event_rows = psql_rows(
        "SELECT name,oc_oid FROM study_event_definition WHERE study_id=3;"
    )
    event_oid_by_name = dict(event_rows)
    events = {}
    for event_ref, event_name in EVENT_NAMES.items():
        event_oid = event_oid_by_name.get(event_name)
        if not event_oid:
            raise RuntimeError(f"event_not_installed:{event_ref}:{event_name}")
        events[event_ref] = {"event_oid": event_oid, "repeat_key": "1"}

    item_rows = psql_rows(
        """
        SELECT c.name,cv.oc_oid,i.name,ig.oc_oid,i.oc_oid
        FROM crf c
        JOIN crf_version cv USING(crf_id)
        JOIN item_form_metadata ifm USING(crf_version_id)
        JOIN item i USING(item_id)
        JOIN item_group_metadata igm
          ON igm.item_id=i.item_id AND igm.crf_version_id=cv.crf_version_id
        JOIN item_group ig USING(item_group_id)
        WHERE c.name LIKE 'RCT_FULL_%_SYNTHETIC'
        ORDER BY c.name,i.name;
        """
    )
    installed_items = {
        (crf_name, item_name): {
            "form_oid": form_oid,
            "item_group_oid": group_oid,
            "item_oid": item_oid,
        }
        for crf_name, form_oid, item_name, group_oid, item_oid in item_rows
    }

    field_mappings: dict[str, dict[str, dict[str, str]]] = {event_ref: {} for event_ref in events}
    mapped_source_columns = 0
    for column in dictionary["columns"]:
        if column["target_kind"] != "crf_item":
            continue
        key = (column["crf_name"], column["item_name"])
        installed = installed_items.get(key)
        if installed is None:
            raise RuntimeError(f"item_not_installed:{key[0]}:{key[1]}")
        event_fields = field_mappings[column["event_ref"]]
        if column["field_code"] in event_fields:
            raise RuntimeError(f"duplicate_event_field:{column['event_ref']}:{column['field_code']}")
        event_fields[column["field_code"]] = installed
        mapped_source_columns += 1

    if mapped_source_columns != dictionary["counts"]["crf_item_columns"]:
        raise RuntimeError("mapped_source_column_count_mismatch")
    if len(installed_items) != mapped_source_columns:
        raise RuntimeError("installed_item_count_mismatch")

    mapping = {
        "mapping_id": "libreclinica-synthetic-rct-full-odm-map",
        "mapping_version": "v0.2-installed-2026-08-10",
        "data_boundary": "synthetic_only",
        "study_identifier": study_rows[0][0],
        "study_oid": study_rows[0][1],
        "source_dictionary_id": dictionary["dictionary_id"],
        "source_dictionary_version": dictionary["dictionary_version"],
        "events": events,
        "field_mappings": field_mappings,
    }
    OUTPUT_PATH.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(OUTPUT_PATH),
                "events": len(events),
                "field_mappings": sum(len(fields) for fields in field_mappings.values()),
            }
        )
    )


if __name__ == "__main__":
    main()
