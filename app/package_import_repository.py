"""Repository contract for encrypted centre-package receipts and attempt logs."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Literal, Protocol

from app.persistence import Database


SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
IMPORT_RESULTS = {"imported", "duplicate", "failed"}


def _bounded(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return value[:limit]


def _safe_filename(value: str) -> str:
    basename = value.replace("\\", "/").rsplit("/", 1)[-1]
    return (basename or "package")[:200]


@dataclass(frozen=True)
class PackageImportReceipt:
    """Immutable proof that one encrypted package was accepted for import."""

    id: str
    package_id: str
    package_sha256: str
    centre_code: str
    record_count: int
    created_by: str
    created_at: str

    def __post_init__(self) -> None:
        if not SHA256_RE.fullmatch(self.package_sha256):
            raise ValueError("package_sha256_invalid")
        if not self.id or not self.package_id or not self.centre_code or not self.created_by:
            raise ValueError("package_receipt_identity_required")
        if not self.created_at:
            raise ValueError("package_receipt_timestamp_required")
        if self.record_count < 0:
            raise ValueError("package_record_count_invalid")


@dataclass(frozen=True)
class PackageImportAttempt:
    """Bounded append-only metadata for one package import outcome."""

    id: str
    package_sha256: str | None
    package_id: str | None
    centre_code: str | None
    source_filename: str
    dictionary_id: str | None
    dictionary_version: str | None
    result: Literal["imported", "duplicate", "failed"]
    error_code: str | None
    error_detail: str | None
    record_count: int
    created_count: int
    duplicate_count: int
    created_by: str
    created_at: str

    def __post_init__(self) -> None:
        if self.package_sha256 is not None and not SHA256_RE.fullmatch(self.package_sha256):
            raise ValueError("package_sha256_invalid")
        if self.result not in IMPORT_RESULTS:
            raise ValueError("package_import_result_invalid")
        if min(self.record_count, self.created_count, self.duplicate_count) < 0:
            raise ValueError("package_import_count_invalid")
        if not self.id or not self.created_by:
            raise ValueError("package_import_actor_required")
        if not self.created_at:
            raise ValueError("package_import_timestamp_required")

        object.__setattr__(self, "source_filename", _safe_filename(self.source_filename))
        object.__setattr__(self, "package_id", _bounded(self.package_id, 200))
        object.__setattr__(self, "centre_code", _bounded(self.centre_code, 100))
        object.__setattr__(self, "dictionary_id", _bounded(self.dictionary_id, 200))
        object.__setattr__(self, "dictionary_version", _bounded(self.dictionary_version, 100))
        object.__setattr__(self, "error_code", _bounded(self.error_code, 120))
        object.__setattr__(self, "error_detail", _bounded(self.error_detail, 500))

    def public_payload(self) -> dict[str, object]:
        """Return the existing secret-free HTTP log representation."""

        return {
            "id": self.id,
            "package_sha256": self.package_sha256,
            "package_id": self.package_id,
            "centre_code": self.centre_code,
            "source_filename": self.source_filename,
            "dictionary_id": self.dictionary_id,
            "dictionary_version": self.dictionary_version,
            "result": self.result,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "record_count": self.record_count,
            "created_count": self.created_count,
            "duplicate_count": self.duplicate_count,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }


class PackageImportRepository(Protocol):
    """Database-neutral behavior required by package-import orchestration."""

    def claim(self, receipt: PackageImportReceipt) -> bool: ...

    def find_receipt(
        self,
        *,
        package_sha256: str,
        package_id: str,
    ) -> PackageImportReceipt | None: ...

    def append_attempt(self, attempt: PackageImportAttempt) -> None: ...

    def list_attempts(self, *, limit: int = 100) -> list[PackageImportAttempt]: ...


def _receipt_from_row(row: sqlite3.Row) -> PackageImportReceipt:
    return PackageImportReceipt(
        id=str(row["id"]),
        package_id=str(row["package_id"]),
        package_sha256=str(row["package_sha256"]),
        centre_code=str(row["centre_code"]),
        record_count=int(row["record_count"]),
        created_by=str(row["created_by"]),
        created_at=str(row["created_at"]),
    )


def _attempt_from_row(row: sqlite3.Row) -> PackageImportAttempt:
    return PackageImportAttempt(
        id=str(row["id"]),
        package_sha256=row["package_sha256"],
        package_id=row["package_id"],
        centre_code=row["centre_code"],
        source_filename=str(row["source_filename"]),
        dictionary_id=row["dictionary_id"],
        dictionary_version=row["dictionary_version"],
        result=str(row["result"]),  # type: ignore[arg-type]
        error_code=row["error_code"],
        error_detail=row["error_detail"],
        record_count=int(row["record_count"]),
        created_count=int(row["created_count"]),
        duplicate_count=int(row["duplicate_count"]),
        created_by=str(row["created_by"]),
        created_at=str(row["created_at"]),
    )


class SQLitePackageImportRepository:
    """SQLite adapter; final claims may join the caller's clinical transaction."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def claim(self, receipt: PackageImportReceipt) -> bool:
        with self._database.connect() as connection:
            return self.claim_in_connection(connection, receipt)

    def claim_in_connection(
        self,
        connection: sqlite3.Connection,
        receipt: PackageImportReceipt,
    ) -> bool:
        cursor = connection.execute(
            """
            INSERT INTO offline_package_imports (
                id, package_id, package_sha256, centre_code, record_count, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT DO NOTHING
            """,
            (
                receipt.id,
                receipt.package_id,
                receipt.package_sha256,
                receipt.centre_code,
                receipt.record_count,
                receipt.created_by,
                receipt.created_at,
            ),
        )
        return cursor.rowcount == 1

    def find_receipt(
        self,
        *,
        package_sha256: str,
        package_id: str,
    ) -> PackageImportReceipt | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, package_id, package_sha256, centre_code,
                       record_count, created_by, created_at
                FROM offline_package_imports
                WHERE package_sha256 = ? OR package_id = ?
                LIMIT 1
                """,
                (package_sha256, package_id),
            ).fetchone()
        return _receipt_from_row(row) if row is not None else None

    def append_attempt(self, attempt: PackageImportAttempt) -> None:
        with self._database.connect() as connection:
            self.append_attempt_in_connection(connection, attempt)

    def append_attempt_in_connection(
        self,
        connection: sqlite3.Connection,
        attempt: PackageImportAttempt,
    ) -> None:
        connection.execute(
            """
            INSERT INTO offline_package_import_logs (
                id, package_sha256, package_id, centre_code, source_filename,
                dictionary_id, dictionary_version, result, error_code, error_detail,
                record_count, created_count, duplicate_count, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt.id,
                attempt.package_sha256,
                attempt.package_id,
                attempt.centre_code,
                attempt.source_filename,
                attempt.dictionary_id,
                attempt.dictionary_version,
                attempt.result,
                attempt.error_code,
                attempt.error_detail,
                attempt.record_count,
                attempt.created_count,
                attempt.duplicate_count,
                attempt.created_by,
                attempt.created_at,
            ),
        )

    def list_attempts(self, *, limit: int = 100) -> list[PackageImportAttempt]:
        if not 1 <= limit <= 500:
            raise ValueError("package_import_log_limit_invalid")
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, package_sha256, package_id, centre_code, source_filename,
                       dictionary_id, dictionary_version, result, error_code, error_detail,
                       record_count, created_count, duplicate_count, created_by, created_at
                FROM offline_package_import_logs
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_attempt_from_row(row) for row in rows]
