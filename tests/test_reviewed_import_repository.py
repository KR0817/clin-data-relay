from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.package_import_repository import PackageImportReceipt
from app.persistence import Database
from app.reviewed_import_repository import (
    ReviewedImportQuality,
    ReviewedImportRecord,
    ReviewedImportRepository,
    ReviewedPackageImportCommand,
    SQLiteReviewedImportRepository,
)


def digest() -> str:
    return uuid4().hex + uuid4().hex


def quality(status: str = "PASS") -> ReviewedImportQuality:
    return ReviewedImportQuality(
        status=status,
        rule_version="clinical-quality-v1",
        findings_json=json.dumps([], separators=(",", ":")),
    )


def record(field_code: str, value: str) -> ReviewedImportRecord:
    return ReviewedImportRecord(
        source_sha256=digest(),
        edc_subject_ref="SUBJ001",
        edc_event_ref="WEEK_0",
        field_code=field_code,
        final_value=value,
        unit="U/L" if field_code == "ALT" else "mg/L",
        reviewed_at="2026-08-22T07:55:00+00:00",
        quality=quality(),
    )


def command(*records: ReviewedImportRecord) -> ReviewedPackageImportCommand:
    receipt = PackageImportReceipt(
        id=str(uuid4()),
        package_id=str(uuid4()),
        package_sha256=digest(),
        centre_code="SITE_A",
        record_count=len(records),
        created_by="central-data-manager@example.test",
        created_at="2026-08-22T08:00:00+00:00",
    )
    return ReviewedPackageImportCommand(
        receipt=receipt,
        source_file_id=str(uuid4()),
        source_filename="site-a.enc.json",
        storage_key=f"offline-package/{receipt.package_sha256}.json",
        dictionary_id="rct-dictionary",
        dictionary_version="2026.08",
        records=records,
    )


def exercise_reviewed_import_contract(repository: ReviewedImportRepository) -> None:
    first_command = command(record("ALT", "31"), record("CRP", "4.2"))
    first = repository.import_package(first_command)

    assert first.status == "imported"
    assert first.record_count == 2
    assert first.created_count == 2
    assert first.duplicate_count == 0
    assert len(first.candidate_ids) == 2
    assert len(first.audit_head_hash or "") == 64

    values = repository.list_imported_values(first.import_id)
    assert [(item.field_code, item.final_value, item.quality_status) for item in values] == [
        ("ALT", "31", "PASS"),
        ("CRP", "4.2", "PASS"),
    ]

    repeated = repository.import_package(first_command)
    assert repeated.status == "duplicate"
    assert repeated.created_count == 0
    assert repeated.candidate_ids == ()

    second_command = command(record("ALT", "31"), record("K", "4.6"))
    second = repository.import_package(second_command)
    assert second.status == "imported"
    assert second.created_count == 1
    assert second.duplicate_count == 1
    assert [item.field_code for item in repository.list_imported_values(second.import_id)] == ["K"]

    verification = repository.verify_audit_chain()
    assert verification.ok is True
    assert verification.checked >= 6
    assert verification.head_hash == second.audit_head_hash


def test_sqlite_reviewed_import_repository_contract(tmp_path: Path) -> None:
    database = Database(tmp_path / "reviewed-import.db")
    database.initialise()
    exercise_reviewed_import_contract(SQLiteReviewedImportRepository(database))


@pytest.mark.postgres
def test_postgres_reviewed_import_repository_contract() -> None:
    dsn = os.getenv("CLINDATA_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("CLINDATA_TEST_POSTGRES_DSN is not configured")

    from app.postgres_reviewed_import_repository import PostgresReviewedImportRepository

    repository = PostgresReviewedImportRepository(dsn, environment="test")
    repository.prepare()
    exercise_reviewed_import_contract(repository)
