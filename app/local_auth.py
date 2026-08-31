from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.clock import utc_now
from app.persistence import Database
from app.security import password_hash, verify_password


LOGIN_ROLES = frozenset(
    {
        "site_investigator",
        "principal_investigator",
        "central_data_manager",
        "monitor",
        "auditor",
    }
)


@dataclass(frozen=True)
class LocalUser:
    id: str
    username: str
    centre_code: str | None
    role: str


@dataclass(frozen=True)
class LocalLoginSession:
    token: str
    user: LocalUser


def resolve_local_session(database: Database, token: str) -> LocalUser | None:
    """Resolve a valid local bearer session without exposing SQL to the HTTP layer."""

    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT users.id, users.username, users.centre_code, users.role
            FROM sessions JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ? AND sessions.expires_at > ? AND users.active = 1
            """,
            (token, utc_now()),
        ).fetchone()
    if row is None or row["role"] not in LOGIN_ROLES:
        return None
    return LocalUser(
        id=row["id"],
        username=row["username"],
        centre_code=row["centre_code"],
        role=row["role"],
    )


def authenticate_local_user(
    database: Database,
    *,
    username: str,
    password: str,
    environment: str,
    centre_profile_present: bool,
) -> LocalLoginSession | None:
    """Authenticate one local account and create its session atomically."""

    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT id, username, password_hash, centre_code, role, credential_kind
            FROM users WHERE username = ? AND active = 1
            """,
            (username,),
        ).fetchone()
        legacy_demo_allowed = bool(
            row is not None
            and row["credential_kind"] == "legacy_demo"
            and environment in {"test", "development", "portable_synthetic"}
            and not centre_profile_present
        )
        if (
            row is None
            or row["role"] not in LOGIN_ROLES
            or not verify_password(
                password,
                row["password_hash"],
                allow_legacy_demo=legacy_demo_allowed,
            )
        ):
            return None
        if legacy_demo_allowed:
            connection.execute(
                "UPDATE users SET password_hash = ?, credential_kind = 'current' WHERE id = ?",
                (password_hash(password), row["id"]),
            )
            database.append_audit_event(
                connection,
                candidate_id=None,
                centre_code=row["centre_code"] or "CENTRAL",
                event_type="credential_hash_upgraded",
                actor_username=row["username"],
                details={"from": "legacy_demo", "to": "scrypt"},
            )
        token = secrets.token_urlsafe(32)
        expires_at = (datetime.now(UTC) + timedelta(hours=8)).isoformat()
        connection.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, row["id"], expires_at),
        )
        user = LocalUser(
            id=row["id"],
            username=row["username"],
            centre_code=row["centre_code"],
            role=row["role"],
        )
    return LocalLoginSession(token=token, user=user)
