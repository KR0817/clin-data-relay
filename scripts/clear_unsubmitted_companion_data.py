from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Back up the companion database and remove records without a confirmed LibreClinica submission."
    )
    parser.add_argument("--database", type=Path, default=Path("data/companion.db"))
    parser.add_argument("--backup-dir", type=Path, default=Path(".runtime"))
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply the cleanup. Without this flag the script only reports the exact scope.",
    )
    return parser.parse_args()


def placeholders(values: set[str]) -> str:
    return ",".join("?" for _ in values)


def audit_hash_chain_enabled(connection: sqlite3.Connection) -> bool:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(audit_events)").fetchall()
    }
    return {"prev_hash", "event_hash"} <= columns


def cleanup_scope(connection: sqlite3.Connection) -> dict[str, object]:
    retained_candidate_ids = {
        row[0]
        for row in connection.execute(
            """
            SELECT DISTINCT c.id
            FROM candidates c
            JOIN transfer_requests t ON t.candidate_id = c.id
            WHERE t.status = 'submitted' AND t.external_reference IS NOT NULL
            """
        )
    }
    all_candidate_ids = {row[0] for row in connection.execute("SELECT id FROM candidates")}
    deleted_candidate_ids = all_candidate_ids - retained_candidate_ids
    retained_transfer_ids = {
        row[0]
        for row in connection.execute(
            "SELECT id FROM transfer_requests WHERE status = 'submitted' AND external_reference IS NOT NULL"
        )
    }
    all_transfer_ids = {row[0] for row in connection.execute("SELECT id FROM transfer_requests")}
    deleted_transfer_ids = all_transfer_ids - retained_transfer_ids

    retained_source_ids: set[str] = set()
    if retained_candidate_ids:
        retained_source_ids.update(
            row[0]
            for row in connection.execute(
                f"SELECT DISTINCT source_file_id FROM candidates WHERE id IN ({placeholders(retained_candidate_ids)})",
                tuple(sorted(retained_candidate_ids)),
            )
        )

    drafts = [
        {
            "id": row[0],
            "original_source_file_id": row[1],
            "derivative_source_file_id": row[2],
        }
        for row in connection.execute(
            "SELECT id, original_source_file_id, derivative_source_file_id FROM deidentification_drafts"
        )
    ]
    changed = True
    while changed:
        changed = False
        for draft in drafts:
            pair = {draft["original_source_file_id"], draft["derivative_source_file_id"]}
            if retained_source_ids.intersection(pair) and not pair.issubset(retained_source_ids):
                retained_source_ids.update(pair)
                changed = True

    retained_draft_ids = {
        draft["id"]
        for draft in drafts
        if draft["original_source_file_id"] in retained_source_ids
        or draft["derivative_source_file_id"] in retained_source_ids
    }
    all_draft_ids = {draft["id"] for draft in drafts}
    deleted_draft_ids = all_draft_ids - retained_draft_ids
    all_source_ids = {row[0] for row in connection.execute("SELECT id FROM source_files")}
    deleted_source_ids = all_source_ids - retained_source_ids

    deleted_null_candidate_audit_ids: set[str] = set()
    for audit_id, details_json in connection.execute(
        "SELECT id, details_json FROM audit_events WHERE candidate_id IS NULL"
    ):
        try:
            details = json.loads(details_json)
        except json.JSONDecodeError:
            continue
        referenced_values = {str(value) for value in details.values() if isinstance(value, str)}
        if (
            referenced_values.intersection(deleted_source_ids)
            or referenced_values.intersection(deleted_draft_ids)
        ):
            deleted_null_candidate_audit_ids.add(audit_id)

    return {
        "retained_candidate_ids": retained_candidate_ids,
        "deleted_candidate_ids": deleted_candidate_ids,
        "retained_transfer_ids": retained_transfer_ids,
        "deleted_transfer_ids": deleted_transfer_ids,
        "retained_source_ids": retained_source_ids,
        "deleted_source_ids": deleted_source_ids,
        "retained_draft_ids": retained_draft_ids,
        "deleted_draft_ids": deleted_draft_ids,
        "deleted_null_candidate_audit_ids": deleted_null_candidate_audit_ids,
    }


def public_summary(scope: dict[str, object]) -> dict[str, int]:
    return {
        "retained_submitted_candidates": len(scope["retained_candidate_ids"]),
        "deleted_unsubmitted_candidates": len(scope["deleted_candidate_ids"]),
        "retained_submitted_transfers": len(scope["retained_transfer_ids"]),
        "deleted_unsubmitted_transfers": len(scope["deleted_transfer_ids"]),
        "retained_provenance_sources": len(scope["retained_source_ids"]),
        "deleted_orphan_source_records": len(scope["deleted_source_ids"]),
        "retained_deidentification_drafts": len(scope["retained_draft_ids"]),
        "deleted_orphan_deidentification_drafts": len(scope["deleted_draft_ids"]),
        "deleted_source_level_audit_events": len(scope["deleted_null_candidate_audit_ids"]),
    }


def delete_ids(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    values: set[str],
) -> None:
    if not values:
        return
    connection.execute(
        f"DELETE FROM {table} WHERE {column} IN ({placeholders(values)})",
        tuple(sorted(values)),
    )


def main() -> int:
    args = parse_args()
    database_path = args.database.resolve()
    if not database_path.is_file():
        raise SystemExit(f"Database not found: {database_path}")

    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    scope = cleanup_scope(connection)
    summary = public_summary(scope)
    if not args.execute:
        print(json.dumps({"mode": "dry_run", **summary}, ensure_ascii=False, indent=2))
        connection.close()
        return 0

    if audit_hash_chain_enabled(connection):
        connection.close()
        raise SystemExit(
            "hash_chained_audit_cannot_be_deleted: use retention cleanup for source bytes; "
            "reviewed audit events are append-only"
        )

    backup_dir = args.backup_dir.resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"companion-before-unsubmitted-clear-{timestamp}.db"
    backup_connection = sqlite3.connect(backup_path)
    connection.backup(backup_connection)
    backup_connection.close()

    try:
        connection.execute("BEGIN IMMEDIATE")
        delete_ids(
            connection,
            "audit_events",
            "candidate_id",
            scope["deleted_candidate_ids"],
        )
        delete_ids(
            connection,
            "audit_events",
            "id",
            scope["deleted_null_candidate_audit_ids"],
        )
        delete_ids(
            connection,
            "transfer_requests",
            "id",
            scope["deleted_transfer_ids"],
        )
        delete_ids(
            connection,
            "candidates",
            "id",
            scope["deleted_candidate_ids"],
        )
        delete_ids(
            connection,
            "deidentification_drafts",
            "id",
            scope["deleted_draft_ids"],
        )
        delete_ids(
            connection,
            "source_files",
            "id",
            scope["deleted_source_ids"],
        )
        violations = list(connection.execute("PRAGMA foreign_key_check"))
        if violations:
            raise RuntimeError(f"Foreign-key violations after cleanup: {violations}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    print(
        json.dumps(
            {
                "mode": "executed",
                "backup_path": str(backup_path),
                "physical_upload_files_deleted": 0,
                **summary,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
