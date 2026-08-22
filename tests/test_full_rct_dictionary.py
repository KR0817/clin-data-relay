import json
from pathlib import Path


def test_full_rct_dictionary_covers_every_source_header_without_direct_identifiers() -> None:
    payload = json.loads(Path("config/rct-full-field-dictionary.v0.2.json").read_text(encoding="utf-8"))
    columns = payload["columns"]

    assert payload["source"]["source_column_count"] == 164
    assert len(columns) == 164
    assert [column["column"] for column in columns] == list(range(1, 165))
    assert [column["column"] for column in columns if column["target_kind"] == "study_subject_label"] == [1]
    assert [column["column"] for column in columns if not column["uploadable"]] == [3, 4]

    crf_items = [column for column in columns if column["target_kind"] == "crf_item"]
    assert len(crf_items) == 161
    assert len({(column["event_ref"], column["field_code"]) for column in crf_items}) == 161
    assert {column["event_ref"] for column in crf_items} == {"WEEK_0", "WEEK_4", "WEEK_8", "WEEK_12"}
    assert {(column["event_ref"], column["field_code"]) for column in crf_items} >= {
        ("WEEK_0", "ALT"),
        ("WEEK_12", "ALT"),
        ("WEEK_4", "MEDICATION_ADHERENCE"),
        ("WEEK_8", "ADVERSE_REACTION_FLAG"),
        ("WEEK_12", "SF36_VITALITY_DUP_C163"),
    }


def test_local_candidate_allowlist_matches_the_full_dictionary() -> None:
    dictionary = json.loads(Path("config/rct-full-field-dictionary.v0.2.json").read_text(encoding="utf-8"))
    mapping = json.loads(Path("config/synthetic_lab_mapping.v0.1.json").read_text(encoding="utf-8"))

    expected = {
        event_ref: [
            column["field_code"]
            for column in dictionary["columns"]
            if column.get("event_ref") == event_ref and column["target_kind"] == "crf_item"
        ]
        for event_ref in ("WEEK_0", "WEEK_4", "WEEK_8", "WEEK_12")
    }
    assert {event_ref: definition["allowed_field_codes"] for event_ref, definition in mapping["events"].items()} == expected
