"""Role-scoped, read-only projection of human-confirmed clinical values."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from app.persistence import Database


CENTRE_RE = re.compile(r"^[A-Z][A-Z0-9_-]{1,31}$")
SUBJECT_RE = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
EVENT_RE = re.compile(r"^[A-Z][A-Z0-9_-]{1,63}$")


@dataclass(frozen=True)
class ConfirmedDataScope:
    """Require callers to choose global or exact-centre access explicitly."""

    centre_code: str | None
    all_centres: bool
    subject_ref: str | None = None
    event_ref: str | None = None

    def __post_init__(self) -> None:
        if self.all_centres == (self.centre_code is not None):
            raise ValueError("confirmed_data_scope_invalid")
        if self.centre_code is not None and not CENTRE_RE.fullmatch(self.centre_code):
            raise ValueError("confirmed_data_scope_invalid")
        if self.subject_ref is not None and not SUBJECT_RE.fullmatch(self.subject_ref):
            raise ValueError("confirmed_data_scope_invalid")
        if self.event_ref is not None and not EVENT_RE.fullmatch(self.event_ref):
            raise ValueError("confirmed_data_scope_invalid")

    @classmethod
    def for_all_centres(
        cls,
        *,
        subject_ref: str | None = None,
        event_ref: str | None = None,
    ) -> ConfirmedDataScope:
        return cls(
            centre_code=None,
            all_centres=True,
            subject_ref=subject_ref,
            event_ref=event_ref,
        )

    @classmethod
    def for_centre(
        cls,
        centre_code: str,
        *,
        subject_ref: str | None = None,
        event_ref: str | None = None,
    ) -> ConfirmedDataScope:
        return cls(
            centre_code=centre_code,
            all_centres=False,
            subject_ref=subject_ref,
            event_ref=event_ref,
        )


@dataclass(frozen=True)
class ConfirmedDataRow:
    candidate_id: str
    centre_code: str
    edc_subject_ref: str
    edc_event_ref: str
    field_code: str
    final_value: str
    unit: str | None
    created_at: str
    reviewed_at: str
    source_sha256: str
    origin_type: str
    import_batch_id: str | None
    quality_status: str | None
    quality_rule_version: str | None
    authority_submitted: bool


class ConfirmedDataRepository(Protocol):
    def list_confirmed(self, scope: ConfirmedDataScope) -> list[ConfirmedDataRow]: ...


class SQLiteConfirmedDataRepository:
    """SQLite adapter used by the current local and Centre Lite application."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def list_confirmed(self, scope: ConfirmedDataScope) -> list[ConfirmedDataRow]:
        conditions = ["candidates.status = 'human_confirmed'"]
        parameters: list[str] = []
        if not scope.all_centres:
            conditions.append("candidates.centre_code = ?")
            parameters.append(str(scope.centre_code))
        if scope.subject_ref is not None:
            conditions.append("candidates.edc_subject_ref = ?")
            parameters.append(scope.subject_ref)
        if scope.event_ref is not None:
            conditions.append("candidates.edc_event_ref = ?")
            parameters.append(scope.event_ref)

        with self._database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT candidates.id, candidates.centre_code,
                       candidates.edc_subject_ref, candidates.edc_event_ref,
                       candidates.field_code, candidates.final_value,
                       candidates.unit, candidates.created_at,
                       candidates.reviewed_at, source_files.sha256 AS source_sha256,
                       candidates.origin_type, candidates.import_batch_id,
                       (
                           SELECT quality.status
                           FROM quality_findings AS quality
                           WHERE quality.candidate_id = candidates.id
                           ORDER BY quality.evaluated_at DESC, quality.id DESC
                           LIMIT 1
                       ) AS quality_status,
                       (
                           SELECT quality.rule_version
                           FROM quality_findings AS quality
                           WHERE quality.candidate_id = candidates.id
                           ORDER BY quality.evaluated_at DESC, quality.id DESC
                           LIMIT 1
                       ) AS quality_rule_version,
                       CASE WHEN EXISTS (
                           SELECT 1 FROM transfer_requests AS authority_transfer
                           WHERE authority_transfer.candidate_id = candidates.id
                             AND authority_transfer.status IN ('submitted', 'reconciled')
                       ) THEN 1 ELSE 0 END AS authority_submitted
                FROM candidates
                JOIN source_files ON source_files.id = candidates.source_file_id
                WHERE {' AND '.join(conditions)}
                ORDER BY candidates.created_at, candidates.rowid
                """,
                tuple(parameters),
            ).fetchall()

        return [
            ConfirmedDataRow(
                candidate_id=str(row["id"]),
                centre_code=str(row["centre_code"]),
                edc_subject_ref=str(row["edc_subject_ref"]),
                edc_event_ref=str(row["edc_event_ref"]),
                field_code=str(row["field_code"]),
                final_value=str(row["final_value"]),
                unit=str(row["unit"]) if row["unit"] is not None else None,
                created_at=str(row["created_at"]),
                reviewed_at=str(row["reviewed_at"]),
                source_sha256=str(row["source_sha256"]),
                origin_type=str(row["origin_type"]),
                import_batch_id=(
                    str(row["import_batch_id"])
                    if row["import_batch_id"] is not None
                    else None
                ),
                quality_status=(
                    str(row["quality_status"])
                    if row["quality_status"] is not None
                    else None
                ),
                quality_rule_version=(
                    str(row["quality_rule_version"])
                    if row["quality_rule_version"] is not None
                    else None
                ),
                authority_submitted=bool(row["authority_submitted"]),
            )
            for row in rows
        ]
