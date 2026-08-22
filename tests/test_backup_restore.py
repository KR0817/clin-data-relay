from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from app.backup import backup_database
from app.main import create_app
from app.persistence import Database


def test_backup_script_creates_hash_and_verified_restore_evidence(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE synthetic_records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO synthetic_records (value) VALUES ('synthetic')")
    output_directory = tmp_path / "backups"
    script = Path(__file__).resolve().parents[1] / "scripts" / "backup_companion_database.py"

    completed = subprocess.run(
        [sys.executable, str(script), "--source", str(source), "--output-dir", str(output_directory)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    evidence_path = Path(completed.stdout.strip())
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    backup_path = output_directory / evidence["backup_filename"]
    assert backup_path.is_file()
    assert evidence["restore_integrity_check"] == "ok"
    assert hashlib.sha256(backup_path.read_bytes()).hexdigest() == evidence["backup_sha256"]
    assert evidence["source_database_name"] == "source.db"
    assert "source_database_path" not in evidence


def test_companion_backup_exports_and_rechecks_audit_chain_anchor(tmp_path: Path) -> None:
    source = tmp_path / "companion.db"
    database = Database(source)
    database.initialise()
    with database.connect() as connection:
        database.append_audit_event(
            connection,
            candidate_id=None,
            centre_code="SITE_A",
            event_type="backup_anchor_test",
            actor_username="tester@example.test",
            details={"bounded": True},
        )

    evidence_path = backup_database(source, tmp_path / "backups")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert evidence["audit_chain_anchor"]["event_count"] == 1
    assert len(evidence["audit_chain_anchor"]["head_hash"]) == 64


def test_companion_backup_refuses_a_tampered_audit_chain(tmp_path: Path) -> None:
    source = tmp_path / "tampered.db"
    database = Database(source)
    database.initialise()
    with database.connect() as connection:
        database.append_audit_event(
            connection,
            candidate_id=None,
            centre_code="SITE_A",
            event_type="before_tamper",
            actor_username="tester@example.test",
            details={"value": "original"},
        )
    with sqlite3.connect(source) as connection:
        connection.execute(
            "UPDATE audit_events SET details_json = ? WHERE event_type = 'before_tamper'",
            ('{"value":"changed"}',),
        )

    with pytest.raises(RuntimeError, match="backup_audit_chain_verification_failed"):
        backup_database(source, tmp_path / "backups")


def test_health_is_explicitly_blocked_for_unqualified_production(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "health.db", environment="test")
    with TestClient(app) as client:
        health = client.get("/api/health")

    assert health.status_code == 200
    readiness = health.json()["production_readiness"]
    assert readiness["status"] == "BLOCK"
    assert readiness["environment"] == "test"
    assert readiness["gates"]["synthetic_data_only"] is False
    assert readiness["gates"]["https"] is False
    assert health.json()["quality_rule_version"] == "clinical-quality-v1"
    assert "active_dictionary_release" in health.json()


def test_health_reports_verified_backup_restore_evidence(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "health-with-backup.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE synthetic_records (id INTEGER PRIMARY KEY)")
    output_directory = tmp_path / "backups"
    script = Path(__file__).resolve().parents[1] / "scripts" / "backup_companion_database.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--source", str(database_path), "--output-dir", str(output_directory)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    monkeypatch.setenv("COMPANION_BACKUP_DIRECTORY", str(output_directory))

    app = create_app(database_path=database_path, environment="test")
    with TestClient(app) as client:
        readiness = client.get("/api/health").json()["production_readiness"]

    assert readiness["gates"]["backup_restore_evidence"] is True
    assert readiness["latest_backup_completed_at"]
    assert readiness["status"] == "BLOCK"


def test_security_retention_reports_configured_policy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("COMPANION_ORIGINAL_RETENTION_DAYS", "45")
    app = create_app(database_path=tmp_path / "retention.db", environment="test")
    with TestClient(app) as client:
        headers = {
            "Authorization": "Bearer " + client.post(
                "/api/auth/login",
                json={"username": "central-data-manager@example.test", "password": "demo-password"},
            ).json()["access_token"]
        }
        response = client.get("/api/security/retention", headers=headers)

    assert response.status_code == 200
    assert response.json()["original_retention_days"] == 45
    assert response.json()["purged_source_count"] == 0
