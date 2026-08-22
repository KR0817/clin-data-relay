from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import pytest

from app.edc_adapter import (
    EdcAdapterError,
    LibreClinicaOdmMapping,
    LibreClinicaSoapAdapter,
)


def soap_response(body: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">'
        f"<soapenv:Body>{body}</soapenv:Body></soapenv:Envelope>"
    ).encode()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


@pytest.fixture()
def odm_mapping() -> LibreClinicaOdmMapping:
    return LibreClinicaOdmMapping.from_file(Path("config/libreclinica-sandbox-odm-map.json"))


def test_live_adapter_probes_credentials_and_builds_a_mapped_odm_import(
    odm_mapping: LibreClinicaOdmMapping,
) -> None:
    requests: list[tuple[str, bytes]] = []

    def transport(url: str, payload: bytes, timeout: float) -> bytes:
        assert timeout == 3
        requests.append((url, payload))
        root = ET.fromstring(payload)
        body = next(element for element in root.iter() if local_name(element.tag) == "Body")
        operation = local_name(next(iter(body)).tag)
        if operation == "listAllByStudyRequest":
            return soap_response("<listAllByStudyResponse><result>Success</result></listAllByStudyResponse>")
        if operation == "isStudySubjectRequest":
            return soap_response(
                "<isStudySubjectResponse><result>Success</result>"
                "<studySubjectOID>SS_SYNTH_001</studySubjectOID></isStudySubjectResponse>"
            )
        if operation == "importRequest":
            return soap_response(
                "<importDataResponse><result>Success. 1 of 1 forms imported.</result></importDataResponse>"
            )
        raise AssertionError(operation)

    adapter = LibreClinicaSoapAdapter(
        base_url="http://127.0.0.1:8081",
        username="companion_soap",
        password_sha1="a" * 40,
        odm_mapping=odm_mapping,
        timeout_seconds=3,
        transport=transport,
    )

    readiness = adapter.readiness()
    result = adapter.submit(
        {
            "edc_record": {"subject_ref": "SUBJ001", "event_ref": "WEEK_0", "field_code": "ALT"},
            "value": {"final_value": "32<&", "unit": "U/L"},
        },
        idempotency_key="candidate:test",
    )

    assert readiness["status"] == "ready"
    assert readiness["write_path"] == "human_triggered"
    event_mapping = odm_mapping.events["WEEK_0"]
    field_mapping = odm_mapping.fields_by_event["WEEK_0"]["ALT"]
    assert result.external_reference == (
        f"S_SYNTHETI/SS_SYNTH_001/{event_mapping.event_oid}:{event_mapping.repeat_key}/"
        f"{field_mapping.form_oid}/{field_mapping.item_oid}"
    )
    assert len(result.response_sha256) == 64
    assert [url.rsplit("/", 2)[-2:] for url, _ in requests] == [
        ["studySubject", "v1"],
        ["studySubject", "v1"],
        ["data", "v1"],
    ]
    import_root = ET.fromstring(requests[-1][1])
    item = next(element for element in import_root.iter() if local_name(element.tag) == "ItemData")
    assert item.attrib == {
        "ItemOID": field_mapping.item_oid,
        "Value": "32<&",
        "TransactionType": "Insert",
    }


def test_live_adapter_fails_closed_for_unmapped_fields_before_network_write(
    odm_mapping: LibreClinicaOdmMapping,
) -> None:
    adapter = LibreClinicaSoapAdapter(
        base_url="http://localhost:8081",
        username="companion_soap",
        password_sha1="b" * 40,
        odm_mapping=odm_mapping,
        transport=lambda _url, _payload, _timeout: (_ for _ in ()).throw(AssertionError("network called")),
    )

    with pytest.raises(EdcAdapterError) as error:
        adapter.submit(
            {
                "edc_record": {
                    "subject_ref": "SUBJ001",
                    "event_ref": "WEEK_0",
                    "field_code": "NOT_IN_DICTIONARY",
                },
                "value": {"final_value": "2.1", "unit": "mg/L"},
            },
            idempotency_key="candidate:test",
        )

    assert error.value.code == "libreclinica_field_not_mapped"


def test_subject_provisioning_creates_missing_subject_and_schedules_event_idempotently(
    odm_mapping: LibreClinicaOdmMapping,
) -> None:
    operations: list[str] = []
    subject_lookup_count = 0

    def transport(_url: str, payload: bytes, _timeout: float) -> bytes:
        nonlocal subject_lookup_count
        root = ET.fromstring(payload)
        body = next(element for element in root.iter() if local_name(element.tag) == "Body")
        operation = local_name(next(iter(body)).tag)
        operations.append(operation)
        if operation == "isStudySubjectRequest":
            subject_lookup_count += 1
            if subject_lookup_count == 1:
                return soap_response("<isStudySubjectResponse><result>Fail</result></isStudySubjectResponse>")
            return soap_response(
                "<isStudySubjectResponse><result>Success</result>"
                "<studySubjectOID>SS_SYNTH_009</studySubjectOID></isStudySubjectResponse>"
            )
        if operation == "createRequest":
            return soap_response(
                "<createResponse><result>Success</result><label>SUBJ009</label></createResponse>"
            )
        if operation == "listAllByStudyRequest":
            return soap_response(
                "<listAllByStudyResponse><result>Success</result>"
                "<studySubject><label>SUBJ009</label></studySubject></listAllByStudyResponse>"
            )
        if operation == "scheduleRequest":
            return soap_response(
                "<scheduleResponse><result>Success</result><studyEventOrdinal>1</studyEventOrdinal></scheduleResponse>"
            )
        raise AssertionError(operation)

    adapter = LibreClinicaSoapAdapter(
        base_url="http://127.0.0.1:8081",
        username="companion_soap",
        password_sha1="a" * 40,
        odm_mapping=odm_mapping,
        allow_subject_provisioning=True,
        transport=transport,
    )

    result = adapter.provision_subject("SUBJ009", "WEEK_0", enrollment_date=date(2026, 8, 10))

    assert result.subject_oid == "SS_SYNTH_009"
    assert result.subject_created is True
    assert result.event_scheduled is True
    assert operations == [
        "isStudySubjectRequest",
        "createRequest",
        "isStudySubjectRequest",
        "listAllByStudyRequest",
        "scheduleRequest",
    ]


def test_subject_provisioning_is_an_explicit_gate(odm_mapping: LibreClinicaOdmMapping) -> None:
    adapter = LibreClinicaSoapAdapter(
        base_url="http://localhost:8081",
        username="companion_soap",
        password_sha1="b" * 40,
        odm_mapping=odm_mapping,
        transport=lambda _url, _payload, _timeout: (_ for _ in ()).throw(AssertionError("network called")),
    )

    with pytest.raises(EdcAdapterError) as error:
        adapter.provision_subject("SUBJ009", "WEEK_0", enrollment_date=date(2026, 8, 10))

    assert error.value.code == "libreclinica_subject_provisioning_disabled"


def test_remote_target_requires_explicit_approval(odm_mapping: LibreClinicaOdmMapping) -> None:
    with pytest.raises(EdcAdapterError) as error:
        LibreClinicaSoapAdapter(
            base_url="https://edc.example.test",
            username="companion_soap",
            password_sha1="c" * 40,
            odm_mapping=odm_mapping,
        )

    assert error.value.code == "libreclinica_remote_target_blocked"


def test_mtom_single_part_response_is_parsed_without_logging_or_storing_the_boundary() -> None:
    xml = soap_response("<importDataResponse><result>Success. 1 of 1 forms imported.</result></importDataResponse>")
    boundary = b"------=_Part_1_123456"
    multipart = (
        boundary
        + b"\r\nContent-Type: application/xop+xml; charset=utf-8; type=\"text/xml\""
        + b"\r\n\r\n"
        + xml
        + b"\r\n"
        + boundary
        + b"--\r\n"
    )

    root = LibreClinicaSoapAdapter._require_success(multipart, "libreclinica_import_rejected")

    assert any(local_name(element.tag) == "result" for element in root.iter())
