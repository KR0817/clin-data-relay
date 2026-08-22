"""Dry-run or explicitly purge expired original source bytes.

The database row, SHA-256 and audit trail remain. Only physical files whose
storage key is an original ``synthetic/`` upload are removed.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sqlite3

from app.persistence import Database


def source_path(database_path: Path, row: sqlite3.Row) -> Path:
    suffix = Path(str(row["storage_key"])).suffix
    return database_path.parent / "synthetic_uploads" / str(row["centre_code"]) / f"{row['id']}{suffix}"


def cleanup(database_path: Path, *, retention_days: int, execute: bool) -> dict[str, object]:
    if retention_days < 1 or retention_days > 3650:
        raise ValueError("retention_days_out_of_range")
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    database = Database(database_path)
    with database.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(source_files)")}
        if "content_purged_at" not in columns:
            connection.execute("ALTER TABLE source_files ADD COLUMN content_purged_at TEXT")
        audit_columns = {row["name"] for row in connection.execute("PRAGMA table_info(audit_events)")}
        if not {"prev_hash", "event_hash"} <= audit_columns:
            raise RuntimeError("audit_chain_required")
        candidates = []
        for row in connection.execute(
            """
            SELECT id, centre_code, storage_key, source_filename, sha256, created_at, content_purged_at
            FROM source_files
            WHERE storage_key LIKE 'synthetic/%' AND content_purged_at IS NULL
            """
        ):
            try:
                created_at = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=UTC)
            except ValueError:
                continue
            if created_at < cutoff:
                candidates.append((row, source_path(database_path, row)))
    report: dict[str, object] = {
        "mode": "execute" if execute else "dry_run",
        "retention_days": retention_days,
        "cutoff": cutoff.isoformat(),
        "eligible_count": len(candidates),
        "purged_count": 0,
        "missing_file_count": 0,
        "purged_source_ids": [],
    }
    if execute:
        purged_at = datetime.now(UTC).isoformat()
        with database.connect() as connection:
            for row, path in candidates:
                if path.is_file():
                    path.unlink()
                else:
                    report["missing_file_count"] = int(report["missing_file_count"]) + 1
                connection.execute(
                    "UPDATE source_files SET content_purged_at = ? WHERE id = ?",
                    (purged_at, row["id"]),
                )
                database.append_audit_event(
                    connection,
                    candidate_id=None,
                    centre_code=row["centre_code"],
                    event_type="original_source_content_purged",
                    actor_username="system:retention-cleanup",
                    created_at=purged_at,
                    details={
                        "source_file_id": row["id"],
                        "source_sha256": row["sha256"],
                        "retention_days": retention_days,
                    },
                )
                report["purged_source_ids"].append(row["id"])
        report["purged_count"] = len(candidates)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/companion.db"))
    parser.add_argument("--retention-days", type=int, default=30)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    report = cleanup(args.database.resolve(strict=True), retention_days=args.retention_days, execute=args.execute)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
