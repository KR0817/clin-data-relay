from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from app.centre_profile import CentreProfile
from app.clock import utc_now
from app.audit_chain import (
    GENESIS_PREV_HASH,
    ChainVerification,
    compute_event_hash,
    event_payload,
    verify_chain,
)
from app.security import DEMO_PASSWORD, SETUP_REQUIRED_PASSWORD_HASH, password_digest


LATEST_SQLITE_SCHEMA_VERSION = 1


class Database:
    def __init__(self, database_path: Path, centre_profile: CentreProfile | None = None) -> None:
        self.database_path = database_path
        self.centre_profile = centre_profile

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialise(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    centre_code TEXT,
                    role TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    credential_kind TEXT NOT NULL DEFAULT 'current'
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS source_files (
                    id TEXT PRIMARY KEY,
                    centre_code TEXT NOT NULL,
                    source_filename TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    storage_key TEXT NOT NULL,
                    edc_subject_ref TEXT,
                    edc_event_ref TEXT,
                    edc_subject_oid TEXT,
                    edc_subject_created INTEGER,
                    edc_event_scheduled INTEGER,
                    edc_provisioned_at TEXT,
                    edc_provisioning_status TEXT,
                    edc_provisioning_error_code TEXT,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS deidentification_drafts (
                    id TEXT PRIMARY KEY,
                    original_source_file_id TEXT NOT NULL REFERENCES source_files(id),
                    derivative_source_file_id TEXT NOT NULL UNIQUE REFERENCES source_files(id),
                    centre_code TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detected_marker_codes_json TEXT NOT NULL,
                    ocr_engine_version TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    confirmed_by TEXT,
                    confirmed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS extraction_runs (
                    id TEXT PRIMARY KEY,
                    centre_code TEXT NOT NULL,
                    source_file_id TEXT NOT NULL REFERENCES source_files(id),
                    edc_subject_ref TEXT NOT NULL,
                    edc_event_ref TEXT NOT NULL,
                    dictionary_id TEXT NOT NULL,
                    dictionary_version TEXT NOT NULL,
                    engine TEXT NOT NULL,
                    engine_version TEXT NOT NULL,
                    model_ids_json TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    derivative_sha256 TEXT,
                    preprocessing_version TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    duration_ms INTEGER NOT NULL,
                    evidence_json TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS candidates (
                    id TEXT PRIMARY KEY,
                    centre_code TEXT NOT NULL,
                    source_file_id TEXT NOT NULL REFERENCES source_files(id),
                    edc_subject_ref TEXT NOT NULL,
                    edc_event_ref TEXT NOT NULL,
                    field_code TEXT NOT NULL,
                    proposed_value TEXT NOT NULL,
                    unit TEXT,
                    final_value TEXT,
                    status TEXT NOT NULL,
                    ocr_engine_version TEXT NOT NULL,
                    kimi_model TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    local_ocr_value TEXT,
                    local_ocr_unit TEXT,
                    extraction_agreement TEXT,
                    evidence_text TEXT,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    review_reason TEXT
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT REFERENCES candidates(id),
                    centre_code TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor_username TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    prev_hash TEXT,
                    event_hash TEXT
                );
                CREATE TABLE IF NOT EXISTS field_header_overrides (
                    event_ref TEXT NOT NULL,
                    field_code TEXT NOT NULL,
                    display_header TEXT NOT NULL,
                    updated_by TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    PRIMARY KEY (event_ref, field_code)
                );
                CREATE TABLE IF NOT EXISTS quality_findings (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL REFERENCES candidates(id),
                    centre_code TEXT NOT NULL,
                    rule_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    findings_json TEXT NOT NULL,
                    evaluated_value TEXT NOT NULL,
                    evaluated_unit TEXT,
                    evaluated_by TEXT NOT NULL,
                    evaluated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS data_issues (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL REFERENCES candidates(id),
                    centre_code TEXT NOT NULL,
                    status TEXT NOT NULL,
                    opened_message TEXT NOT NULL,
                    opened_by TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    answer_message TEXT,
                    answered_by TEXT,
                    answered_at TEXT,
                    resolution_message TEXT,
                    resolved_by TEXT,
                    resolved_at TEXT,
                    reopened_by TEXT,
                    reopened_at TEXT
                );
                CREATE TABLE IF NOT EXISTS transfer_holds (
                    id TEXT PRIMARY KEY,
                    scope_key TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    centre_code TEXT,
                    subject_ref TEXT,
                    event_ref TEXT,
                    action TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    actor_username TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS visit_attestations (
                    id TEXT PRIMARY KEY,
                    centre_code TEXT NOT NULL,
                    subject_ref TEXT NOT NULL,
                    event_ref TEXT NOT NULL,
                    message TEXT NOT NULL,
                    candidate_count INTEGER NOT NULL,
                    candidate_state_sha256 TEXT NOT NULL,
                    attested_by TEXT NOT NULL,
                    attested_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transfer_requests (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL REFERENCES candidates(id),
                    centre_code TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    target_kind TEXT NOT NULL DEFAULT 'not_configured',
                    package_sha256 TEXT,
                    package_json TEXT,
                    idempotency_key TEXT,
                    receipt_json TEXT,
                    receipt_sha256 TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error_code TEXT,
                    last_error_message TEXT,
                    reconciled_by TEXT,
                    reconciled_at TEXT,
                    reconciliation_note TEXT,
                    external_reference TEXT,
                    authority_response_sha256 TEXT,
                    submitted_at TEXT,
                    readback_status TEXT NOT NULL DEFAULT 'not_checked',
                    readback_checked_at TEXT,
                    readback_attempt_count INTEGER NOT NULL DEFAULT 0,
                    readback_observed_value TEXT,
                    readback_response_sha256 TEXT,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS readback_checks (
                    id TEXT PRIMARY KEY,
                    transfer_id TEXT NOT NULL REFERENCES transfer_requests(id),
                    candidate_id TEXT NOT NULL REFERENCES candidates(id),
                    centre_code TEXT NOT NULL,
                    status TEXT NOT NULL,
                    expected_value TEXT NOT NULL,
                    observed_value TEXT,
                    response_sha256 TEXT,
                    checked_by TEXT NOT NULL,
                    checked_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS structured_import_batches (
                    id TEXT PRIMARY KEY,
                    centre_code TEXT NOT NULL,
                    source_file_id TEXT NOT NULL REFERENCES source_files(id),
                    source_sha256 TEXT NOT NULL,
                    source_filename TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    created_count INTEGER NOT NULL,
                    duplicate_count INTEGER NOT NULL,
                    blocked_count INTEGER NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS offline_package_imports (
                    id TEXT PRIMARY KEY,
                    package_id TEXT NOT NULL UNIQUE,
                    package_sha256 TEXT NOT NULL UNIQUE,
                    centre_code TEXT NOT NULL,
                    record_count INTEGER NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS offline_package_import_logs (
                    id TEXT PRIMARY KEY,
                    package_sha256 TEXT,
                    package_id TEXT,
                    centre_code TEXT,
                    source_filename TEXT NOT NULL,
                    dictionary_id TEXT,
                    dictionary_version TEXT,
                    result TEXT NOT NULL,
                    error_code TEXT,
                    error_detail TEXT,
                    record_count INTEGER NOT NULL DEFAULT 0,
                    created_count INTEGER NOT NULL DEFAULT 0,
                    duplicate_count INTEGER NOT NULL DEFAULT 0,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    centre_code TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    assigned_role TEXT NOT NULL,
                    candidate_id TEXT REFERENCES candidates(id),
                    transfer_id TEXT REFERENCES transfer_requests(id),
                    data_issue_id TEXT REFERENCES data_issues(id),
                    title TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    completed_by TEXT,
                    completed_at TEXT,
                    completion_note TEXT
                );
                CREATE TABLE IF NOT EXISTS dictionary_releases (
                    id TEXT PRIMARY KEY,
                    version TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    base_release_id TEXT,
                    rollback_of TEXT,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    published_by TEXT,
                    published_at TEXT
                );
                CREATE TABLE IF NOT EXISTS dictionary_release_items (
                    release_id TEXT NOT NULL REFERENCES dictionary_releases(id),
                    event_ref TEXT NOT NULL,
                    field_code TEXT NOT NULL,
                    display_header TEXT NOT NULL,
                    PRIMARY KEY (release_id, event_ref, field_code)
                );
                CREATE TABLE IF NOT EXISTS dictionary_release_state (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    active_release_id TEXT NOT NULL REFERENCES dictionary_releases(id)
                );
                CREATE TABLE IF NOT EXISTS analysis_snapshots (
                    id TEXT PRIMARY KEY,
                    content_sha256 TEXT NOT NULL,
                    canonical_json TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    dictionary_release_id TEXT NOT NULL REFERENCES dictionary_releases(id),
                    quality_rule_version TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recognition_jobs (
                    id TEXT PRIMARY KEY,
                    centre_code TEXT NOT NULL,
                    status TEXT NOT NULL,
                    item_count INTEGER NOT NULL,
                    completed_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    cancelled_by TEXT,
                    cancelled_at TEXT
                );
                CREATE TABLE IF NOT EXISTS recognition_job_items (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES recognition_jobs(id),
                    source_file_id TEXT NOT NULL REFERENCES source_files(id),
                    centre_code TEXT NOT NULL,
                    edc_subject_ref TEXT NOT NULL,
                    edc_event_ref TEXT NOT NULL,
                    field_codes_json TEXT,
                    candidate_ids_json TEXT,
                    use_kimi INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    last_retry_at TEXT,
                    UNIQUE (job_id, source_file_id)
                );
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_deidentification_drafts_original_source
                ON deidentification_drafts (original_source_file_id)
                """
            )
            existing_user_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(users)").fetchall()
            }
            if "credential_kind" not in existing_user_columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN credential_kind TEXT NOT NULL DEFAULT 'current'"
                )
                connection.execute(
                    """
                    UPDATE users SET credential_kind = 'legacy_demo'
                    WHERE password_hash NOT LIKE 'scrypt$%'
                      AND username LIKE '%@example.test'
                    """
                )
            existing_audit_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(audit_events)").fetchall()
            }
            audit_chain_added = False
            for column_name in ("prev_hash", "event_hash"):
                if column_name not in existing_audit_columns:
                    connection.execute(f"ALTER TABLE audit_events ADD COLUMN {column_name} TEXT")
                    audit_chain_added = True
            if audit_chain_added:
                previous = GENESIS_PREV_HASH
                historical_rows = connection.execute(
                    "SELECT rowid, * FROM audit_events ORDER BY rowid"
                ).fetchall()
                for row in historical_rows:
                    payload = self._audit_row_payload(row)
                    digest = compute_event_hash(previous, payload)
                    connection.execute(
                        "UPDATE audit_events SET prev_hash = ?, event_hash = ? WHERE rowid = ?",
                        (previous, digest, row["rowid"]),
                    )
                    previous = digest
                self.append_audit_event(
                    connection,
                    candidate_id=None,
                    centre_code="SYSTEM",
                    event_type="audit_chain_backfilled",
                    actor_username="system",
                    details={"historical_event_count": len(historical_rows)},
                )
            existing_source_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(source_files)").fetchall()
            }
            for column_name, column_type in (
                ("edc_subject_ref", "TEXT"),
                ("edc_event_ref", "TEXT"),
                ("edc_subject_oid", "TEXT"),
                ("edc_subject_created", "INTEGER"),
                ("edc_event_scheduled", "INTEGER"),
                ("edc_provisioned_at", "TEXT"),
                ("edc_provisioning_status", "TEXT"),
                ("edc_provisioning_error_code", "TEXT"),
                ("content_purged_at", "TEXT"),
            ):
                if column_name not in existing_source_columns:
                    connection.execute(f"ALTER TABLE source_files ADD COLUMN {column_name} {column_type}")
            existing_recognition_item_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(recognition_job_items)").fetchall()
            }
            if "use_kimi" not in existing_recognition_item_columns:
                connection.execute(
                    "ALTER TABLE recognition_job_items ADD COLUMN use_kimi INTEGER NOT NULL DEFAULT 0"
                )
            if "candidate_ids_json" not in existing_recognition_item_columns:
                connection.execute(
                    "ALTER TABLE recognition_job_items ADD COLUMN candidate_ids_json TEXT"
                )
            existing_candidate_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(candidates)").fetchall()
            }
            for column_name in (
                "local_ocr_value",
                "local_ocr_unit",
                "extraction_agreement",
                "evidence_text",
            ):
                if column_name not in existing_candidate_columns:
                    connection.execute(f"ALTER TABLE candidates ADD COLUMN {column_name} TEXT")
            if "import_batch_id" not in existing_candidate_columns:
                connection.execute("ALTER TABLE candidates ADD COLUMN import_batch_id TEXT")
            if "origin_type" not in existing_candidate_columns:
                connection.execute(
                    "ALTER TABLE candidates ADD COLUMN origin_type TEXT NOT NULL DEFAULT 'image_ocr'"
                )
            if "extraction_run_id" not in existing_candidate_columns:
                connection.execute("ALTER TABLE candidates ADD COLUMN extraction_run_id TEXT")
            existing_attestation_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(visit_attestations)").fetchall()
            }
            if "candidate_state_sha256" not in existing_attestation_columns:
                connection.execute("ALTER TABLE visit_attestations ADD COLUMN candidate_state_sha256 TEXT")
            existing_transfer_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(transfer_requests)").fetchall()
            }
            if "target_kind" not in existing_transfer_columns:
                connection.execute(
                    "ALTER TABLE transfer_requests ADD COLUMN target_kind TEXT NOT NULL DEFAULT 'not_configured'"
                )
            if "package_sha256" not in existing_transfer_columns:
                connection.execute("ALTER TABLE transfer_requests ADD COLUMN package_sha256 TEXT")
            if "package_json" not in existing_transfer_columns:
                connection.execute("ALTER TABLE transfer_requests ADD COLUMN package_json TEXT")
            if "idempotency_key" not in existing_transfer_columns:
                connection.execute("ALTER TABLE transfer_requests ADD COLUMN idempotency_key TEXT")
            if "receipt_json" not in existing_transfer_columns:
                connection.execute("ALTER TABLE transfer_requests ADD COLUMN receipt_json TEXT")
            if "receipt_sha256" not in existing_transfer_columns:
                connection.execute("ALTER TABLE transfer_requests ADD COLUMN receipt_sha256 TEXT")
            if "attempt_count" not in existing_transfer_columns:
                connection.execute(
                    "ALTER TABLE transfer_requests ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0"
                )
            if "retry_count" not in existing_transfer_columns:
                connection.execute(
                    "ALTER TABLE transfer_requests ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0"
                )
            if "last_error_code" not in existing_transfer_columns:
                connection.execute("ALTER TABLE transfer_requests ADD COLUMN last_error_code TEXT")
            if "last_error_message" not in existing_transfer_columns:
                connection.execute("ALTER TABLE transfer_requests ADD COLUMN last_error_message TEXT")
            if "reconciled_by" not in existing_transfer_columns:
                connection.execute("ALTER TABLE transfer_requests ADD COLUMN reconciled_by TEXT")
            if "reconciled_at" not in existing_transfer_columns:
                connection.execute("ALTER TABLE transfer_requests ADD COLUMN reconciled_at TEXT")
            if "reconciliation_note" not in existing_transfer_columns:
                connection.execute("ALTER TABLE transfer_requests ADD COLUMN reconciliation_note TEXT")
            if "external_reference" not in existing_transfer_columns:
                connection.execute("ALTER TABLE transfer_requests ADD COLUMN external_reference TEXT")
            if "authority_response_sha256" not in existing_transfer_columns:
                connection.execute("ALTER TABLE transfer_requests ADD COLUMN authority_response_sha256 TEXT")
            if "submitted_at" not in existing_transfer_columns:
                connection.execute("ALTER TABLE transfer_requests ADD COLUMN submitted_at TEXT")
            if "updated_at" not in existing_transfer_columns:
                connection.execute("ALTER TABLE transfer_requests ADD COLUMN updated_at TEXT")
            if "readback_status" not in existing_transfer_columns:
                connection.execute(
                    "ALTER TABLE transfer_requests ADD COLUMN readback_status TEXT NOT NULL DEFAULT 'not_checked'"
                )
            if "readback_checked_at" not in existing_transfer_columns:
                connection.execute("ALTER TABLE transfer_requests ADD COLUMN readback_checked_at TEXT")
            if "readback_attempt_count" not in existing_transfer_columns:
                connection.execute(
                    "ALTER TABLE transfer_requests ADD COLUMN readback_attempt_count INTEGER NOT NULL DEFAULT 0"
                )
            if "readback_observed_value" not in existing_transfer_columns:
                connection.execute("ALTER TABLE transfer_requests ADD COLUMN readback_observed_value TEXT")
            if "readback_response_sha256" not in existing_transfer_columns:
                connection.execute("ALTER TABLE transfer_requests ADD COLUMN readback_response_sha256 TEXT")
            connection.execute(
                "UPDATE transfer_requests SET updated_at = created_at WHERE updated_at IS NULL"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_quality_findings_candidate ON quality_findings (candidate_id, evaluated_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_data_issues_candidate_status ON data_issues (candidate_id, status)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_transfer_holds_scope ON transfer_holds (scope_key, created_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_visit_attestations_visit ON visit_attestations (centre_code, subject_ref, event_ref, attested_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_scope_status ON tasks (centre_code, status, assigned_role)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_recognition_jobs_scope_status ON recognition_jobs (centre_code, status, created_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_recognition_job_items_job_status ON recognition_job_items (job_id, status)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_extraction_runs_source_event ON extraction_runs (source_file_id, edc_event_ref, created_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_candidates_extraction_run ON candidates (extraction_run_id)"
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_candidates_confirmed_export_scope
                ON candidates (centre_code, edc_event_ref, edc_subject_ref, created_at)
                WHERE status = 'human_confirmed'
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_events_review ON audit_events (event_type, created_at)"
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_transfer_requests_centre_idempotency
                ON transfer_requests (centre_code, idempotency_key)
                WHERE idempotency_key IS NOT NULL
                """
            )
            if self.centre_profile is None:
                seeded_users = (
                    ("site-a-investigator@example.test", "SITE_A", "site_investigator"),
                    ("site-b-investigator@example.test", "SITE_B", "site_investigator"),
                    ("principal-investigator@example.test", None, "principal_investigator"),
                    ("central-data-manager@example.test", None, "central_data_manager"),
                )
            else:
                existing_users = connection.execute(
                    "SELECT username, centre_code, role, active FROM users ORDER BY username"
                ).fetchall()
                if existing_users:
                    if len(existing_users) != 1 or (
                        existing_users[0]["username"] != self.centre_profile.username
                        or existing_users[0]["centre_code"] != self.centre_profile.centre_code
                        or existing_users[0]["role"] != "site_investigator"
                        or existing_users[0]["active"] != 1
                    ):
                        raise RuntimeError("centre_profile_database_scope_mismatch")
                    seeded_users = ()
                else:
                    connection.execute(
                        """
                        INSERT INTO users (
                            id, username, password_hash, centre_code, role, active, credential_kind
                        ) VALUES (?, ?, ?, ?, 'site_investigator', 1, 'current')
                        """,
                        (
                            str(uuid4()),
                            self.centre_profile.username,
                            SETUP_REQUIRED_PASSWORD_HASH,
                            self.centre_profile.centre_code,
                        ),
                    )
                    seeded_users = ()
            for username, centre_code, role in seeded_users:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO users (
                        id, username, password_hash, centre_code, role, credential_kind
                    ) VALUES (?, ?, ?, ?, ?, 'legacy_demo')
                    """,
                    (str(uuid4()), username, password_digest(DEMO_PASSWORD), centre_code, role),
                )
            # Preserve legacy usernames for audit provenance, but remove the entry role
            # from the active authentication surface and invalidate its existing sessions.
            if self.centre_profile is None:
                connection.execute("UPDATE users SET active = 0 WHERE role = 'site_entry'")
            interrupted_at = utc_now()
            interrupted_job_ids = [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM recognition_jobs WHERE status = 'running'"
                ).fetchall()
            ]
            connection.execute(
                """
                UPDATE recognition_job_items
                SET status = 'failed', error_code = 'recognition_interrupted',
                    error_message = 'recognition_interrupted', finished_at = ?
                WHERE status = 'running'
                """,
                (interrupted_at,),
            )
            for job_id in interrupted_job_ids:
                connection.execute(
                    """
                    UPDATE recognition_jobs
                    SET status = 'failed',
                        completed_count = (
                            SELECT COUNT(*) FROM recognition_job_items
                            WHERE job_id = ? AND status = 'succeeded'
                        ),
                        failed_count = (
                            SELECT COUNT(*) FROM recognition_job_items
                            WHERE job_id = ? AND status = 'failed'
                        ),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (job_id, job_id, interrupted_at, job_id),
                )
            if interrupted_job_ids:
                self.append_audit_event(
                    connection,
                    candidate_id=None,
                    centre_code="SYSTEM",
                    event_type="recognition_jobs_recovered_after_restart",
                    actor_username="system",
                    details={"job_count": len(interrupted_job_ids)},
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO schema_migrations (version, name, applied_at)
                VALUES (?, 'sqlite_converged_schema', ?)
                """,
                (LATEST_SQLITE_SCHEMA_VERSION, utc_now()),
            )

    def current_schema_version(self) -> int:
        """Return the highest successfully applied local schema version."""

        with self.connect() as connection:
            row = connection.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
        if row is None or row["version"] is None:
            raise RuntimeError("database_schema_version_missing")
        return int(row["version"])

    @staticmethod
    def _audit_row_payload(row: sqlite3.Row) -> dict[str, object]:
        return event_payload(
            event_id=row["id"],
            candidate_id=row["candidate_id"],
            centre_code=row["centre_code"],
            event_type=row["event_type"],
            actor_username=row["actor_username"],
            created_at=row["created_at"],
            details=json.loads(row["details_json"]),
        )

    def append_audit_event(
        self,
        connection: sqlite3.Connection,
        *,
        candidate_id: str | None,
        centre_code: str,
        event_type: str,
        actor_username: str,
        details: dict[str, object],
        created_at: str | None = None,
    ) -> str:
        """Append one chained audit event inside the caller's transaction."""

        event_id = str(uuid4())
        timestamp = created_at or utc_now()
        previous_row = connection.execute(
            "SELECT event_hash FROM audit_events ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        previous = previous_row["event_hash"] if previous_row is not None else GENESIS_PREV_HASH
        if not previous:
            raise RuntimeError("audit_chain_tail_missing")
        payload = event_payload(
            event_id=event_id,
            candidate_id=candidate_id,
            centre_code=centre_code,
            event_type=event_type,
            actor_username=actor_username,
            created_at=timestamp,
            details=details,
        )
        digest = compute_event_hash(previous, payload)
        connection.execute(
            """
            INSERT INTO audit_events (
                id, candidate_id, centre_code, event_type, actor_username,
                created_at, details_json, prev_hash, event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                candidate_id,
                centre_code,
                event_type,
                actor_username,
                timestamp,
                json.dumps(details, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                previous,
                digest,
            ),
        )
        return event_id

    def verify_audit_chain(
        self,
        connection: sqlite3.Connection,
        *,
        expected_head_hash: str | None = None,
    ) -> ChainVerification:
        rows = connection.execute("SELECT rowid, * FROM audit_events ORDER BY rowid").fetchall()
        events: list[dict[str, object]] = []
        for row in rows:
            try:
                payload: object = self._audit_row_payload(row)
            except (json.JSONDecodeError, TypeError):
                payload = None
            events.append(
                {
                    "prev_hash": row["prev_hash"],
                    "event_hash": row["event_hash"],
                    "payload": payload,
                }
            )
        return verify_chain(events, expected_head_hash=expected_head_hash)

    def reset_centre_password(self, encoded_password_hash: str) -> None:
        if self.centre_profile is None:
            raise RuntimeError("centre_profile_required")
        with self.connect() as connection:
            account = connection.execute(
                """
                SELECT id FROM users
                WHERE username = ? AND centre_code = ? AND role = 'site_investigator' AND active = 1
                """,
                (self.centre_profile.username, self.centre_profile.centre_code),
            ).fetchone()
            if account is None:
                raise RuntimeError("centre_profile_account_missing")
            connection.execute(
                "UPDATE users SET password_hash = ?, credential_kind = 'current' WHERE id = ?",
                (encoded_password_hash, account["id"]),
            )
            connection.execute("DELETE FROM sessions WHERE user_id = ?", (account["id"],))
            self.append_audit_event(
                connection,
                candidate_id=None,
                centre_code=self.centre_profile.centre_code,
                event_type="centre_password_reset",
                actor_username=self.centre_profile.username,
                details={"method": "local_console"},
            )
