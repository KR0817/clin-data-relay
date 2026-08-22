"""Fail-closed production readiness evaluation.

Environment variables describe runtime configuration, not proof that an
institutional control exists. This module combines both signals with a small,
secret-free evidence manifest whose entries expire and point to externally
controlled approval or validation records.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping


MANIFEST_PROTOCOL = "clinical-edc-production-evidence-v1"
MAX_MANIFEST_BYTES = 256 * 1024
_FORBIDDEN_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "private_key",
    "api_key",
    "credential",
    "clinical_value",
    "patient",
)
_EVIDENCE_REF_RE = re.compile(r"^[A-Za-z0-9._:/-]{3,240}$")

MANIFEST_GATE_NAMES = (
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


def _env_true(name: str) -> bool:
    return os.getenv(name, "").strip().casefold() == "true"


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = str(key).casefold()
            allowed_control_key = lowered in {"managed_secrets"}
            if not allowed_control_key and any(part in lowered for part in _FORBIDDEN_KEY_PARTS):
                return True
            if _contains_forbidden_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def load_evidence_manifest(path: Path | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    """Read and validate a bounded, non-secret approval evidence manifest."""

    manifest_path = path or Path(os.getenv("COMPANION_PRODUCTION_EVIDENCE_FILE", ".runtime/production-evidence.json"))
    result: dict[str, Any] = {
        "status": "missing",
        "approved_gates": [],
        "expired_gates": [],
        "errors": [],
    }
    def fail(code: str) -> dict[str, Any]:
        result["status"] = "invalid"
        result["errors"].append(code)
        return result
    if not manifest_path.is_file():
        return fail("evidence_manifest_missing")
    try:
        if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
            return fail("evidence_manifest_too_large")
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return fail("evidence_manifest_unreadable")
    if not isinstance(document, dict):
        return fail("evidence_manifest_invalid_schema")
    if _contains_forbidden_key(document):
        return fail("evidence_manifest_contains_sensitive_key")
    if document.get("protocol") != MANIFEST_PROTOCOL or document.get("manifest_version") != 1:
        return fail("evidence_manifest_version_unsupported")
    gates = document.get("gates")
    if not isinstance(gates, dict):
        return fail("evidence_manifest_gates_required")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    for name in MANIFEST_GATE_NAMES:
        entry = gates.get(name)
        if not isinstance(entry, dict) or entry.get("status") != "approved":
            continue
        evidence_ref = entry.get("evidence_ref")
        checked_at = _parse_timestamp(entry.get("checked_at"))
        expires_at = _parse_timestamp(entry.get("expires_at"))
        if not isinstance(evidence_ref, str) or not _EVIDENCE_REF_RE.fullmatch(evidence_ref):
            result["errors"].append(f"evidence_manifest_{name}_reference_invalid")
            continue
        if checked_at is None or expires_at is None or expires_at <= checked_at:
            result["errors"].append(f"evidence_manifest_{name}_timestamp_invalid")
            continue
        if expires_at <= current:
            result["expired_gates"].append(name)
            continue
        result["approved_gates"].append(name)
    result["status"] = "valid" if not result["errors"] else "invalid"
    result["manifest_version"] = document.get("manifest_version")
    result["expires_at"] = max(
        (_parse_timestamp(gates[name].get("expires_at")) for name in result["approved_gates"] if isinstance(gates.get(name), dict)),
        default=None,
    )
    if isinstance(result["expires_at"], datetime):
        result["expires_at"] = result["expires_at"].isoformat()
    return result


def evaluate_production_readiness(
    *,
    environment: str,
    deployment_profile: str,
    database_backend: str,
    authority_target_kind: str,
    backup_restore_evidence: bool,
    disk_encryption_enabled: bool,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Return gate booleans and stable blocking reasons without secrets."""

    strict = environment.casefold() not in {"test", "development"}
    approved = set(manifest.get("approved_gates", []))

    def manifest_gate(name: str) -> bool:
        return not strict or name in approved

    data_mode = os.getenv("COMPANION_DATA_MODE", "synthetic").strip().casefold()
    secret_provider = os.getenv("COMPANION_SECRET_PROVIDER", "local_file").strip().casefold()
    auth_mode = os.getenv("COMPANION_AUTH_MODE", "demo").strip().casefold()
    gates = {
        "synthetic_data_only": data_mode == "real_approved" and manifest_gate("data_governance") and _env_true("DATA_GOVERNANCE_APPROVED"),
        "https": _env_true("PRODUCTION_HTTPS_ENABLED") and manifest_gate("https"),
        "managed_secrets": _env_true("MANAGED_SECRETS_CONFIGURED") and secret_provider not in {"", "local_file", "env"} and manifest_gate("managed_secrets"),
        "identity_provider": _env_true("IDENTITY_PROVIDER_APPROVED") and auth_mode in {"oidc", "saml"} and manifest_gate("identity_provider"),
        "central_repository": deployment_profile == "central" and database_backend == "postgresql" and manifest_gate("central_repository"),
        "backup_restore_evidence": backup_restore_evidence and manifest_gate("backup_restore"),
        "disk_encryption": disk_encryption_enabled and manifest_gate("data_governance"),
        "validation_evidence": _env_true("VALIDATION_EVIDENCE_APPROVED") and manifest_gate("validation"),
        "authority_edc_configured": authority_target_kind == "libreclinica" and _env_true("AUTHORITY_EDC_QUALIFIED") and manifest_gate("authority_edc"),
        "monitoring": _env_true("MONITORING_CONFIGURED") and manifest_gate("monitoring"),
        "incident_response": _env_true("INCIDENT_RESPONSE_APPROVED") and manifest_gate("incident_response"),
        "sop_training": _env_true("SOP_TRAINING_APPROVED") and manifest_gate("sop_training"),
        "disaster_recovery": _env_true("DISASTER_RECOVERY_TESTED") and manifest_gate("disaster_recovery"),
    }
    reasons: dict[str, str] = {}
    for name, passed in gates.items():
        if passed:
            continue
        if name == "central_repository" and database_backend != "postgresql":
            reasons[name] = "qualified_postgresql_repository_required"
        elif strict and name not in approved:
            reasons[name] = "unexpired_evidence_manifest_entry_required"
        elif name == "managed_secrets":
            reasons[name] = "managed_secret_provider_required"
        elif name == "identity_provider":
            reasons[name] = "approved_oidc_or_saml_mfa_required"
        elif name == "authority_edc_configured":
            reasons[name] = "qualified_authority_edc_evidence_required"
        else:
            reasons[name] = "runtime_control_not_configured"
    return {
        "status": "PASS" if all(gates.values()) else "BLOCK",
        "strict": strict,
        "gates": gates,
        "blocking_reasons": reasons,
        "evidence_manifest": {
            "status": manifest.get("status"),
            "approved_gate_count": len(approved),
            "expired_gates": list(manifest.get("expired_gates", [])),
            "errors": list(manifest.get("errors", [])),
        },
    }
