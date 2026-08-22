"""Run the same fail-closed production preflight used by ``/api/health``."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys

from app.disk_security import disk_encryption_status
from app.production_readiness import evaluate_production_readiness, load_evidence_manifest
from app.runtime_config import RuntimeConfigurationError, RuntimeConfig


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _latest_backup_evidence(directory: Path) -> bool:
    try:
        evidence_paths = sorted(
            directory.glob("companion-*.evidence.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not evidence_paths or evidence_paths[0].stat().st_size > 64 * 1024:
            return False
        evidence = json.loads(evidence_paths[0].read_text(encoding="utf-8"))
        completed_at = datetime.fromisoformat(str(evidence.get("completed_at", "")).replace("Z", "+00:00"))
        age_hours = (datetime.now(UTC) - completed_at.astimezone(UTC)).total_seconds() / 3600
        backup_path = directory / str(evidence.get("backup_filename") or "")
        return (
            evidence.get("restore_integrity_check") == "ok"
            and isinstance(evidence.get("backup_sha256"), str)
            and len(evidence["backup_sha256"]) == 64
            and backup_path.is_file()
            and age_hours <= float(os.getenv("COMPANION_BACKUP_MAX_AGE_HOURS", "48"))
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-file", type=Path, default=None)
    arguments = parser.parse_args()
    try:
        runtime = RuntimeConfig.from_environment()
    except RuntimeConfigurationError as error:
        report = {"status": "BLOCK", "blocking_reasons": {"runtime_configuration": str(error)}}
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    backup_directory = Path(
        os.getenv("COMPANION_BACKUP_DIRECTORY", str(PROJECT_ROOT / ".runtime" / "backups"))
    )
    disk = disk_encryption_status(runtime.database_path)
    manifest = load_evidence_manifest(arguments.evidence_file)
    authority_kind = "libreclinica" if os.getenv("COMPANION_EDC_MODE", "").strip().casefold() == "libreclinica_soap" else "not_configured"
    report = evaluate_production_readiness(
        environment=runtime.environment,
        deployment_profile=runtime.deployment_profile,
        database_backend=runtime.database_backend,
        authority_target_kind=authority_kind,
        backup_restore_evidence=_latest_backup_evidence(backup_directory),
        disk_encryption_enabled=disk.get("status") == "enabled",
        identity_provider_ready=False,
        manifest=manifest,
    )
    report["runtime"] = {
        "environment": runtime.environment,
        "deployment_profile": runtime.deployment_profile,
        "database_backend": runtime.database_backend,
    }
    report["disk_encryption"] = disk
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
