from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.pulmonary_function import (
    PulmonaryFunctionExtractionFailed,
    load_pulmonary_function_dictionary,
    parse_pulmonary_function_text,
)
from app.crf_mapping import SyntheticLabMapping


SYNTHETIC_REPORT_TEXT = """
预计值 实测值 实/预
VT 0.43 0.92 215.2
BF 20.00 21.88 109.4
MV 8.57 20.17 235.4
VC MAX 4.11 3.92 95.3
IC 3.02 2.00 66.2
FVC 3.96 3.20 80.7
FEV 1 3.09 2.45 79.2
PEF 8.02 5.03 62.8
MEF 75 7.12 3.67 51.5
MEF 50 4.22 1.73 41.1
MEF 25 1.51 0.35 23.3
VBEex 0.06
MVV 116.27 51.69 44.5
TLC-SB 6.74 6.53 96.9
RV-SB 2.44 2.89 118.2
DLCOSB 8.97 3.61 40.3
KCO 1.33 0.56 42.4
"""


def test_supplied_workbook_dictionary_registers_all_headers_and_excludes_identifiers() -> None:
    payload = json.loads(
        Path("config/pulmonary-function-field-dictionary.v1.json").read_text(encoding="utf-8")
    )

    headers = [item["source_header"] for item in payload["identifier_headers"] + payload["fields"]]
    assert payload["source"]["header_count"] == 21
    assert headers == [
        "姓名", "住院号", "测试号", "FEV1", "FVC", "FEV1实/预", "VT", "BF", "MV", "VC MAX",
        "IC", "REF", "MEF 75", "MEF 50", "MEF 25", "VBEex", "MVV", "TLC-SB", "RV-SB",
        "DLCOSB", "KCO",
    ]
    assert all(item["uploadable"] is False for item in payload["identifier_headers"])
    assert len(payload["fields"]) == 18


def test_parser_selects_measured_values_and_fev1_measured_predicted_percent() -> None:
    extraction = parse_pulmonary_function_text(
        SYNTHETIC_REPORT_TEXT,
        load_pulmonary_function_dictionary(),
    )
    values = {candidate.field_code: candidate.proposed_value for candidate in extraction.candidates}

    assert len(values) == 18
    assert values["PFT_FEV1"] == "2.45"
    assert values["PFT_FVC"] == "3.20"
    assert values["PFT_FEV1_MEASURED_PREDICTED_PERCENT"] == "79.2"
    assert values["PFT_PEF"] == "5.03"
    assert values["PFT_VBEEX"] == "0.06"
    assert values["PFT_DLCOSB"] == "3.61"
    assert all("姓名" not in candidate.evidence_text for candidate in extraction.candidates)


def test_parser_fails_closed_when_no_supported_rows_are_present() -> None:
    with pytest.raises(PulmonaryFunctionExtractionFailed, match="pulmonary_report_values_not_found"):
        parse_pulmonary_function_text("unrelated report", load_pulmonary_function_dictionary())


def test_pulmonary_fields_are_available_for_each_supported_visit() -> None:
    mapping = SyntheticLabMapping.from_default_file()

    for event_ref in ("WEEK_0", "WEEK_4", "WEEK_8", "WEEK_12"):
        assert {
            "PFT_FEV1",
            "PFT_FVC",
            "PFT_FEV1_MEASURED_PREDICTED_PERCENT",
            "PFT_DLCOSB",
            "PFT_KCO",
        } <= mapping.allowed_fields_by_event[event_ref]
        assert mapping.field_dictionary_for_event(event_ref)["PFT_PEF"] == "REF"
