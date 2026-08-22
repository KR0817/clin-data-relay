"""Atomic persistence for validated, human-reviewed centre-package values."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import uuid4

from app.audit_chain import ChainVerification, GENESIS_PREV_HASH
from app.package_import_repository import (
    PackageImportAttempt,
    PackageImportReceipt,
    SQLitePackageImportRepository,
)
from app.persistence import Database


SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
SUBJECT_RE = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
EVENT_RE = re.compile(r"^[A-Z][A-Z0-9_-]{1,63}$")
FIELD_RE = re.compile(r"^[A-Z][A-Z0-9_-]{0,63}$")
QUALITY_STATUSES = {"PASS", "WARN", "BLOCK"}


@dataclass(frozen=True)
class ReviewedImportQuality:
    status: Literal["PASS", "WARN", "BLOCK"]
    rule_version: str
    findings_json: str

    def __post_init__(self) -> None:
        if self.status not in QUALITY_STATUSES or not self.rule_version:
            raise ValueError("reviewed_import_quality_invalid")
        try:
            findings = json.loads(self.findings_json)
        except (json.JSONDecodeError, TypeError):
            raise ValueError("reviewed_import_quality_findings_invalid") from None
        if not isinstance(findings, list):
            raise ValueError("reviewed_import_quality_findings_invalid")
        if any(
            not isinstance(finding, dict) or not isinstance(finding.get("code"), str)
            for finding in findings
        ):
            raise ValueError("reviewed_import_quality_findings_invalid")
        object.__setattr__(
            self,
            "findings_json",
            json.dumps(findings, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )


@dataclass(frozen=True)
class ReviewedImportRecord:
    source_sha256: str
    edc_subject_ref: str
    edc_event_ref: str
    field_code: str
    final_value: str
    unit: str | None
    reviewed_at: str
    quality: ReviewedImportQuality

    def __post_init__(self) -> None:
        if not SHA256_RE.fullmatch(self.source_sha256):
            raise ValueError("reviewed_import_source_sha256_invalid")
        if not SUBJECT_RE.fullmatch(self.edc_subject_ref):
            raise ValueError("reviewed_import_reference_invalid")
        if not EVENT_RE.fullmatch(self.edc_event_ref) or not FIELD_RE.fullmatch(self.field_code):
            raise ValueError("reviewed_import_reference_invalid")
        if not self.final_value or len(self.final_value) > 200 or not self.reviewed_at:
            raise ValueError("reviewed_import_value_invalid")
        if self.unit is not None and len(self.unit) > 100:
            raise ValueError("reviewed_import_unit_invalid")
        try:
            reviewed_at = datetime.fromisoformat(self.reviewed_at.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("reviewed_import_timestamp_invalid") from None
        if reviewed_at.tzinfo is None:
            raise ValueError("reviewed_import_timestamp_invalid")
        object.__setattr__(self, "reviewed_at", reviewed_at.astimezone(UTC).isoformat())


@dataclass(frozen=True)
class ReviewedPackageImportCommand:
    receipt: PackageImportReceipt
    source_file_id: str
    source_filename: str
    storage_key: str
    dictionary_id: str
    dictionary_version: str
    records: tuple[ReviewedImportRecord, ...]

    def __post_init__(self) -> None:
        if not self.source_file_id or not self.source_filename or not self.storage_key:
            raise ValueError("reviewed_import_source_required")
        source_filename = self.source_filename.replace("\\", "/").rsplit("/", 1)[-1]
        if not source_filename or len(self.storage_key) > 500:
            raise ValueError("reviewed_import_source_required")
        object.__setattr__(self, "source_filename", source_filename[:200])
        if not self.dictionary_id or not self.dictionary_version:
            raise ValueError("reviewed_import_dictionary_required")
        if not self.records or self.receipt.record_count != len(self.records):
            raise ValueError("reviewed_import_record_count_mismatch")


@dataclass(frozen=True)
class ReviewedImportResult:
    status: Literal["imported", "duplicate"]
    import_id: str
    package_id: str
    package_sha256: str
    centre_code: str
    record_count: int
    created_count: int
    duplicate_count: int
    candidate_ids: tuple[str, ...]
    audit_head_hash: str | None


@dataclass(frozen=True)
class ImportedReviewedValue:
    candidate_id: str
    centre_code: str
    edc_subject_ref: str
    edc_event_ref: str
    field_code: str
    final_value: str
    unit: str | None
    reviewed_at: str
    quality_status: str
    quality_rule_version: str


class ReviewedImportRepository(Protocol):
    def import_package(self, command: ReviewedPackageImportCommand) -> ReviewedImportResult: ...

    def list_imported_values(self, import_id: str) -> list[ImportedReviewedValue]: ...

    def verify_audit_chain(self) -> ChainVerification: ...


def imported_attempt(
    command: ReviewedPackageImportCommand,
    *,
    result: Literal["imported", "duplicate"],
    created_count: int,
    duplicate_count: int,
) -> PackageImportAttempt:
    return PackageImportAttempt(
        id=str(uuid4()),
        package_sha256=command.receipt.package_sha256,
        package_id=command.receipt.package_id,
        centre_code=command.receipt.centre_code,
        source_filename=command.source_filename,
        dictionary_id=command.dictionary_id,
        dictionary_version=command.dictionary_version,
        result=result,
        error_code="offline_package_already_imported" if result == "duplicate" else None,
        error_detail="",
        record_count=command.receipt.record_count,
        created_count=created_count,
        duplicate_count=duplicate_count,
        created_by=command.receipt.created_by,
        created_at=command.receipt.created_at,
    )


class SQLiteReviewedImportRepository:
    """SQLite adapter for the complete reviewed-package clinical transaction."""

    def __init__(self, database: Database) -> None:
        self._database = database
        self._package_repository = SQLitePackageImportRepository(database)

    def import_package(self, command: ReviewedPackageImportCommand) -> ReviewedImportResult:
        created_ids: list[str] = []
        duplicate_count = 0
        with self._database.connect() as connection:
            if not self._package_repository.claim_in_connection(connection, command.receipt):
                self._package_repository.append_attempt_in_connection(
                    connection,
                    imported_attempt(
                        command,
                        result="duplicate",
                        created_count=0,
                        duplicate_count=0,
                    ),
                )
                return self._result(
                    command,
                    status="duplicate",
                    created_ids=(),
                    duplicate_count=0,
                    audit_head_hash=self._audit_head(connection),
                )

            connection.execute(
                """
                INSERT INTO source_files (
                    id, centre_code, source_filename, sha256, mime_type, storage_key,
                    created_by, created_at
                ) VALUES (?, ?, ?, ?, 'application/json', ?, ?, ?)
                """,
                (
                    command.source_file_id,
                    command.receipt.centre_code,
                    command.source_filename,
                    command.receipt.package_sha256,
                    command.storage_key,
                    command.receipt.created_by,
                    command.receipt.created_at,
                ),
            )
            for record in command.records:
                duplicate = connection.execute(
                    """
                    SELECT id FROM candidates
                    WHERE centre_code = ? AND edc_subject_ref = ? AND edc_event_ref = ?
                      AND field_code = ? AND proposed_value = ? AND unit IS ?
                      AND status != 'rejected'
                    LIMIT 1
                    """,
                    (
                        command.receipt.centre_code,
                        record.edc_subject_ref,
                        record.edc_event_ref,
                        record.field_code,
                        record.final_value,
                        record.unit,
                    ),
                ).fetchone()
                if duplicate is not None:
                    duplicate_count += 1
                    continue
                candidate_id = str(uuid4())
                self._insert_candidate(connection, command, record, candidate_id)
                self._append_candidate_audit(connection, command, record, candidate_id)
                self._insert_quality(connection, command, record, candidate_id)
                created_ids.append(candidate_id)

            self._package_repository.append_attempt_in_connection(
                connection,
                imported_attempt(
                    command,
                    result="imported",
                    created_count=len(created_ids),
                    duplicate_count=duplicate_count,
                ),
            )
            return self._result(
                command,
                status="imported",
                created_ids=tuple(created_ids),
                duplicate_count=duplicate_count,
                audit_head_hash=self._audit_head(connection),
            )

    def _insert_candidate(
        self,
        connection: sqlite3.Connection,
        command: ReviewedPackageImportCommand,
        record: ReviewedImportRecord,
        candidate_id: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO candidates (
                id, centre_code, source_file_id, edc_subject_ref, edc_event_ref,
                field_code, proposed_value, unit, final_value, status,
                ocr_engine_version, kimi_model, schema_version, confidence,
                local_ocr_value, local_ocr_unit, extraction_agreement, evidence_text,
                import_batch_id, origin_type, created_by, created_at,
                reviewed_by, reviewed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'human_confirmed',
                      'offline-reviewed-package-v1', 'not_used_offline_package',
                      'offline-reviewed-package-v1', 1.0, ?, ?, 'offline_reviewed', ?,
                      ?, 'offline_package', ?, ?, 'originating-centre-reviewer', ?)
            """,
            (
                candidate_id,
                command.receipt.centre_code,
                command.source_file_id,
                record.edc_subject_ref,
                record.edc_event_ref,
                record.field_code,
                record.final_value,
                record.unit,
                record.final_value,
                record.final_value,
                record.unit,
                "Imported from a reviewed centre package; source evidence remains at the originating centre.",
                command.receipt.id,
                command.receipt.created_by,
                command.receipt.created_at,
                record.reviewed_at,
            ),
        )

    def _append_candidate_audit(
        self,
        connection: sqlite3.Connection,
        command: ReviewedPackageImportCommand,
        record: ReviewedImportRecord,
        candidate_id: str,
    ) -> None:
        self._database.append_audit_event(
            connection,
            candidate_id=candidate_id,
            centre_code=command.receipt.centre_code,
            event_type="offline_package_imported",
            actor_username=command.receipt.created_by,
            details={
                "package_id": command.receipt.package_id,
                "package_sha256": command.receipt.package_sha256,
                "source_sha256": record.source_sha256,
                "field_code": record.field_code,
            },
            created_at=command.receipt.created_at,
        )

    def _insert_quality(
        self,
        connection: sqlite3.Connection,
        command: ReviewedPackageImportCommand,
        record: ReviewedImportRecord,
        candidate_id: str,
    ) -> None:
        assessment_id = str(uuid4())
        connection.execute(
            """
            INSERT INTO quality_findings (
                id, candidate_id, centre_code, rule_version, status, findings_json,
                evaluated_value, evaluated_unit, evaluated_by, evaluated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                assessment_id,
                candidate_id,
                command.receipt.centre_code,
                record.quality.rule_version,
                record.quality.status,
                record.quality.findings_json,
                record.final_value,
                record.unit,
                command.receipt.created_by,
                command.receipt.created_at,
            ),
        )
        findings = json.loads(record.quality.findings_json)
        self._database.append_audit_event(
            connection,
            candidate_id=candidate_id,
            centre_code=command.receipt.centre_code,
            event_type="candidate_quality_evaluated",
            actor_username=command.receipt.created_by,
            details={
                "assessment_id": assessment_id,
                "status": record.quality.status,
                "rule_version": record.quality.rule_version,
                "finding_codes": [finding["code"] for finding in findings],
            },
            created_at=command.receipt.created_at,
        )

    @staticmethod
    def _audit_head(connection: sqlite3.Connection) -> str:
        row = connection.execute(
            "SELECT event_hash FROM audit_events ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        return str(row["event_hash"]) if row is not None else GENESIS_PREV_HASH

    @staticmethod
    def _result(
        command: ReviewedPackageImportCommand,
        *,
        status: Literal["imported", "duplicate"],
        created_ids: tuple[str, ...],
        duplicate_count: int,
        audit_head_hash: str,
    ) -> ReviewedImportResult:
        return ReviewedImportResult(
            status=status,
            import_id=command.receipt.id,
            package_id=command.receipt.package_id,
            package_sha256=command.receipt.package_sha256,
            centre_code=command.receipt.centre_code,
            record_count=command.receipt.record_count,
            created_count=len(created_ids),
            duplicate_count=duplicate_count,
            candidate_ids=created_ids,
            audit_head_hash=audit_head_hash,
        )

    def list_imported_values(self, import_id: str) -> list[ImportedReviewedValue]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT candidates.id, candidates.centre_code, candidates.edc_subject_ref,
                       candidates.edc_event_ref, candidates.field_code, candidates.final_value,
                       candidates.unit, candidates.reviewed_at, quality_findings.status,
                       quality_findings.rule_version
                FROM candidates
                JOIN quality_findings ON quality_findings.candidate_id = candidates.id
                WHERE candidates.import_batch_id = ?
                ORDER BY candidates.rowid
                """,
                (import_id,),
            ).fetchall()
        return [
            ImportedReviewedValue(
                candidate_id=str(row["id"]),
                centre_code=str(row["centre_code"]),
                edc_subject_ref=str(row["edc_subject_ref"]),
                edc_event_ref=str(row["edc_event_ref"]),
                field_code=str(row["field_code"]),
                final_value=str(row["final_value"]),
                unit=row["unit"],
                reviewed_at=str(row["reviewed_at"]),
                quality_status=str(row["status"]),
                quality_rule_version=str(row["rule_version"]),
            )
            for row in rows
        ]

    def verify_audit_chain(self) -> ChainVerification:
        with self._database.connect() as connection:
            return self._database.verify_audit_chain(connection)
