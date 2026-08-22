from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.confirmed_data_repository import (
    ConfirmedDataRepository,
    ConfirmedDataScope,
    SQLiteConfirmedDataRepository,
)
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


def command(
    *,
    centre_code: str,
    subject_ref: str,
    event_ref: str,
    created_at: str,
    fields: tuple[tuple[str, str, str], ...],
) -> ReviewedPackageImportCommand:
    receipt = PackageImportReceipt(
        id=str(uuid4()),
        package_id=str(uuid4()),
        package_sha256=digest(),
        centre_code=centre_code,
        record_count=len(fields),
        created_by="central-data-manager@example.test",
        created_at=created_at,
    )
    records = tuple(
        ReviewedImportRecord(
            source_sha256=digest(),
            edc_subject_ref=subject_ref,
            edc_event_ref=event_ref,
            field_code=field_code,
            final_value=value,
            unit="U/L",
            reviewed_at=created_at,
            quality=ReviewedImportQuality(
                status=quality_status,
                rule_version="clinical-quality-v1",
                findings_json=json.dumps([], separators=(",", ":")),
            ),
        )
        for field_code, value, quality_status in fields
    )
    return ReviewedPackageImportCommand(
        receipt=receipt,
        source_file_id=str(uuid4()),
        source_filename=f"{centre_code.lower()}.enc.json",
        storage_key=f"offline-package/{receipt.package_sha256}.json",
        dictionary_id="rct-dictionary",
        dictionary_version="2026.08",
        records=records,
    )


def exercise_confirmed_data_contract(
    import_repository: ReviewedImportRepository,
    read_repository: ConfirmedDataRepository,
) -> None:
    first = command(
        centre_code=f"SITE_{uuid4().hex[:8].upper()}",
        subject_ref=f"SUBJ{uuid4().hex[:8].upper()}",
        event_ref="WEEK_0",
        created_at="2026-08-22T08:00:00+00:00",
        fields=(("ALT", "31", "PASS"), ("CRP", "4.2", "WARN")),
    )
    second = command(
        centre_code=f"SITE_{uuid4().hex[:8].upper()}",
        subject_ref=f"SUBJ{uuid4().hex[:8].upper()}",
        event_ref="WEEK_4",
        created_at="2026-08-22T08:05:00+00:00",
        fields=(("K", "4.6", "PASS"),),
    )
    import_repository.import_package(first)
    import_repository.import_package(second)

    all_rows = read_repository.list_confirmed(ConfirmedDataScope.for_all_centres())
    relevant = [
        row
        for row in all_rows
        if row.edc_subject_ref in {first.records[0].edc_subject_ref, second.records[0].edc_subject_ref}
    ]
    assert [row.field_code for row in relevant] == ["ALT", "CRP", "K"]
    assert [row.quality_status for row in relevant] == ["PASS", "WARN", "PASS"]
    assert all(row.quality_rule_version == "clinical-quality-v1" for row in relevant)
    assert all(row.authority_submitted is False for row in relevant)

    centre_rows = read_repository.list_confirmed(
        ConfirmedDataScope.for_centre(first.receipt.centre_code)
    )
    assert [(row.edc_subject_ref, row.field_code) for row in centre_rows] == [
        (first.records[0].edc_subject_ref, "ALT"),
        (first.records[0].edc_subject_ref, "CRP"),
    ]

    subject_rows = read_repository.list_confirmed(
        ConfirmedDataScope.for_all_centres(subject_ref=second.records[0].edc_subject_ref)
    )
    assert [(row.centre_code, row.edc_event_ref, row.field_code) for row in subject_rows] == [
        (second.receipt.centre_code, "WEEK_4", "K")
    ]

    assert read_repository.list_confirmed(
        ConfirmedDataScope.for_centre(first.receipt.centre_code, event_ref="WEEK_4")
    ) == []


def test_confirmed_data_scope_rejects_implicit_or_conflicting_global_access() -> None:
    with pytest.raises(ValueError, match="confirmed_data_scope_invalid"):
        ConfirmedDataScope(centre_code=None, all_centres=False)
    with pytest.raises(ValueError, match="confirmed_data_scope_invalid"):
        ConfirmedDataScope(centre_code="SITE_A", all_centres=True)
    with pytest.raises(ValueError, match="confirmed_data_scope_invalid"):
        ConfirmedDataScope.for_centre("site a")


def test_sqlite_confirmed_data_repository_contract(tmp_path: Path) -> None:
    database = Database(tmp_path / "confirmed-data.db")
    database.initialise()
    exercise_confirmed_data_contract(
        SQLiteReviewedImportRepository(database),
        SQLiteConfirmedDataRepository(database),
    )


def test_sqlite_confirmed_data_repository_excludes_non_confirmed_rows(tmp_path: Path) -> None:
    database = Database(tmp_path / "confirmed-only.db")
    database.initialise()
    import_repository = SQLiteReviewedImportRepository(database)
    import_command = command(
        centre_code="SITE_FILTER",
        subject_ref="SUBJFILTER",
        event_ref="WEEK_0",
        created_at="2026-08-22T09:00:00+00:00",
        fields=(("ALT", "31", "PASS"), ("CRP", "4.2", "PASS")),
    )
    result = import_repository.import_package(import_command)
    with database.connect() as connection:
        connection.execute(
            "UPDATE candidates SET status = 'rejected' WHERE id = ?",
            (result.candidate_ids[0],),
        )
        connection.execute(
            "UPDATE candidates SET status = 'candidate' WHERE id = ?",
            (result.candidate_ids[1],),
        )

    assert SQLiteConfirmedDataRepository(database).list_confirmed(
        ConfirmedDataScope.for_centre("SITE_FILTER")
    ) == []


@pytest.mark.postgres
def test_postgres_confirmed_data_repository_contract() -> None:
    dsn = os.getenv("CLINDATA_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("CLINDATA_TEST_POSTGRES_DSN is not configured")

    from app.postgres_confirmed_data_repository import PostgresConfirmedDataRepository
    from app.postgres_reviewed_import_repository import PostgresReviewedImportRepository

    import_repository = PostgresReviewedImportRepository(dsn, environment="test")
    read_repository = PostgresConfirmedDataRepository(dsn, environment="test")
    import_repository.prepare()
    exercise_confirmed_data_contract(import_repository, read_repository)
