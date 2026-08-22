from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_cleanup_script_preserves_submitted_records_and_removes_unsubmitted_records(tmp_path: Path) -> None:
    database_path = tmp_path / "companion.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE source_files (id TEXT PRIMARY KEY);
            CREATE TABLE deidentification_drafts (
                id TEXT PRIMARY KEY,
                original_source_file_id TEXT NOT NULL,
                derivative_source_file_id TEXT NOT NULL
            );
            CREATE TABLE candidates (
                id TEXT PRIMARY KEY,
                source_file_id TEXT NOT NULL
            );
            CREATE TABLE transfer_requests (
                id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                status TEXT NOT NULL,
                external_reference TEXT
            );
            CREATE TABLE audit_events (
                id TEXT PRIMARY KEY,
                candidate_id TEXT,
                details_json TEXT NOT NULL
            );
            INSERT INTO source_files VALUES ('source-submitted'), ('source-unsubmitted');
            INSERT INTO candidates VALUES
                ('candidate-submitted', 'source-submitted'),
                ('candidate-unsubmitted', 'source-unsubmitted');
            INSERT INTO transfer_requests VALUES
                ('transfer-submitted', 'candidate-submitted', 'submitted', 'S/SS/SE/F/I'),
                ('transfer-queued', 'candidate-unsubmitted', 'queued', NULL);
            INSERT INTO audit_events VALUES
                ('audit-submitted', 'candidate-submitted', '{}'),
                ('audit-unsubmitted', 'candidate-unsubmitted', '{}'),
                ('audit-source-unsubmitted', NULL, '{"source_file_id":"source-unsubmitted"}');
            """
        )

    script_path = Path(__file__).parents[1] / "scripts" / "clear_unsubmitted_companion_data.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--database",
            str(database_path),
            "--backup-dir",
            str(tmp_path / "backups"),
            "--execute",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(result.stdout)

    assert report["retained_submitted_candidates"] == 1
    assert report["deleted_unsubmitted_candidates"] == 1
    assert Path(report["backup_path"]).is_file()
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT id FROM candidates").fetchall() == [("candidate-submitted",)]
        assert connection.execute("SELECT id FROM transfer_requests").fetchall() == [("transfer-submitted",)]
        assert connection.execute("SELECT id FROM source_files").fetchall() == [("source-submitted",)]
        assert connection.execute("SELECT id FROM audit_events").fetchall() == [("audit-submitted",)]


def test_cleanup_script_refuses_to_delete_hash_chained_audit_history(tmp_path: Path) -> None:
    database_path = tmp_path / "chained.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE source_files (id TEXT PRIMARY KEY);
            CREATE TABLE deidentification_drafts (
                id TEXT PRIMARY KEY,
                original_source_file_id TEXT NOT NULL,
                derivative_source_file_id TEXT NOT NULL
            );
            CREATE TABLE candidates (id TEXT PRIMARY KEY, source_file_id TEXT NOT NULL);
            CREATE TABLE transfer_requests (
                id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                status TEXT NOT NULL,
                external_reference TEXT
            );
            CREATE TABLE audit_events (
                id TEXT PRIMARY KEY,
                candidate_id TEXT,
                details_json TEXT NOT NULL,
                prev_hash TEXT,
                event_hash TEXT
            );
            """
        )

    script_path = Path(__file__).parents[1] / "scripts" / "clear_unsubmitted_companion_data.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--database",
            str(database_path),
            "--backup-dir",
            str(tmp_path / "backups"),
            "--execute",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "hash_chained_audit_cannot_be_deleted" in result.stderr
