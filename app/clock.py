"""UTC timestamp helpers shared by persistence and workflow orchestration."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp suitable for audit fields."""

    return datetime.now(UTC).isoformat()
