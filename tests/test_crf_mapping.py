from app.crf_mapping import SyntheticLabMapping


def test_crf_mapping_exposes_only_uploadable_excel_headers_for_kimi_prompt() -> None:
    mapping = SyntheticLabMapping.from_default_file()

    fields = mapping.field_dictionary_for_event("WEEK_0")

    assert fields["DRUG_CLASS"] == "药物类别（1-中药，2-西药）"
    assert fields["ALT"] == "ALT"
    assert set(fields) == set(mapping.allowed_fields_by_event["WEEK_0"])
    assert "姓名" not in fields.values()
    assert "缩写" not in fields.values()
