"""PostgreSQL adapter for atomic reviewed centre-package clinical imports."""

from __future__ import annotations

import json
from typing import Literal
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from app.audit_chain import (
    GENESIS_PREV_HASH,
    ChainVerification,
    compute_event_hash,
    event_payload,
    verify_chain,
)
from app.postgres_repository import (
    PostgresPackageImportRepository,
    PostgresRepositoryBootstrap,
    PostgresRepositoryError,
    PostgresRepositoryStatus,
)
from app.reviewed_import_repository import (
    ImportedReviewedValue,
    ReviewedImportRecord,
    ReviewedImportResult,
    ReviewedPackageImportCommand,
    imported_attempt,
)


AUDIT_APPEND_LOCK_ID = 0x4344524155444954


def _timestamp_text(value: object) -> str:
    isoformat = getattr(value, "isoformat", None)
    return str(isoformat()) if callable(isoformat) else str(value)


class PostgresReviewedImportRepository:
    """Persist one reviewed package, its quality and audit trail atomically."""

    def __init__(self, dsn: str, *, environment: str) -> None:
        self._bootstrap = PostgresRepositoryBootstrap(dsn, environment=environment)

    def prepare(self) -> PostgresRepositoryStatus:
        return self._bootstrap.prepare()

    def import_package(self, command: ReviewedPackageImportCommand) -> ReviewedImportResult:
        created_ids: list[str] = []
        duplicate_count = 0
        try:
            with self._bootstrap._open_connection() as connection:
                if not PostgresPackageImportRepository.claim_in_connection(connection, command.receipt):
                    PostgresPackageImportRepository.append_attempt_in_connection(
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

                connection.execute("SELECT pg_advisory_xact_lock(%s)", (AUDIT_APPEND_LOCK_ID,))
                connection.execute(
                    """
                    INSERT INTO source_files (
                        id, centre_code, source_filename, sha256, mime_type,
                        storage_key, created_by, created_at
                    ) VALUES (%s, %s, %s, %s, 'application/json', %s, %s, %s)
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
                    candidate_id = str(uuid4())
                    inserted = self._insert_candidate(connection, command, record, candidate_id)
                    if not inserted:
                        duplicate_count += 1
                        continue
                    self._append_audit(
                        connection,
                        command=command,
                        candidate_id=candidate_id,
                        event_type="offline_package_imported",
                        details={
                            "package_id": command.receipt.package_id,
                            "package_sha256": command.receipt.package_sha256,
                            "source_sha256": record.source_sha256,
                            "field_code": record.field_code,
                        },
                    )
                    self._insert_quality(connection, command, record, candidate_id)
                    created_ids.append(candidate_id)

                PostgresPackageImportRepository.append_attempt_in_connection(
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
        except (psycopg.Error, TypeError, ValueError, KeyError):
            raise PostgresRepositoryError("postgres_reviewed_import_unavailable") from None

    @staticmethod
    def _insert_candidate(connection, command, record, candidate_id: str) -> bool:
        row = connection.execute(
            """
            INSERT INTO candidates (
                id, centre_code, source_file_id, edc_subject_ref, edc_event_ref,
                field_code, proposed_value, unit, final_value, status,
                ocr_engine_version, kimi_model, schema_version, confidence,
                local_ocr_value, local_ocr_unit, extraction_agreement, evidence_text,
                import_batch_id, origin_type, created_by, created_at,
                reviewed_by, reviewed_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'human_confirmed',
                      'offline-reviewed-package-v1', 'not_used_offline_package',
                      'offline-reviewed-package-v1', 1.0, %s, %s, 'offline_reviewed', %s,
                      %s, 'offline_package', %s, %s, 'originating-centre-reviewer', %s)
            ON CONFLICT DO NOTHING
            RETURNING id
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
        ).fetchone()
        return row is not None

    def _insert_quality(
        self,
        connection,
        command: ReviewedPackageImportCommand,
        record: ReviewedImportRecord,
        candidate_id: str,
    ) -> None:
        assessment_id = str(uuid4())
        findings = json.loads(record.quality.findings_json)
        connection.execute(
            """
            INSERT INTO quality_findings (
                id, candidate_id, centre_code, rule_version, status, findings_json,
                evaluated_value, evaluated_unit, evaluated_by, evaluated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                assessment_id,
                candidate_id,
                command.receipt.centre_code,
                record.quality.rule_version,
                record.quality.status,
                Jsonb(findings),
                record.final_value,
                record.unit,
                command.receipt.created_by,
                command.receipt.created_at,
            ),
        )
        self._append_audit(
            connection,
            command=command,
            candidate_id=candidate_id,
            event_type="candidate_quality_evaluated",
            details={
                "assessment_id": assessment_id,
                "status": record.quality.status,
                "rule_version": record.quality.rule_version,
                "finding_codes": [finding["code"] for finding in findings],
            },
        )

    @staticmethod
    def _append_audit(
        connection,
        *,
        command: ReviewedPackageImportCommand,
        candidate_id: str,
        event_type: str,
        details: dict[str, object],
    ) -> None:
        previous_row = connection.execute(
            "SELECT event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous = str(previous_row["event_hash"]) if previous_row is not None else GENESIS_PREV_HASH
        event_id = str(uuid4())
        created_at = command.receipt.created_at
        payload = event_payload(
            event_id=event_id,
            candidate_id=candidate_id,
            centre_code=command.receipt.centre_code,
            event_type=event_type,
            actor_username=command.receipt.created_by,
            created_at=created_at,
            details=details,
        )
        event_hash = compute_event_hash(previous, payload)
        connection.execute(
            """
            INSERT INTO audit_events (
                id, candidate_id, centre_code, event_type, actor_username,
                created_at, details_json, prev_hash, event_hash
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                event_id,
                candidate_id,
                command.receipt.centre_code,
                event_type,
                command.receipt.created_by,
                created_at,
                Jsonb(details),
                previous,
                event_hash,
            ),
        )

    @staticmethod
    def _audit_head(connection) -> str:
        row = connection.execute(
            "SELECT event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
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
        try:
            with self._bootstrap._open_connection() as connection:
                rows = connection.execute(
                    """
                    SELECT candidates.id, candidates.centre_code, candidates.edc_subject_ref,
                           candidates.edc_event_ref, candidates.field_code, candidates.final_value,
                           candidates.unit, candidates.reviewed_at, quality_findings.status,
                           quality_findings.rule_version
                    FROM candidates
                    JOIN quality_findings ON quality_findings.candidate_id = candidates.id
                    WHERE candidates.import_batch_id = %s
                    ORDER BY candidates.sequence
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
                    unit=str(row["unit"]) if row["unit"] is not None else None,
                    reviewed_at=_timestamp_text(row["reviewed_at"]),
                    quality_status=str(row["status"]),
                    quality_rule_version=str(row["rule_version"]),
                )
                for row in rows
            ]
        except (psycopg.Error, TypeError, ValueError):
            raise PostgresRepositoryError("postgres_reviewed_import_unavailable") from None

    def verify_audit_chain(self) -> ChainVerification:
        try:
            with self._bootstrap._open_connection() as connection:
                rows = connection.execute(
                    """
                    SELECT id, candidate_id, centre_code, event_type, actor_username,
                           created_at, details_json, prev_hash, event_hash
                    FROM audit_events
                    ORDER BY sequence
                    """
                ).fetchall()
            events = [
                {
                    "prev_hash": str(row["prev_hash"]),
                    "event_hash": str(row["event_hash"]),
                    "payload": event_payload(
                        event_id=str(row["id"]),
                        candidate_id=str(row["candidate_id"]) if row["candidate_id"] is not None else None,
                        centre_code=str(row["centre_code"]),
                        event_type=str(row["event_type"]),
                        actor_username=str(row["actor_username"]),
                        created_at=_timestamp_text(row["created_at"]),
                        details=dict(row["details_json"]),
                    ),
                }
                for row in rows
            ]
            return verify_chain(events)
        except (psycopg.Error, TypeError, ValueError):
            raise PostgresRepositoryError("postgres_reviewed_import_unavailable") from None
