"""Shared PostgreSQL writer and verifier for the global audit hash chain."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from psycopg.types.json import Jsonb

from app.audit_chain import (
    GENESIS_PREV_HASH,
    ChainVerification,
    compute_event_hash,
    event_payload,
    verify_chain,
)


AUDIT_APPEND_LOCK_ID = 0x4344524155444954


def _timestamp_text(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("audit_timestamp_invalid")
        return value.astimezone(UTC).isoformat()
    isoformat = getattr(value, "isoformat", None)
    return str(isoformat()) if callable(isoformat) else str(value)


def _timestamp_value(value: datetime | str) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("audit_timestamp_invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("audit_timestamp_invalid")
    return parsed.astimezone(UTC)


def lock_audit_chain(connection: object) -> None:
    """Serialize writers before they read and extend the global chain tail."""
    connection.execute("SELECT pg_advisory_xact_lock(%s)", (AUDIT_APPEND_LOCK_ID,))


def audit_head(connection: object) -> str:
    row = connection.execute(
        "SELECT event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    return str(row["event_hash"]) if row is not None else GENESIS_PREV_HASH


def append_audit_event(
    connection: object,
    *,
    event_id: str,
    candidate_id: str | None,
    centre_code: str,
    event_type: str,
    actor_username: str,
    created_at: datetime | str,
    details: Mapping[str, object],
) -> str:
    """Append after the caller has acquired the transaction audit lock."""
    previous = audit_head(connection)
    created_at_value = _timestamp_value(created_at)
    created_at_text = _timestamp_text(created_at_value)
    payload = event_payload(
        event_id=event_id,
        candidate_id=candidate_id,
        centre_code=centre_code,
        event_type=event_type,
        actor_username=actor_username,
        created_at=created_at_text,
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
            centre_code,
            event_type,
            actor_username,
            created_at_value,
            Jsonb(dict(details)),
            previous,
            event_hash,
        ),
    )
    return event_hash


def verify_postgres_audit_chain(connection: object) -> ChainVerification:
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
                candidate_id=(
                    str(row["candidate_id"])
                    if row["candidate_id"] is not None
                    else None
                ),
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
