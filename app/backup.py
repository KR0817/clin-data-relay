"""SQLite online backup with temporary restore integrity verification."""

from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
import gc
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from uuid import uuid4

from app.audit_chain import event_payload, make_anchor, verify_chain


def _audit_chain_anchor(connection: sqlite3.Connection, generated_at: str) -> dict[str, object] | None:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'audit_events'"
    ).fetchone()
    if table is None:
        return None
    columns = {row[1] for row in connection.execute("PRAGMA table_info(audit_events)").fetchall()}
    if not {"prev_hash", "event_hash"} <= columns:
        raise RuntimeError("backup_audit_chain_columns_missing")
    rows = connection.execute("SELECT rowid, * FROM audit_events ORDER BY rowid").fetchall()
    events = []
    for row in rows:
        try:
            details = json.loads(row["details_json"])
        except (json.JSONDecodeError, TypeError) as error:
            raise RuntimeError("backup_audit_chain_verification_failed") from error
        if not isinstance(details, dict):
            raise RuntimeError("backup_audit_chain_verification_failed")
        events.append(
            {
                "prev_hash": row["prev_hash"],
                "event_hash": row["event_hash"],
                "payload": event_payload(
                    event_id=row["id"],
                    candidate_id=row["candidate_id"],
                    centre_code=row["centre_code"],
                    event_type=row["event_type"],
                    actor_username=row["actor_username"],
                    created_at=row["created_at"],
                    details=details,
                ),
            }
        )
    verification = verify_chain(events)
    if not verification.ok:
        raise RuntimeError("backup_audit_chain_verification_failed")
    return make_anchor(verification.head_hash, verification.checked, generated_at)


def backup_database(source: Path, output_directory: Path) -> Path:
    source = source.resolve(strict=True)
    output_directory = output_directory.resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    backup_id = f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%SZ')}-{uuid4().hex[:8]}"
    backup_path = output_directory / f"companion-{backup_id}.db"
    partial_path = output_directory / f"companion-{backup_id}.partial"
    source_uri = f"{source.as_uri()}?mode=ro"
    completed_at = datetime.now(UTC).isoformat()
    with closing(sqlite3.connect(source_uri, uri=True)) as source_connection:
        source_connection.row_factory = sqlite3.Row
        audit_anchor = _audit_chain_anchor(source_connection, completed_at)
        with closing(sqlite3.connect(partial_path)) as destination_connection:
            source_connection.backup(destination_connection)
    del source_connection, destination_connection
    os.replace(partial_path, backup_path)
    with tempfile.TemporaryDirectory(prefix="companion-restore-check-") as temporary_directory:
        restored_path = Path(temporary_directory) / "restored.db"
        with closing(sqlite3.connect(backup_path)) as backup_connection:
            with closing(sqlite3.connect(restored_path)) as restored_connection:
                backup_connection.backup(restored_connection)
        with closing(sqlite3.connect(restored_path)) as restored_connection:
            restored_connection.row_factory = sqlite3.Row
            integrity = restored_connection.execute("PRAGMA integrity_check").fetchone()[0]
            restored_anchor = _audit_chain_anchor(restored_connection, completed_at)
    del backup_connection, restored_connection
    if integrity != "ok":
        raise RuntimeError("backup_restore_integrity_failed")
    if restored_anchor != audit_anchor:
        raise RuntimeError("backup_restore_audit_chain_mismatch")
    digest = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    evidence = {
        "protocol": "clinical-edc-companion-backup-evidence-v1",
        "backup_id": backup_id,
        "backup_filename": backup_path.name,
        "backup_sha256": digest,
        "source_database_name": source.name,
        "restore_integrity_check": integrity,
        "completed_at": completed_at,
    }
    if audit_anchor is not None:
        evidence["audit_chain_anchor"] = audit_anchor
    evidence_path = output_directory / f"companion-{backup_id}.evidence.json"
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_directory / f"companion-{backup_id}.sha256").write_text(f"{digest}  {backup_path.name}\n", encoding="ascii")
    # The Windows SQLite driver can retain native file handles until the
    # connection wrapper is collected, even after ``close()``. Release those
    # handles before the caller rotates or deletes the source database.
    gc.collect()
    return evidence_path
