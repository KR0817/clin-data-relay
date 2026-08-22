from __future__ import annotations

import json

import pytest

from app.offline_package import (
    OfflinePackageError,
    build_encrypted_reviewed_package,
    build_reviewed_package,
    parse_encrypted_reviewed_package,
    parse_reviewed_package,
)


def _package() -> bytes:
    content, _package_id, _digest = build_reviewed_package(
        centre_code="SITE_A",
        dictionary_id="synthetic-lab",
        dictionary_version="2026.08",
        created_by="site-a-investigator@example.test",
        created_at="2026-08-14T00:00:00+00:00",
        records=[
            {
                "centre_code": "SITE_A",
                "edc_subject_ref": "SUBJ001",
                "edc_event_ref": "WEEK_0",
                "field_code": "ALT",
                "final_value": "31",
                "unit": "U/L",
                "source_sha256": "a" * 64,
                "reviewed_at": "2026-08-14T00:00:00+00:00",
            }
        ],
    )
    return content


def test_reviewed_package_is_canonical_and_hash_verified() -> None:
    content = _package()

    parsed = parse_reviewed_package(content)

    assert parsed["package_type"] == "clinical-edc-reviewed-package"
    assert parsed["record_count"] == 1
    assert parsed["records"][0]["field_code"] == "ALT"
    assert content.endswith(b"\n")


def test_reviewed_package_rejects_tampering() -> None:
    document = json.loads(_package().decode("utf-8"))
    document["records"][0]["final_value"] = "999"

    with pytest.raises(OfflinePackageError, match="offline_package_hash_mismatch"):
        parse_reviewed_package(json.dumps(document).encode("utf-8"))


def test_encrypted_reviewed_package_hides_values_and_round_trips() -> None:
    encrypted, package_id, package_sha256 = build_encrypted_reviewed_package(
        passphrase="centre-passphrase-2026",
        centre_code="SITE_A",
        dictionary_id="synthetic-lab",
        dictionary_version="2026.08",
        created_by="site-a-investigator@example.test",
        created_at="2026-08-14T00:00:00+00:00",
        records=[
            {
                "centre_code": "SITE_A",
                "edc_subject_ref": "SUBJ001",
                "edc_event_ref": "WEEK_0",
                "field_code": "ALT",
                "final_value": "31",
                "unit": "U/L",
                "source_sha256": "a" * 64,
                "reviewed_at": "2026-08-14T00:00:00+00:00",
            }
        ],
    )

    # The transport envelope contains random salt/nonce and hashes, so an
    # incidental byte sequence such as ``31`` can appear by chance. Assert
    # that the plaintext JSON field/value pair is absent instead.
    assert b'"final_value":"31"' not in encrypted
    assert b'"unit":"U/L"' not in encrypted
    parsed, parsed_sha256 = parse_encrypted_reviewed_package(
        encrypted,
        passphrase="centre-passphrase-2026",
    )

    assert parsed["package_id"] == package_id
    assert parsed_sha256 == package_sha256
    assert parsed["records"][0]["final_value"] == "31"


def test_audit_anchor_is_authenticated_inside_and_outside_the_encrypted_package() -> None:
    anchor = {
        "version": "audit-chain-v1",
        "head_hash": "c" * 64,
        "event_count": 12,
        "generated_at": "2026-08-17T00:00:00+00:00",
    }
    encrypted, _package_id, _package_sha256 = build_encrypted_reviewed_package(
        passphrase="centre-passphrase-2026",
        centre_code="SITE_A",
        dictionary_id="synthetic-lab",
        dictionary_version="2026.08",
        created_by="site-a-investigator@example.test",
        created_at="2026-08-17T00:00:00+00:00",
        records=[],
        audit_anchor=anchor,
    )

    envelope = json.loads(encrypted.decode("utf-8"))
    parsed, _transport_hash = parse_encrypted_reviewed_package(
        encrypted,
        passphrase="centre-passphrase-2026",
    )

    assert envelope["audit_anchor"] == anchor
    assert parsed["audit_anchor"] == anchor


def test_tampering_with_the_encrypted_audit_anchor_is_rejected() -> None:
    encrypted, _package_id, _package_sha256 = build_encrypted_reviewed_package(
        passphrase="centre-passphrase-2026",
        centre_code="SITE_A",
        dictionary_id="synthetic-lab",
        dictionary_version="2026.08",
        created_by="site-a-investigator@example.test",
        created_at="2026-08-17T00:00:00+00:00",
        records=[],
        audit_anchor={
            "version": "audit-chain-v1",
            "head_hash": "c" * 64,
            "event_count": 12,
            "generated_at": "2026-08-17T00:00:00+00:00",
        },
    )
    envelope = json.loads(encrypted.decode("utf-8"))
    envelope["audit_anchor"]["event_count"] = 13

    with pytest.raises(OfflinePackageError, match="offline_package_hash_mismatch"):
        parse_encrypted_reviewed_package(
            json.dumps(envelope).encode("utf-8"),
            passphrase="centre-passphrase-2026",
        )


def test_encrypted_reviewed_package_rejects_wrong_passphrase() -> None:
    encrypted, _package_id, _package_sha256 = build_encrypted_reviewed_package(
        passphrase="centre-passphrase-2026",
        centre_code="SITE_A",
        dictionary_id="synthetic-lab",
        dictionary_version="2026.08",
        created_by="site-a-investigator@example.test",
        created_at="2026-08-14T00:00:00+00:00",
        records=[],
    )

    with pytest.raises(OfflinePackageError, match="offline_package_decryption_failed"):
        parse_encrypted_reviewed_package(encrypted, passphrase="wrong-passphrase")


def test_package_builder_rejects_direct_identifier_in_a_confirmed_value() -> None:
    with pytest.raises(OfflinePackageError, match="offline_package_direct_identifier_detected"):
        build_encrypted_reviewed_package(
            passphrase="centre-passphrase-2026",
            centre_code="SITE_A",
            dictionary_id="synthetic-lab",
            dictionary_version="2026.08",
            created_by="site-a-investigator@example.test",
            created_at="2026-08-14T00:00:00+00:00",
            records=[
                {
                    "centre_code": "SITE_A",
                    "edc_subject_ref": "SUBJ001",
                    "edc_event_ref": "WEEK_0",
                    "field_code": "ALT",
                    "final_value": "patient name: Zhang",
                    "unit": None,
                    "source_sha256": "a" * 64,
                    "reviewed_at": "2026-08-14T00:00:00+00:00",
                }
            ],
        )


def test_package_builder_collapses_identical_historical_duplicates() -> None:
    record = {
        "centre_code": "SITE_A",
        "edc_subject_ref": "SUBJ001",
        "edc_event_ref": "WEEK_0",
        "field_code": "ALT",
        "final_value": "31",
        "unit": "U/L",
        "source_sha256": "a" * 64,
        "reviewed_at": "2026-08-14T00:00:00+00:00",
    }

    content, _package_id, _digest = build_reviewed_package(
        centre_code="SITE_A",
        dictionary_id="synthetic-lab",
        dictionary_version="2026.08",
        created_by="site-a-investigator@example.test",
        created_at="2026-08-14T00:00:00+00:00",
        records=[record, {**record, "reviewed_at": "2026-08-14T01:00:00+00:00"}],
    )

    parsed = parse_reviewed_package(content)
    assert parsed["record_count"] == 1
    assert parsed["records"][0]["reviewed_at"] == "2026-08-14T01:00:00+00:00"


def test_package_builder_rejects_conflicting_historical_duplicates() -> None:
    record = {
        "centre_code": "SITE_A",
        "edc_subject_ref": "SUBJ001",
        "edc_event_ref": "WEEK_0",
        "field_code": "ALT",
        "final_value": "31",
        "unit": "U/L",
        "source_sha256": "a" * 64,
        "reviewed_at": "2026-08-14T00:00:00+00:00",
    }

    with pytest.raises(OfflinePackageError, match="offline_package_conflicting_record"):
        build_reviewed_package(
            centre_code="SITE_A",
            dictionary_id="synthetic-lab",
            dictionary_version="2026.08",
            created_by="site-a-investigator@example.test",
            created_at="2026-08-14T00:00:00+00:00",
            records=[record, {**record, "final_value": "32"}],
        )
