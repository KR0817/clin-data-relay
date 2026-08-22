"""PostgreSQL adapter for scoped human-confirmed clinical reads."""

from __future__ import annotations

import psycopg

from app.confirmed_data_repository import ConfirmedDataRow, ConfirmedDataScope
from app.postgres_repository import (
    PostgresRepositoryBootstrap,
    PostgresRepositoryError,
    PostgresRepositoryStatus,
)


def _timestamp_text(value: object) -> str:
    isoformat = getattr(value, "isoformat", None)
    return str(isoformat()) if callable(isoformat) else str(value)


class PostgresConfirmedDataRepository:
    """Future-central adapter; it is not wired into the current HTTP runtime."""

    def __init__(self, dsn: str, *, environment: str) -> None:
        self._bootstrap = PostgresRepositoryBootstrap(dsn, environment=environment)

    def prepare(self) -> PostgresRepositoryStatus:
        return self._bootstrap.prepare()

    def list_confirmed(self, scope: ConfirmedDataScope) -> list[ConfirmedDataRow]:
        conditions = ["candidates.status = 'human_confirmed'"]
        parameters: list[str] = []
        if not scope.all_centres:
            conditions.append("candidates.centre_code = %s")
            parameters.append(str(scope.centre_code))
        if scope.subject_ref is not None:
            conditions.append("candidates.edc_subject_ref = %s")
            parameters.append(scope.subject_ref)
        if scope.event_ref is not None:
            conditions.append("candidates.edc_event_ref = %s")
            parameters.append(scope.event_ref)

        try:
            with self._bootstrap._open_connection() as connection:
                rows = connection.execute(
                    f"""
                    SELECT candidates.id, candidates.centre_code,
                           candidates.edc_subject_ref, candidates.edc_event_ref,
                           candidates.field_code, candidates.final_value,
                           candidates.unit, candidates.created_at,
                           candidates.reviewed_at, source_files.sha256 AS source_sha256,
                           candidates.origin_type, candidates.import_batch_id,
                           quality.status AS quality_status,
                           quality.rule_version AS quality_rule_version,
                           FALSE AS authority_submitted
                    FROM candidates
                    JOIN source_files ON source_files.id = candidates.source_file_id
                    LEFT JOIN LATERAL (
                        SELECT findings.status, findings.rule_version
                        FROM quality_findings AS findings
                        WHERE findings.candidate_id = candidates.id
                        ORDER BY findings.evaluated_at DESC, findings.id DESC
                        LIMIT 1
                    ) AS quality ON TRUE
                    WHERE {' AND '.join(conditions)}
                    ORDER BY candidates.created_at, candidates.sequence
                    """,
                    tuple(parameters),
                ).fetchall()
        except (psycopg.Error, TypeError, ValueError):
            raise PostgresRepositoryError("postgres_confirmed_data_unavailable") from None

        return [
            ConfirmedDataRow(
                candidate_id=str(row["id"]),
                centre_code=str(row["centre_code"]),
                edc_subject_ref=str(row["edc_subject_ref"]),
                edc_event_ref=str(row["edc_event_ref"]),
                field_code=str(row["field_code"]),
                final_value=str(row["final_value"]),
                unit=str(row["unit"]) if row["unit"] is not None else None,
                created_at=_timestamp_text(row["created_at"]),
                reviewed_at=_timestamp_text(row["reviewed_at"]),
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
