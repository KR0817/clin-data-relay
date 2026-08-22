"""PostgreSQL bootstrap and migration preflight for the future central repository."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from app.package_import_repository import PackageImportAttempt, PackageImportReceipt


LATEST_POSTGRES_SCHEMA_VERSION = 6
MIGRATION_NAMES = {
    1: "central_repository_bootstrap",
    2: "package_import_ledger",
    3: "reviewed_package_clinical_import",
    4: "confirmed_data_read_index",
    5: "study_membership_authorization",
    6: "institutional_sessions",
}
MIGRATION_STATEMENTS = {
    1: (),
    2: (
        """
        CREATE TABLE IF NOT EXISTS offline_package_imports (
            id TEXT PRIMARY KEY,
            package_id TEXT NOT NULL UNIQUE CHECK (length(package_id) BETWEEN 1 AND 200),
            package_sha256 TEXT NOT NULL UNIQUE
                CHECK (package_sha256 ~ '^[a-f0-9]{64}$'),
            centre_code TEXT NOT NULL CHECK (length(centre_code) BETWEEN 1 AND 100),
            record_count INTEGER NOT NULL CHECK (record_count >= 0),
            created_by TEXT NOT NULL CHECK (length(created_by) BETWEEN 1 AND 320),
            created_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS offline_package_import_logs (
            id TEXT PRIMARY KEY,
            package_sha256 TEXT
                CHECK (package_sha256 IS NULL OR package_sha256 ~ '^[a-f0-9]{64}$'),
            package_id TEXT CHECK (package_id IS NULL OR length(package_id) <= 200),
            centre_code TEXT CHECK (centre_code IS NULL OR length(centre_code) <= 100),
            source_filename TEXT NOT NULL CHECK (length(source_filename) BETWEEN 1 AND 200),
            dictionary_id TEXT CHECK (dictionary_id IS NULL OR length(dictionary_id) <= 200),
            dictionary_version TEXT
                CHECK (dictionary_version IS NULL OR length(dictionary_version) <= 100),
            result TEXT NOT NULL CHECK (result IN ('imported', 'duplicate', 'failed')),
            error_code TEXT CHECK (error_code IS NULL OR length(error_code) <= 120),
            error_detail TEXT CHECK (error_detail IS NULL OR length(error_detail) <= 500),
            record_count INTEGER NOT NULL DEFAULT 0 CHECK (record_count >= 0),
            created_count INTEGER NOT NULL DEFAULT 0 CHECK (created_count >= 0),
            duplicate_count INTEGER NOT NULL DEFAULT 0 CHECK (duplicate_count >= 0),
            created_by TEXT NOT NULL CHECK (length(created_by) BETWEEN 1 AND 320),
            created_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_offline_package_import_logs_created_at
        ON offline_package_import_logs (created_at DESC)
        """,
    ),
    3: (
        """
        CREATE TABLE IF NOT EXISTS source_files (
            id TEXT PRIMARY KEY,
            centre_code TEXT NOT NULL CHECK (length(centre_code) BETWEEN 1 AND 100),
            source_filename TEXT NOT NULL CHECK (length(source_filename) BETWEEN 1 AND 200),
            sha256 TEXT NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
            mime_type TEXT NOT NULL,
            storage_key TEXT NOT NULL CHECK (length(storage_key) BETWEEN 1 AND 500),
            created_by TEXT NOT NULL CHECK (length(created_by) BETWEEN 1 AND 320),
            created_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS candidates (
            sequence BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
            id TEXT PRIMARY KEY,
            centre_code TEXT NOT NULL CHECK (length(centre_code) BETWEEN 1 AND 100),
            source_file_id TEXT NOT NULL REFERENCES source_files(id),
            edc_subject_ref TEXT NOT NULL CHECK (length(edc_subject_ref) BETWEEN 2 AND 64),
            edc_event_ref TEXT NOT NULL CHECK (length(edc_event_ref) BETWEEN 2 AND 64),
            field_code TEXT NOT NULL CHECK (length(field_code) BETWEEN 1 AND 64),
            proposed_value TEXT NOT NULL CHECK (length(proposed_value) BETWEEN 1 AND 200),
            unit TEXT CHECK (unit IS NULL OR length(unit) <= 100),
            final_value TEXT NOT NULL CHECK (length(final_value) BETWEEN 1 AND 200),
            status TEXT NOT NULL CHECK (status IN ('human_confirmed', 'rejected')),
            ocr_engine_version TEXT NOT NULL,
            kimi_model TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            confidence DOUBLE PRECISION NOT NULL CHECK (confidence BETWEEN 0 AND 1),
            local_ocr_value TEXT,
            local_ocr_unit TEXT,
            extraction_agreement TEXT,
            evidence_text TEXT,
            import_batch_id TEXT NOT NULL REFERENCES offline_package_imports(id),
            origin_type TEXT NOT NULL CHECK (origin_type = 'offline_package'),
            created_by TEXT NOT NULL CHECK (length(created_by) BETWEEN 1 AND 320),
            created_at TIMESTAMPTZ NOT NULL,
            reviewed_by TEXT NOT NULL,
            reviewed_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_active_value_unique
        ON candidates (
            centre_code, edc_subject_ref, edc_event_ref, field_code,
            proposed_value, COALESCE(unit, '')
        )
        WHERE status <> 'rejected'
        """,
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            sequence BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
            id TEXT PRIMARY KEY,
            candidate_id TEXT REFERENCES candidates(id),
            centre_code TEXT NOT NULL CHECK (length(centre_code) BETWEEN 1 AND 100),
            event_type TEXT NOT NULL,
            actor_username TEXT NOT NULL CHECK (length(actor_username) BETWEEN 1 AND 320),
            created_at TIMESTAMPTZ NOT NULL,
            details_json JSONB NOT NULL,
            prev_hash TEXT NOT NULL CHECK (prev_hash ~ '^[a-f0-9]{64}$'),
            event_hash TEXT NOT NULL UNIQUE CHECK (event_hash ~ '^[a-f0-9]{64}$')
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS quality_findings (
            id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL REFERENCES candidates(id),
            centre_code TEXT NOT NULL CHECK (length(centre_code) BETWEEN 1 AND 100),
            rule_version TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('PASS', 'WARN', 'BLOCK')),
            findings_json JSONB NOT NULL CHECK (jsonb_typeof(findings_json) = 'array'),
            evaluated_value TEXT NOT NULL CHECK (length(evaluated_value) BETWEEN 1 AND 200),
            evaluated_unit TEXT CHECK (evaluated_unit IS NULL OR length(evaluated_unit) <= 100),
            evaluated_by TEXT NOT NULL CHECK (length(evaluated_by) BETWEEN 1 AND 320),
            evaluated_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_quality_findings_candidate
        ON quality_findings (candidate_id, evaluated_at DESC)
        """,
    ),
    4: (
        """
        CREATE INDEX IF NOT EXISTS idx_candidates_confirmed_export_scope
        ON candidates (
            centre_code, edc_event_ref, edc_subject_ref, created_at, sequence
        )
        WHERE status = 'human_confirmed'
        """,
    ),
    5: (
        """
        CREATE TABLE IF NOT EXISTS study_memberships (
            sequence BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
            id TEXT PRIMARY KEY,
            provider_id TEXT NOT NULL
                CHECK (provider_id ~ '^[a-z][a-z0-9._-]{1,63}$'),
            principal_id TEXT NOT NULL
                CHECK (principal_id ~ '^institutional:[a-f0-9]{64}$'),
            role TEXT NOT NULL CHECK (role IN (
                'site_investigator', 'principal_investigator',
                'central_data_manager', 'monitor', 'auditor'
            )),
            centre_code TEXT,
            active BOOLEAN NOT NULL,
            valid_from TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL CHECK (expires_at > valid_from),
            created_by TEXT NOT NULL CHECK (length(created_by) BETWEEN 3 AND 320),
            created_at TIMESTAMPTZ NOT NULL,
            deactivated_by TEXT CHECK (
                deactivated_by IS NULL OR length(deactivated_by) BETWEEN 3 AND 320
            ),
            deactivated_at TIMESTAMPTZ,
            deactivation_reason TEXT CHECK (
                deactivation_reason IS NULL
                OR length(deactivation_reason) BETWEEN 3 AND 500
            ),
            CHECK (
                (role = 'site_investigator'
                 AND centre_code IS NOT NULL
                 AND centre_code ~ '^[A-Z][A-Z0-9_-]{1,31}$')
                OR (role <> 'site_investigator' AND centre_code IS NULL)
            ),
            CHECK (
                (active AND deactivated_by IS NULL AND deactivated_at IS NULL
                 AND deactivation_reason IS NULL)
                OR (NOT active AND deactivated_by IS NOT NULL
                    AND deactivated_at IS NOT NULL
                    AND deactivation_reason IS NOT NULL)
            )
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_study_memberships_one_active_principal
        ON study_memberships (principal_id)
        WHERE active
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_study_memberships_principal_lookup
        ON study_memberships (principal_id, active)
        """,
    ),
    6: (
        """
        CREATE TABLE IF NOT EXISTS institutional_sessions (
            sequence BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
            id TEXT PRIMARY KEY,
            token_sha256 TEXT NOT NULL UNIQUE
                CHECK (token_sha256 ~ '^[a-f0-9]{64}$'),
            membership_id TEXT NOT NULL REFERENCES study_memberships(id),
            username TEXT NOT NULL CHECK (length(username) BETWEEN 3 AND 320),
            issued_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL CHECK (expires_at > issued_at),
            revoked_at TIMESTAMPTZ,
            CHECK (revoked_at IS NULL OR revoked_at >= issued_at)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_institutional_sessions_membership
        ON institutional_sessions (membership_id, expires_at DESC)
        """,
    ),
}
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
        """Apply ordered migrations and return redacted capability state."""

        try:
            with self._open_connection() as connection:
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
                versions = [int(row["version"]) for row in rows]
                for row in rows:
                    version = int(row["version"])
                    if version > LATEST_POSTGRES_SCHEMA_VERSION:
                        raise PostgresRepositoryError("postgres_schema_too_new")
                    if MIGRATION_NAMES.get(version) != row["name"]:
                        raise PostgresRepositoryError("postgres_migration_ledger_invalid")
                if versions and versions != list(range(1, max(versions) + 1)):
                    raise PostgresRepositoryError("postgres_migration_ledger_invalid")

                applied_versions = set(versions)
                for version in range(1, LATEST_POSTGRES_SCHEMA_VERSION + 1):
                    if version in applied_versions:
                        continue
                    for statement in MIGRATION_STATEMENTS[version]:
                        connection.execute(statement)
                    connection.execute(
                        "INSERT INTO companion_schema_migrations (version, name) VALUES (%s, %s)",
                        (version, MIGRATION_NAMES[version]),
                    )
                rows = connection.execute(
                    "SELECT version, name FROM companion_schema_migrations ORDER BY version"
                ).fetchall()

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

    def _open_connection(self):
        return psycopg.connect(self._dsn, connect_timeout=5, row_factory=dict_row)


def _timestamp_text(value: object) -> str:
    isoformat = getattr(value, "isoformat", None)
    return str(isoformat()) if callable(isoformat) else str(value)


def _postgres_receipt(row: dict[str, object]) -> PackageImportReceipt:
    return PackageImportReceipt(
        id=str(row["id"]),
        package_id=str(row["package_id"]),
        package_sha256=str(row["package_sha256"]),
        centre_code=str(row["centre_code"]),
        record_count=int(row["record_count"]),
        created_by=str(row["created_by"]),
        created_at=_timestamp_text(row["created_at"]),
    )


def _postgres_attempt(row: dict[str, object]) -> PackageImportAttempt:
    return PackageImportAttempt(
        id=str(row["id"]),
        package_sha256=str(row["package_sha256"]) if row["package_sha256"] is not None else None,
        package_id=str(row["package_id"]) if row["package_id"] is not None else None,
        centre_code=str(row["centre_code"]) if row["centre_code"] is not None else None,
        source_filename=str(row["source_filename"]),
        dictionary_id=str(row["dictionary_id"]) if row["dictionary_id"] is not None else None,
        dictionary_version=(
            str(row["dictionary_version"]) if row["dictionary_version"] is not None else None
        ),
        result=str(row["result"]),  # type: ignore[arg-type]
        error_code=str(row["error_code"]) if row["error_code"] is not None else None,
        error_detail=str(row["error_detail"]) if row["error_detail"] is not None else None,
        record_count=int(row["record_count"]),
        created_count=int(row["created_count"]),
        duplicate_count=int(row["duplicate_count"]),
        created_by=str(row["created_by"]),
        created_at=_timestamp_text(row["created_at"]),
    )


class PostgresPackageImportRepository:
    """PostgreSQL adapter for the non-clinical package import ledger."""

    def __init__(self, dsn: str, *, environment: str) -> None:
        self._bootstrap = PostgresRepositoryBootstrap(dsn, environment=environment)

    def prepare(self) -> PostgresRepositoryStatus:
        return self._bootstrap.prepare()

    def claim(self, receipt: PackageImportReceipt) -> bool:
        try:
            with self._bootstrap._open_connection() as connection:
                return self.claim_in_connection(connection, receipt)
        except psycopg.Error:
            raise PostgresRepositoryError("postgres_package_import_unavailable") from None

    @staticmethod
    def claim_in_connection(connection, receipt: PackageImportReceipt) -> bool:
        row = connection.execute(
            """
            INSERT INTO offline_package_imports (
                id, package_id, package_sha256, centre_code,
                record_count, created_by, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            (
                receipt.id,
                receipt.package_id,
                receipt.package_sha256,
                receipt.centre_code,
                receipt.record_count,
                receipt.created_by,
                receipt.created_at,
            ),
        ).fetchone()
        return row is not None

    def find_receipt(
        self,
        *,
        package_sha256: str,
        package_id: str,
    ) -> PackageImportReceipt | None:
        try:
            with self._bootstrap._open_connection() as connection:
                row = connection.execute(
                    """
                    SELECT id, package_id, package_sha256, centre_code,
                           record_count, created_by, created_at
                    FROM offline_package_imports
                    WHERE package_sha256 = %s OR package_id = %s
                    LIMIT 1
                    """,
                    (package_sha256, package_id),
                ).fetchone()
            return _postgres_receipt(row) if row is not None else None
        except psycopg.Error:
            raise PostgresRepositoryError("postgres_package_import_unavailable") from None

    def append_attempt(self, attempt: PackageImportAttempt) -> None:
        try:
            with self._bootstrap._open_connection() as connection:
                self.append_attempt_in_connection(connection, attempt)
        except psycopg.Error:
            raise PostgresRepositoryError("postgres_package_import_unavailable") from None

    @staticmethod
    def append_attempt_in_connection(connection, attempt: PackageImportAttempt) -> None:
        connection.execute(
            """
            INSERT INTO offline_package_import_logs (
                id, package_sha256, package_id, centre_code, source_filename,
                dictionary_id, dictionary_version, result, error_code, error_detail,
                record_count, created_count, duplicate_count, created_by, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                attempt.id,
                attempt.package_sha256,
                attempt.package_id,
                attempt.centre_code,
                attempt.source_filename,
                attempt.dictionary_id,
                attempt.dictionary_version,
                attempt.result,
                attempt.error_code,
                attempt.error_detail,
                attempt.record_count,
                attempt.created_count,
                attempt.duplicate_count,
                attempt.created_by,
                attempt.created_at,
            ),
        )

    def list_attempts(self, *, limit: int = 100) -> list[PackageImportAttempt]:
        if not 1 <= limit <= 500:
            raise ValueError("package_import_log_limit_invalid")
        try:
            with self._bootstrap._open_connection() as connection:
                rows = connection.execute(
                    """
                    SELECT id, package_sha256, package_id, centre_code, source_filename,
                           dictionary_id, dictionary_version, result, error_code, error_detail,
                           record_count, created_count, duplicate_count, created_by, created_at
                    FROM offline_package_import_logs
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    (limit,),
                ).fetchall()
            return [_postgres_attempt(row) for row in rows]
        except psycopg.Error:
            raise PostgresRepositoryError("postgres_package_import_unavailable") from None
