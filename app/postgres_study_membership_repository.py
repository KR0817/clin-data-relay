"""PostgreSQL lifecycle repository for application-owned study authorization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import psycopg

from app.audit_chain import ChainVerification
from app.institutional_identity import (
    InstitutionalIdentityError,
    StudyMembership,
    VerifiedInstitutionalPrincipal,
    institutional_principal_id,
)
from app.postgres_audit import (
    append_audit_event,
    lock_audit_chain,
    verify_postgres_audit_chain,
)
from app.postgres_repository import PostgresRepositoryBootstrap, PostgresRepositoryStatus


class StudyMembershipRepositoryError(RuntimeError):
    """Stable fail-closed membership repository error."""


@dataclass(frozen=True)
class StudyMembershipRecord:
    id: str
    membership: StudyMembership
    created_by: str
    created_at: datetime
    deactivated_by: str | None
    deactivated_at: datetime | None
    deactivation_reason: str | None

    @property
    def active(self) -> bool:
        return self.membership.active


def _validated_actor(value: object) -> str:
    if not (
        isinstance(value, str)
        and 3 <= len(value) <= 320
        and all(not character.isspace() and 32 < ord(character) < 127 for character in value)
    ):
        raise StudyMembershipRepositoryError("study_membership_actor_invalid")
    return value


def _validated_reason(value: object) -> str:
    if not isinstance(value, str):
        raise StudyMembershipRepositoryError("study_membership_reason_invalid")
    reason = value.strip()
    if not 3 <= len(reason) <= 500 or any(ord(character) < 32 for character in reason):
        raise StudyMembershipRepositoryError("study_membership_reason_invalid")
    return reason


def _validated_incident_reference(value: object) -> str:
    if not isinstance(value, str):
        raise StudyMembershipRepositoryError("study_membership_emergency_invalid")
    reference = value.strip()
    if not 3 <= len(reference) <= 200 or any(
        ord(character) < 32 for character in reference
    ):
        raise StudyMembershipRepositoryError("study_membership_emergency_invalid")
    return reference


def _validated_time(value: object, error_code: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise StudyMembershipRepositoryError(error_code)
    return value.astimezone(UTC)


def _record(row: dict[str, object]) -> StudyMembershipRecord:
    membership = StudyMembership(
        provider_id=str(row["provider_id"]),
        principal_id=str(row["principal_id"]),
        role=str(row["role"]),
        centre_code=str(row["centre_code"]) if row["centre_code"] is not None else None,
        active=bool(row["active"]),
        valid_from=row["valid_from"],
        expires_at=row["expires_at"],
    )
    return StudyMembershipRecord(
        id=str(row["id"]),
        membership=membership,
        created_by=str(row["created_by"]),
        created_at=row["created_at"],
        deactivated_by=(
            str(row["deactivated_by"]) if row["deactivated_by"] is not None else None
        ),
        deactivated_at=row["deactivated_at"],
        deactivation_reason=(
            str(row["deactivation_reason"])
            if row["deactivation_reason"] is not None
            else None
        ),
    )


_MEMBERSHIP_COLUMNS = """
    id, provider_id, principal_id, role, centre_code, active,
    valid_from, expires_at, created_by, created_at,
    deactivated_by, deactivated_at, deactivation_reason
"""


class PostgresStudyMembershipRepository:
    """Persist one active study authorization per pseudonymous principal."""

    def __init__(self, dsn: str, *, environment: str) -> None:
        self._bootstrap = PostgresRepositoryBootstrap(dsn, environment=environment)

    def prepare(self) -> PostgresRepositoryStatus:
        return self._bootstrap.prepare()

    @staticmethod
    def _insert_grant(
        connection: object,
        membership: StudyMembership,
        *,
        membership_id: str,
        actor: str,
        created_at: datetime,
        bootstrap: bool,
    ) -> StudyMembershipRecord:
        row = connection.execute(
            f"""
            INSERT INTO study_memberships ({_MEMBERSHIP_COLUMNS})
            VALUES (%s, %s, %s, %s, %s, TRUE, %s, %s, %s, %s,
                    NULL, NULL, NULL)
            RETURNING {_MEMBERSHIP_COLUMNS}
            """,
            (
                membership_id,
                membership.provider_id,
                membership.principal_id,
                membership.role,
                membership.centre_code,
                membership.valid_from,
                membership.expires_at,
                actor,
                created_at,
            ),
        ).fetchone()
        details: dict[str, object] = {
            "membership_id": membership_id,
            "provider_id": membership.provider_id,
            "role": membership.role,
            "centre_code": membership.centre_code,
        }
        if bootstrap:
            details["bootstrap"] = True
        append_audit_event(
            connection,
            event_id=str(uuid4()),
            candidate_id=None,
            centre_code=membership.centre_code or "CENTRAL",
            event_type="study_membership_granted",
            actor_username=actor,
            created_at=created_at,
            details=details,
        )
        return _record(row)

    def grant(
        self,
        membership: StudyMembership,
        *,
        actor_username: str,
        granted_at: datetime,
    ) -> StudyMembershipRecord:
        actor = _validated_actor(actor_username)
        created_at = _validated_time(granted_at, "study_membership_time_invalid")
        if not membership.active or membership.expires_at <= created_at:
            raise StudyMembershipRepositoryError("study_membership_grant_invalid")
        membership_id = str(uuid4())
        try:
            with self._bootstrap._open_connection() as connection:
                lock_audit_chain(connection)
                return self._insert_grant(
                    connection,
                    membership,
                    membership_id=membership_id,
                    actor=actor,
                    created_at=created_at,
                    bootstrap=False,
                )
        except psycopg.errors.UniqueViolation:
            raise StudyMembershipRepositoryError("study_membership_active_exists") from None
        except (psycopg.Error, InstitutionalIdentityError, TypeError, ValueError):
            raise StudyMembershipRepositoryError("study_membership_repository_unavailable") from None

    def bootstrap_first_central_data_manager(
        self,
        provider_id: str,
        principal_id: str,
        *,
        actor_username: str,
        granted_at: datetime,
        expires_at: datetime,
    ) -> StudyMembershipRecord:
        actor = _validated_actor(actor_username)
        created_at = _validated_time(granted_at, "study_membership_time_invalid")
        expiry = _validated_time(expires_at, "study_membership_time_invalid")
        try:
            membership = StudyMembership(
                provider_id=provider_id,
                principal_id=principal_id,
                role="central_data_manager",
                centre_code=None,
                active=True,
                valid_from=created_at,
                expires_at=expiry,
            )
        except (InstitutionalIdentityError, TypeError, ValueError):
            raise StudyMembershipRepositoryError(
                "study_membership_bootstrap_invalid"
            ) from None
        membership_id = str(uuid4())
        try:
            with self._bootstrap._open_connection() as connection:
                lock_audit_chain(connection)
                disallowed = connection.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM study_memberships AS memberships
                        WHERE memberships.active
                           OR memberships.role <> 'central_data_manager'
                           OR memberships.centre_code IS NOT NULL
                           OR NOT EXISTS (
                               SELECT 1
                               FROM audit_events AS events
                               WHERE events.event_type = 'study_membership_granted'
                                 AND events.details_json ->> 'membership_id' = memberships.id
                                 AND events.details_json ->> 'bootstrap' = 'true'
                           )
                           OR NOT EXISTS (
                               SELECT 1
                               FROM audit_events AS events
                               WHERE events.event_type = 'study_membership_bootstrap_rolled_back'
                                 AND events.details_json ->> 'membership_id' = memberships.id
                           )
                    ) AS invalid_membership_history,
                    EXISTS (SELECT 1 FROM institutional_sessions) AS session_history
                    """
                ).fetchone()
                if bool(disallowed["invalid_membership_history"]) or bool(
                    disallowed["session_history"]
                ):
                    raise StudyMembershipRepositoryError(
                        "study_membership_bootstrap_closed"
                    )
                return self._insert_grant(
                    connection,
                    membership,
                    membership_id=membership_id,
                    actor=actor,
                    created_at=created_at,
                    bootstrap=True,
                )
        except StudyMembershipRepositoryError:
            raise
        except psycopg.errors.UniqueViolation:
            raise StudyMembershipRepositoryError(
                "study_membership_bootstrap_closed"
            ) from None
        except (psycopg.Error, InstitutionalIdentityError, TypeError, ValueError):
            raise StudyMembershipRepositoryError(
                "study_membership_repository_unavailable"
            ) from None

    def find_active(
        self,
        principal: VerifiedInstitutionalPrincipal,
    ) -> StudyMembershipRecord | None:
        principal_id = institutional_principal_id(principal)
        try:
            with self._bootstrap._open_connection() as connection:
                row = connection.execute(
                    f"""
                    SELECT {_MEMBERSHIP_COLUMNS}
                    FROM study_memberships
                    WHERE principal_id = %s AND provider_id = %s AND active
                    """,
                    (principal_id, principal.provider_id),
                ).fetchone()
            return _record(row) if row is not None else None
        except (psycopg.Error, InstitutionalIdentityError, TypeError, ValueError):
            raise StudyMembershipRepositoryError("study_membership_repository_unavailable") from None

    def deactivate(
        self,
        membership_id: str,
        *,
        actor_username: str,
        reason: str,
        deactivated_at: datetime,
    ) -> StudyMembershipRecord:
        actor = _validated_actor(actor_username)
        bounded_reason = _validated_reason(reason)
        occurred_at = _validated_time(deactivated_at, "study_membership_time_invalid")
        if not isinstance(membership_id, str) or not 1 <= len(membership_id) <= 200:
            raise StudyMembershipRepositoryError("study_membership_id_invalid")
        try:
            with self._bootstrap._open_connection() as connection:
                lock_audit_chain(connection)
                existing = connection.execute(
                    f"""
                    SELECT {_MEMBERSHIP_COLUMNS}
                    FROM study_memberships
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (membership_id,),
                ).fetchone()
                if existing is None:
                    raise StudyMembershipRepositoryError("study_membership_not_found")
                if not bool(existing["active"]):
                    return _record(existing)
                if occurred_at < existing["created_at"]:
                    raise StudyMembershipRepositoryError("study_membership_time_invalid")
                row = connection.execute(
                    f"""
                    UPDATE study_memberships
                    SET active = FALSE, deactivated_by = %s, deactivated_at = %s,
                        deactivation_reason = %s
                    WHERE id = %s
                    RETURNING {_MEMBERSHIP_COLUMNS}
                    """,
                    (actor, occurred_at, bounded_reason, membership_id),
                ).fetchone()
                append_audit_event(
                    connection,
                    event_id=str(uuid4()),
                    candidate_id=None,
                    centre_code=str(existing["centre_code"] or "CENTRAL"),
                    event_type="study_membership_deactivated",
                    actor_username=actor,
                    created_at=occurred_at,
                    details={
                        "membership_id": membership_id,
                        "provider_id": str(existing["provider_id"]),
                        "role": str(existing["role"]),
                        "centre_code": existing["centre_code"],
                        "reason": bounded_reason,
                    },
                )
                return _record(row)
        except StudyMembershipRepositoryError:
            raise
        except (psycopg.Error, InstitutionalIdentityError, TypeError, ValueError):
            raise StudyMembershipRepositoryError("study_membership_repository_unavailable") from None

    def rollback_unused_central_data_manager_bootstrap(
        self,
        membership_id: str,
        *,
        actor_username: str,
        reason: str,
        rolled_back_at: datetime,
    ) -> StudyMembershipRecord:
        actor = _validated_actor(actor_username)
        bounded_reason = _validated_reason(reason)
        occurred_at = _validated_time(rolled_back_at, "study_membership_time_invalid")
        if not isinstance(membership_id, str) or not 1 <= len(membership_id) <= 200:
            raise StudyMembershipRepositoryError("study_membership_bootstrap_invalid")
        try:
            with self._bootstrap._open_connection() as connection:
                lock_audit_chain(connection)
                existing = connection.execute(
                    f"""
                    SELECT {_MEMBERSHIP_COLUMNS}
                    FROM study_memberships
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (membership_id,),
                ).fetchone()
                if existing is None:
                    raise StudyMembershipRepositoryError(
                        "study_membership_bootstrap_not_found"
                    )
                bootstrap_audit = connection.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM audit_events
                        WHERE event_type = 'study_membership_granted'
                          AND details_json ->> 'membership_id' = %s
                          AND details_json ->> 'bootstrap' = 'true'
                    ) AS grant_present,
                    EXISTS (
                        SELECT 1
                        FROM audit_events
                        WHERE event_type = 'study_membership_bootstrap_rolled_back'
                          AND details_json ->> 'membership_id' = %s
                    ) AS rollback_present
                    """,
                    (membership_id, membership_id),
                ).fetchone()
                if (
                    str(existing["role"]) != "central_data_manager"
                    or existing["centre_code"] is not None
                    or not bool(bootstrap_audit["grant_present"])
                ):
                    raise StudyMembershipRepositoryError(
                        "study_membership_bootstrap_invalid"
                    )
                used = connection.execute(
                    """
                    SELECT EXISTS (SELECT 1 FROM institutional_sessions) AS present
                    """
                ).fetchone()
                if bool(used["present"]):
                    raise StudyMembershipRepositoryError(
                        "study_membership_bootstrap_already_used"
                    )
                if not bool(existing["active"]):
                    if not bool(bootstrap_audit["rollback_present"]):
                        raise StudyMembershipRepositoryError(
                            "study_membership_bootstrap_invalid"
                        )
                    return _record(existing)
                if bool(bootstrap_audit["rollback_present"]):
                    raise StudyMembershipRepositoryError(
                        "study_membership_bootstrap_invalid"
                    )
                if occurred_at < existing["created_at"]:
                    raise StudyMembershipRepositoryError("study_membership_time_invalid")
                row = connection.execute(
                    f"""
                    UPDATE study_memberships
                    SET active = FALSE, deactivated_by = %s, deactivated_at = %s,
                        deactivation_reason = %s
                    WHERE id = %s
                    RETURNING {_MEMBERSHIP_COLUMNS}
                    """,
                    (actor, occurred_at, bounded_reason, membership_id),
                ).fetchone()
                append_audit_event(
                    connection,
                    event_id=str(uuid4()),
                    candidate_id=None,
                    centre_code="CENTRAL",
                    event_type="study_membership_bootstrap_rolled_back",
                    actor_username=actor,
                    created_at=occurred_at,
                    details={
                        "membership_id": membership_id,
                        "provider_id": str(existing["provider_id"]),
                        "role": "central_data_manager",
                        "reason": bounded_reason,
                    },
                )
                return _record(row)
        except StudyMembershipRepositoryError:
            raise
        except (psycopg.Error, InstitutionalIdentityError, TypeError, ValueError):
            raise StudyMembershipRepositoryError(
                "study_membership_repository_unavailable"
            ) from None

    def emergency_deactivate_bootstrap_central_data_manager(
        self,
        membership_id: str,
        *,
        actor_username: str,
        incident_reference: str,
        reason: str,
        deactivated_at: datetime,
    ) -> StudyMembershipRecord:
        """Contain a used bootstrap grant without deleting session evidence."""
        actor = _validated_actor(actor_username)
        reference = _validated_incident_reference(incident_reference)
        bounded_reason = _validated_reason(reason)
        occurred_at = _validated_time(deactivated_at, "study_membership_time_invalid")
        if not isinstance(membership_id, str) or not 1 <= len(membership_id) <= 200:
            raise StudyMembershipRepositoryError("study_membership_emergency_invalid")
        try:
            with self._bootstrap._open_connection() as connection:
                lock_audit_chain(connection)
                existing = connection.execute(
                    f"""
                    SELECT {_MEMBERSHIP_COLUMNS}
                    FROM study_memberships
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (membership_id,),
                ).fetchone()
                if existing is None:
                    raise StudyMembershipRepositoryError(
                        "study_membership_emergency_not_found"
                    )
                bootstrap_audit = connection.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM audit_events
                        WHERE event_type = 'study_membership_granted'
                          AND details_json ->> 'membership_id' = %s
                          AND details_json ->> 'bootstrap' = 'true'
                    ) AS grant_present
                    """,
                    (membership_id,),
                ).fetchone()
                if (
                    str(existing["role"]) != "central_data_manager"
                    or existing["centre_code"] is not None
                    or not bool(bootstrap_audit["grant_present"])
                ):
                    raise StudyMembershipRepositoryError(
                        "study_membership_emergency_invalid"
                    )
                if not bool(existing["active"]):
                    raise StudyMembershipRepositoryError(
                        "study_membership_emergency_already_inactive"
                    )
                if occurred_at < existing["created_at"]:
                    raise StudyMembershipRepositoryError("study_membership_time_invalid")
                row = connection.execute(
                    f"""
                    UPDATE study_memberships
                    SET active = FALSE, deactivated_by = %s, deactivated_at = %s,
                        deactivation_reason = %s
                    WHERE id = %s
                    RETURNING {_MEMBERSHIP_COLUMNS}
                    """,
                    (actor, occurred_at, bounded_reason, membership_id),
                ).fetchone()
                append_audit_event(
                    connection,
                    event_id=str(uuid4()),
                    candidate_id=None,
                    centre_code="CENTRAL",
                    event_type="study_membership_emergency_deactivated",
                    actor_username=actor,
                    created_at=occurred_at,
                    details={
                        "membership_id": membership_id,
                        "provider_id": str(existing["provider_id"]),
                        "role": "central_data_manager",
                        "incident_reference": reference,
                        "reason": bounded_reason,
                    },
                )
                return _record(row)
        except StudyMembershipRepositoryError:
            raise
        except (psycopg.Error, InstitutionalIdentityError, TypeError, ValueError):
            raise StudyMembershipRepositoryError(
                "study_membership_repository_unavailable"
            ) from None

    def verify_audit_chain(self) -> ChainVerification:
        try:
            with self._bootstrap._open_connection() as connection:
                return verify_postgres_audit_chain(connection)
        except (psycopg.Error, TypeError, ValueError):
            raise StudyMembershipRepositoryError("study_membership_repository_unavailable") from None
