from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from app.production_readiness import evaluate_production_readiness, load_evidence_manifest


def _manifest_payload(*, expires_at: str) -> dict[str, object]:
    gates = {
        name: {
            "status": "approved",
            "evidence_ref": f"ticket:{name}-001",
            "checked_at": "2026-08-01T00:00:00+00:00",
            "expires_at": expires_at,
        }
        for name in (
            "data_governance",
            "https",
            "managed_secrets",
            "identity_provider",
            "central_repository",
            "backup_restore",
            "validation",
            "authority_edc",
            "monitoring",
            "incident_response",
            "sop_training",
            "disaster_recovery",
        )
    }
    return {"protocol": "clinical-edc-production-evidence-v1", "manifest_version": 1, "gates": gates}


def test_manifest_accepts_unexpired_secret_free_entries(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    path.write_text(
        json.dumps(_manifest_payload(expires_at="2099-01-01T00:00:00+00:00")),
        encoding="utf-8",
    )

    result = load_evidence_manifest(path, now=datetime(2026, 8, 14, tzinfo=UTC))

    assert result["status"] == "valid"
    assert len(result["approved_gates"]) == 12
    assert not result["errors"]


def test_manifest_rejects_sensitive_keys_and_expired_entries(tmp_path: Path) -> None:
    document = _manifest_payload(expires_at="2026-08-13T00:00:00+00:00")
    document["private_key"] = "must never be here"
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    result = load_evidence_manifest(path, now=datetime(2026, 8, 14, tzinfo=UTC))

    assert result["status"] == "invalid"
    assert "evidence_manifest_contains_sensitive_key" in result["errors"]


def test_production_evaluation_requires_real_runtime_controls() -> None:
    readiness = evaluate_production_readiness(
        environment="production",
        deployment_profile="local",
        database_backend="sqlite",
        authority_target_kind="libreclinica",
        backup_restore_evidence=True,
        disk_encryption_enabled=True,
        identity_provider_ready=False,
        manifest={"status": "missing", "approved_gates": [], "expired_gates": [], "errors": []},
    )

    assert readiness["status"] == "BLOCK"
    assert readiness["gates"]["central_repository"] is False
    assert readiness["blocking_reasons"]["central_repository"] == "qualified_postgresql_repository_required"
    assert readiness["blocking_reasons"]["identity_provider"] == "unexpired_evidence_manifest_entry_required"


def test_identity_gate_requires_a_real_runtime_adapter_capability(
    monkeypatch,
) -> None:
    monkeypatch.setenv("IDENTITY_PROVIDER_APPROVED", "true")
    monkeypatch.setenv("COMPANION_AUTH_MODE", "oidc")
    manifest = {
        "status": "valid",
        "approved_gates": ["identity_provider"],
        "expired_gates": [],
        "errors": [],
    }
    arguments = {
        "environment": "production",
        "deployment_profile": "central",
        "database_backend": "postgresql",
        "authority_target_kind": "libreclinica",
        "backup_restore_evidence": True,
        "disk_encryption_enabled": True,
        "manifest": manifest,
    }

    blocked = evaluate_production_readiness(
        **arguments,
        identity_provider_ready=False,
    )
    ready = evaluate_production_readiness(
        **arguments,
        identity_provider_ready=True,
    )

    assert blocked["gates"]["identity_provider"] is False
    assert blocked["blocking_reasons"]["identity_provider"] == (
        "qualified_identity_adapter_required"
    )
    assert ready["gates"]["identity_provider"] is True
    assert "identity_provider" not in ready["blocking_reasons"]
