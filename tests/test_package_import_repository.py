from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.package_import_repository import (
    PackageImportAttempt,
    PackageImportRepository,
    PackageImportReceipt,
    SQLitePackageImportRepository,
)
from app.persistence import Database


def make_receipt(*, package_id: str | None = None, package_sha256: str | None = None) -> PackageImportReceipt:
    return PackageImportReceipt(
        id=str(uuid4()),
        package_id=package_id or str(uuid4()),
        package_sha256=package_sha256 or uuid4().hex + uuid4().hex,
        centre_code="SITE_A",
        record_count=3,
        created_by="central-data-manager@example.test",
        created_at="2026-08-22T08:00:00+00:00",
    )


def make_attempt(receipt: PackageImportReceipt) -> PackageImportAttempt:
    return PackageImportAttempt(
        id=str(uuid4()),
        package_sha256=receipt.package_sha256,
        package_id=receipt.package_id,
        centre_code=receipt.centre_code,
        source_filename="../../centre-a.enc.json",
        dictionary_id="rct-dictionary",
        dictionary_version="2026.08",
        result="imported",
        error_code=None,
        error_detail="",
        record_count=3,
        created_count=2,
        duplicate_count=1,
        created_by=receipt.created_by,
        created_at="2026-08-22T08:01:00+00:00",
    )


def exercise_repository_contract(repository: PackageImportRepository) -> None:
    receipt = make_receipt()

    assert repository.claim(receipt) is True
    assert repository.claim(receipt) is False
    assert repository.claim(make_receipt(package_id=receipt.package_id)) is False
    assert repository.claim(make_receipt(package_sha256=receipt.package_sha256)) is False

    found = repository.find_receipt(
        package_sha256=receipt.package_sha256,
        package_id=receipt.package_id,
    )
    assert found == receipt

    repository.append_attempt(make_attempt(receipt))
    attempts = repository.list_attempts(limit=10)
    assert len(attempts) == 1
    assert attempts[0].source_filename == "centre-a.enc.json"
    assert attempts[0].result == "imported"
    assert attempts[0].created_count == 2
    assert attempts[0].duplicate_count == 1


def test_sqlite_package_import_repository_contract(tmp_path: Path) -> None:
    database = Database(tmp_path / "package-ledger.db")
    database.initialise()

    exercise_repository_contract(SQLitePackageImportRepository(database))


def test_sqlite_claim_can_join_and_roll_back_the_callers_transaction(tmp_path: Path) -> None:
    database = Database(tmp_path / "package-ledger-rollback.db")
    database.initialise()
    repository = SQLitePackageImportRepository(database)
    receipt = make_receipt()

    with pytest.raises(RuntimeError, match="synthetic_candidate_write_failed"):
        with database.connect() as connection:
            assert repository.claim_in_connection(connection, receipt) is True
            repository.append_attempt_in_connection(connection, make_attempt(receipt))
            raise RuntimeError("synthetic_candidate_write_failed")

    assert repository.find_receipt(
        package_sha256=receipt.package_sha256,
        package_id=receipt.package_id,
    ) is None
    assert repository.list_attempts() == []


def test_import_attempt_bounds_untrusted_display_text() -> None:
    receipt = make_receipt()
    attempt = make_attempt(receipt)
    bounded = PackageImportAttempt(
        **{
            **attempt.__dict__,
            "source_filename": "folder\\" + "x" * 250 + ".json",
            "error_detail": "d" * 700,
        }
    )

    assert len(bounded.source_filename) == 200
    assert "\\" not in bounded.source_filename
    assert len(bounded.error_detail or "") == 500


@pytest.mark.postgres
def test_postgres_package_import_repository_contract() -> None:
    dsn = os.getenv("CLINDATA_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("CLINDATA_TEST_POSTGRES_DSN is not configured")

    from app.postgres_repository import PostgresPackageImportRepository

    repository = PostgresPackageImportRepository(dsn, environment="test")
    repository.prepare()
    exercise_repository_contract(repository)
