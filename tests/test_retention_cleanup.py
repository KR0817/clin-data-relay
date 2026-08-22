from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_expired_original_cleanup_preserves_hash_and_removes_only_bytes(tmp_path: Path) -> None:
    database = tmp_path / "companion.db"
    source_id = "source-expired"
    upload = tmp_path / "synthetic_uploads" / "SITE_A" / f"{source_id}.png"
    upload.parent.mkdir(parents=True)
    upload.write_bytes(b"synthetic-original")
    old = (datetime.now(UTC) - timedelta(days=45)).isoformat()
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE source_files (
                id TEXT PRIMARY KEY, centre_code TEXT NOT NULL, storage_key TEXT NOT NULL,
                source_filename TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE audit_events (
                id TEXT PRIMARY KEY, candidate_id TEXT, centre_code TEXT NOT NULL,
                event_type TEXT NOT NULL, actor_username TEXT NOT NULL,
                created_at TEXT NOT NULL, details_json TEXT NOT NULL,
                prev_hash TEXT, event_hash TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO source_files (id, centre_code, storage_key, source_filename, sha256, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (source_id, "SITE_A", f"synthetic/SITE_A/{source_id}.png", "report.png", "a" * 64, old),
        )
    script = Path(__file__).parents[1] / "scripts" / "cleanup_expired_originals.py"
    result = subprocess.run(
        [sys.executable, str(script), "--database", str(database), "--retention-days", "30", "--execute"],
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(result.stdout)

    assert report["purged_count"] == 1
    assert not upload.exists()
    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT sha256, content_purged_at FROM source_files WHERE id = ?", (source_id,)).fetchone()
        assert row[0] == "a" * 64
        assert row[1]
        assert connection.execute("SELECT event_type FROM audit_events").fetchone()[0] == "original_source_content_purged"
