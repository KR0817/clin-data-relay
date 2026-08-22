"""PostgreSQL bootstrap and migration preflight for the future central repository."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row


LATEST_POSTGRES_SCHEMA_VERSION = 1
MIGRATION_NAMES = {1: "central_repository_bootstrap"}
MIGRATION_LOCK_ID = 0x4344524D494752
LOCAL_ENVIRONMENTS = {"development", "test"}
LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}


class PostgresConfigurationError(RuntimeError):
    """Raised when PostgreSQL configuration violates the deployment policy."""


class PostgresRepositoryError(RuntimeError):
    """Raised with a redacted code when repository preparation cannot finish."""


@dataclass(frozen=True)
class PostgresRepositoryStatus:
    backend: Literal["postgresql"]
    server_major: int
    schema_version: int
    migration_count: int
    clinical_data_ready: bool = False

    def public_payload(self) -> dict[str, object]:
        """Return capability metadata without connection or credential material."""

        return {
            "backend": self.backend,
            "server_major": self.server_major,
            "schema_version": self.schema_version,
            "migration_count": self.migration_count,
            "clinical_data_ready": self.clinical_data_ready,
        }


def _all_targets_are_local(parameters: dict[str, str]) -> bool:
    target_value = parameters.get("hostaddr") or parameters.get("host", "")
    targets = [target.strip().lower() for target in target_value.split(",")]
    return all(target in LOCAL_HOSTS or target.startswith("/") for target in targets)


class PostgresRepositoryBootstrap:
    """Prepare and inspect the non-clinical PostgreSQL migration ledger."""

    def __init__(self, dsn: str, *, environment: str) -> None:
        self.environment = environment.strip().lower()
        if not dsn.strip():
            raise PostgresConfigurationError("postgres_dsn_required")
        try:
            parameters = conninfo_to_dict(dsn)
        except (psycopg.Error, ValueError):
            raise PostgresConfigurationError("postgres_dsn_invalid") from None

        sslmode = parameters.get("sslmode", "prefer").lower()
        if self.environment not in LOCAL_ENVIRONMENTS and sslmode != "verify-full":
            raise PostgresConfigurationError("postgres_tls_verify_full_required")
        if sslmode != "verify-full" and not _all_targets_are_local(parameters):
            raise PostgresConfigurationError("postgres_nonlocal_unverified_tls_forbidden")
        self._dsn = dsn

    @classmethod
    def from_environment(cls) -> "PostgresRepositoryBootstrap":
        """Build from runtime secrets without returning or logging their values."""

        return cls(
            os.getenv("COMPANION_POSTGRES_DSN", ""),
            environment=os.getenv("COMPANION_ENV", "development"),
        )

    def prepare(self) -> PostgresRepositoryStatus:
        """Apply the bootstrap migration once and return redacted capability state."""

        try:
            with psycopg.connect(self._dsn, connect_timeout=5, row_factory=dict_row) as connection:
                server_row = connection.execute("SHOW server_version_num").fetchone()
                if server_row is None:
                    raise PostgresRepositoryError("postgres_server_version_unavailable")
                server_version_num = int(server_row["server_version_num"])
                if server_version_num < 160000:
                    raise PostgresRepositoryError("postgres_server_version_unsupported")

                connection.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK_ID,))
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS companion_schema_migrations (
                        version INTEGER PRIMARY KEY CHECK (version > 0),
                        name TEXT NOT NULL UNIQUE,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                rows = connection.execute(
                    "SELECT version, name FROM companion_schema_migrations ORDER BY version"
                ).fetchall()
                for row in rows:
                    version = int(row["version"])
                    if version > LATEST_POSTGRES_SCHEMA_VERSION:
                        raise PostgresRepositoryError("postgres_schema_too_new")
                    if MIGRATION_NAMES.get(version) != row["name"]:
                        raise PostgresRepositoryError("postgres_migration_ledger_invalid")

                if not rows:
                    connection.execute(
                        "INSERT INTO companion_schema_migrations (version, name) VALUES (%s, %s)",
                        (LATEST_POSTGRES_SCHEMA_VERSION, MIGRATION_NAMES[LATEST_POSTGRES_SCHEMA_VERSION]),
                    )
                    rows = [{"version": 1, "name": MIGRATION_NAMES[1]}]

                return PostgresRepositoryStatus(
                    backend="postgresql",
                    server_major=server_version_num // 10000,
                    schema_version=max(int(row["version"]) for row in rows),
                    migration_count=len(rows),
                )
        except PostgresRepositoryError:
            raise
        except (psycopg.Error, TypeError, ValueError):
            raise PostgresRepositoryError("postgres_repository_unavailable") from None
