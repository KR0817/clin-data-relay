"""PostgreSQL sessions created after institutional identity authorization."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import psycopg

from app.audit_chain import ChainVerification
from app.institutional_identity import (
    InstitutionalIdentityError,
    InstitutionalUser,
    MAX_AUTHENTICATION_AGE,
    StudyMembership,
    VerifiedInstitutionalPrincipal,
    authorize_institutional_principal,
    institutional_principal_id,
)
from app.postgres_audit import (
    append_audit_event,
    lock_audit_chain,
    verify_postgres_audit_chain,
)
from app.postgres_repository import PostgresRepositoryBootstrap, PostgresRepositoryStatus


SESSION_TOKEN_RE = re.compile(r"^cdrs_[A-Za-z0-9_-]{43}$")
MAX_SESSION_LIFETIME = MAX_AUTHENTICATION_AGE


class InstitutionalSessionRepositoryError(RuntimeError):
    """Stable fail-closed institutional-session error."""


@dataclass(frozen=True)
class InstitutionalSession:
    token: str = field(repr=False)
    user: InstitutionalUser
    issued_at: datetime
    expires_at: datetime


def _validated_time(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise InstitutionalSessionRepositoryError("institutional_session_time_invalid")
    return value.astimezone(UTC)


def _token_digest(token: object) -> str | None:
    if not isinstance(token, str) or not SESSION_TOKEN_RE.fullmatch(token):
        return None
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _membership(row: dict[str, object]) -> StudyMembership:
    return StudyMembership(
        provider_id=str(row["provider_id"]),
        principal_id=str(row["principal_id"]),
        role=str(row["role"]),
        centre_code=str(row["centre_code"]) if row["centre_code"] is not None else None,
        active=bool(row["active"]),
        valid_from=row["valid_from"],
        expires_at=row["membership_expires_at"],
    )


class PostgresInstitutionalSessionRepository:
    """Issue and resolve digest-backed sessions for verified principals."""

    def __init__(self, dsn: str, *, environment: str) -> None:
        self._bootstrap = PostgresRepositoryBootstrap(dsn, environment=environment)

    def prepare(self) -> PostgresRepositoryStatus:
        return self._bootstrap.prepare()

    def create_session(
        self,
        principal: VerifiedInstitutionalPrincipal,
        *,
        issued_at: datetime,
    ) -> InstitutionalSession:
        issued = _validated_time(issued_at)
        principal_id = institutional_principal_id(principal)
        session_id = str(uuid4())
        token = f"cdrs_{secrets.token_urlsafe(32)}"
        digest = _token_digest(token)
        if digest is None:
            raise InstitutionalSessionRepositoryError("institutional_session_token_invalid")
        try:
            with self._bootstrap._open_connection() as connection:
                lock_audit_chain(connection)
                row = connection.execute(
                    """
                    SELECT id AS membership_id, provider_id, principal_id, role,
                           centre_code, active, valid_from,
                           expires_at AS membership_expires_at
                    FROM study_memberships
                    WHERE provider_id = %s AND principal_id = %s AND active
                    FOR SHARE
                    """,
                    (principal.provider_id, principal_id),
                ).fetchone()
                if row is None:
                    raise InstitutionalSessionRepositoryError(
                        "institutional_session_membership_required"
                    )
                membership = _membership(row)
                user = authorize_institutional_principal(
                    principal,
                    membership,
                    now=issued,
                )
                expires_at = min(
                    issued + MAX_SESSION_LIFETIME,
                    principal.authenticated_at + MAX_SESSION_LIFETIME,
                    membership.expires_at,
                )
                if expires_at <= issued:
                    raise InstitutionalSessionRepositoryError(
                        "institutional_session_lifetime_exhausted"
                    )
                connection.execute(
                    """
                    INSERT INTO institutional_sessions (
                        id, token_sha256, membership_id, username,
                        issued_at, expires_at, revoked_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, NULL)
                    """,
                    (
                        session_id,
                        digest,
                        row["membership_id"],
                        principal.username,
                        issued,
                        expires_at,
                    ),
                )
                append_audit_event(
                    connection,
                    event_id=str(uuid4()),
                    candidate_id=None,
                    centre_code=membership.centre_code or "CENTRAL",
                    event_type="institutional_session_created",
                    actor_username=principal.username,
                    created_at=issued,
                    details={
                        "session_id": session_id,
                        "membership_id": str(row["membership_id"]),
                        "expires_at": expires_at.isoformat(),
                    },
                )
            return InstitutionalSession(
                token=token,
                user=user,
                issued_at=issued,
                expires_at=expires_at,
            )
        except InstitutionalSessionRepositoryError:
            raise
        except InstitutionalIdentityError as error:
            raise InstitutionalSessionRepositoryError(str(error)) from None
        except (psycopg.Error, TypeError, ValueError):
            raise InstitutionalSessionRepositoryError(
                "institutional_session_repository_unavailable"
            ) from None

    def resolve_session(
        self,
        token: str,
        *,
        now: datetime,
    ) -> InstitutionalUser | None:
        resolved_now = _validated_time(now)
        digest = _token_digest(token)
        if digest is None:
            return None
        try:
            with self._bootstrap._open_connection() as connection:
                row = connection.execute(
                    """
                    SELECT sessions.username, memberships.principal_id,
                           memberships.role, memberships.centre_code
                    FROM institutional_sessions AS sessions
                    JOIN study_memberships AS memberships
                      ON memberships.id = sessions.membership_id
                    WHERE sessions.token_sha256 = %s
                      AND sessions.revoked_at IS NULL
                      AND sessions.expires_at > %s
                      AND memberships.active
                      AND memberships.valid_from <= %s
                      AND memberships.expires_at > %s
                    """,
                    (digest, resolved_now, resolved_now, resolved_now),
                ).fetchone()
            if row is None:
                return None
            return InstitutionalUser(
                id=str(row["principal_id"]),
                username=str(row["username"]),
                role=str(row["role"]),
                centre_code=(
                    str(row["centre_code"]) if row["centre_code"] is not None else None
                ),
            )
        except (psycopg.Error, TypeError, ValueError):
            raise InstitutionalSessionRepositoryError(
                "institutional_session_repository_unavailable"
            ) from None

    def revoke_session(
        self,
        token: str,
        *,
        revoked_at: datetime,
    ) -> bool:
        occurred_at = _validated_time(revoked_at)
        digest = _token_digest(token)
        if digest is None:
            return False
        try:
            with self._bootstrap._open_connection() as connection:
                lock_audit_chain(connection)
                row = connection.execute(
                    """
                    SELECT sessions.id AS session_id, sessions.membership_id,
                           sessions.username, sessions.issued_at, sessions.revoked_at,
                           memberships.centre_code
                    FROM institutional_sessions AS sessions
                    JOIN study_memberships AS memberships
                      ON memberships.id = sessions.membership_id
                    WHERE sessions.token_sha256 = %s
                    FOR UPDATE OF sessions
                    """,
                    (digest,),
                ).fetchone()
                if row is None:
                    return False
                if row["revoked_at"] is not None:
                    return True
                if occurred_at < row["issued_at"]:
                    raise InstitutionalSessionRepositoryError(
                        "institutional_session_time_invalid"
                    )
                connection.execute(
                    """
                    UPDATE institutional_sessions
                    SET revoked_at = %s
                    WHERE id = %s
                    """,
                    (occurred_at, row["session_id"]),
                )
                append_audit_event(
                    connection,
                    event_id=str(uuid4()),
                    candidate_id=None,
                    centre_code=str(row["centre_code"] or "CENTRAL"),
                    event_type="institutional_session_revoked",
                    actor_username=str(row["username"]),
                    created_at=occurred_at,
                    details={
                        "session_id": str(row["session_id"]),
                        "membership_id": str(row["membership_id"]),
                    },
                )
                return True
        except InstitutionalSessionRepositoryError:
            raise
        except (psycopg.Error, TypeError, ValueError):
            raise InstitutionalSessionRepositoryError(
                "institutional_session_repository_unavailable"
            ) from None

    def verify_audit_chain(self) -> ChainVerification:
        try:
            with self._bootstrap._open_connection() as connection:
                return verify_postgres_audit_chain(connection)
        except (psycopg.Error, TypeError, ValueError):
            raise InstitutionalSessionRepositoryError(
                "institutional_session_repository_unavailable"
            ) from None
