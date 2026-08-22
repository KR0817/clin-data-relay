from __future__ import annotations

from pathlib import Path

from app.persistence import Database


def test_database_interface_initialises_and_reopens_a_local_repository(tmp_path: Path) -> None:
    database_path = tmp_path / "companion.db"
    database = Database(database_path)

    database.initialise()
    with database.connect() as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        investigator = connection.execute(
            "SELECT role, centre_code, active FROM users WHERE username = ?",
            ("site-a-investigator@example.test",),
        ).fetchone()

    assert integrity == "ok"
    assert investigator["role"] == "site_investigator"
    assert investigator["centre_code"] == "SITE_A"
    assert investigator["active"] == 1
    assert database.current_schema_version() == 1

    reopened = Database(database_path)
    reopened.initialise()
    with reopened.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= 3
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1


def test_database_enables_local_writer_safety_pragmas(tmp_path: Path) -> None:
    database = Database(tmp_path / "pragmas.db")
    database.initialise()

    with database.connect() as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]

    assert journal_mode == "wal"
    assert busy_timeout >= 5_000


def test_database_audit_chain_detects_persisted_tampering(tmp_path: Path) -> None:
    database = Database(tmp_path / "audit.db")
    database.initialise()
    with database.connect() as connection:
        database.append_audit_event(
            connection,
            candidate_id=None,
            centre_code="SITE_A",
            event_type="synthetic_test_event",
            actor_username="tester@example.test",
            details={"value": "before"},
        )
        assert database.verify_audit_chain(connection).ok is True

    with database.connect() as connection:
        connection.execute(
            "UPDATE audit_events SET details_json = ? WHERE event_type = 'synthetic_test_event'",
            ('{"value":"after"}',),
        )
        verification = database.verify_audit_chain(connection)

    assert verification.ok is False
    assert verification.reason == "audit_event_hash_mismatch"


def test_initialise_marks_interrupted_recognition_work_as_failed(tmp_path: Path) -> None:
    database = Database(tmp_path / "restart.db")
    database.initialise()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO source_files (
                id, centre_code, source_filename, sha256, mime_type, storage_key,
                created_by, created_at
            ) VALUES ('source-running', 'SITE_A', 'test.png', ?, 'image/png',
                      'synthetic/SITE_A/test.png', 'tester', 'now')
            """,
            ("a" * 64,),
        )
        connection.execute(
            """
            INSERT INTO recognition_jobs (
                id, centre_code, status, item_count, completed_count, failed_count,
                created_by, created_at, updated_at
            ) VALUES ('job-running', 'SITE_A', 'running', 1, 0, 0, 'tester', 'now', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO recognition_job_items (
                id, job_id, source_file_id, centre_code, edc_subject_ref, edc_event_ref,
                use_kimi, field_codes_json, status, candidate_ids_json,
                attempts, created_at
            ) VALUES (
                'item-running', 'job-running', 'source-running', 'SITE_A', 'SUBJ001', 'WEEK_0',
                1, '[]', 'running', '[]', 0, 'now'
            )
            """
        )

    database.initialise()
    with database.connect() as connection:
        job = connection.execute(
            "SELECT status, completed_count, failed_count FROM recognition_jobs WHERE id = 'job-running'"
        ).fetchone()
        item = connection.execute(
            "SELECT status, error_code FROM recognition_job_items WHERE id = 'item-running'"
        ).fetchone()

    assert job["status"] == "failed"
    assert job["completed_count"] == 0
    assert job["failed_count"] == 1
    assert item["status"] == "failed"
    assert item["error_code"] == "recognition_interrupted"
