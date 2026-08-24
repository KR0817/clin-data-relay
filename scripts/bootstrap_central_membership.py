"""Bootstrap, correct, or contain the first Central Data Manager membership."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import json
import os
import sys
from typing import Any

from app.institutional_identity import (
    InstitutionalIdentityError,
    institutional_principal_id_from_subject,
)
from app.postgres_repository import PostgresConfigurationError, PostgresRepositoryError
from app.postgres_study_membership_repository import (
    PostgresStudyMembershipRepository,
    StudyMembershipRepositoryError,
)


MAX_INPUT_BYTES = 8 * 1024
INPUT_ERROR = "study_membership_bootstrap_input_invalid"
UNAVAILABLE_ERROR = "study_membership_bootstrap_unavailable"
BOOTSTRAP_CONFIRMATION = "BOOTSTRAP_FIRST_CENTRAL_DATA_MANAGER"
ROLLBACK_CONFIRMATION = "ROLLBACK_UNUSED_CENTRAL_DATA_MANAGER_BOOTSTRAP"
EMERGENCY_CONFIRMATION = "EMERGENCY_DEACTIVATE_BOOTSTRAP_CENTRAL_DATA_MANAGER"
BOOTSTRAP_FIELDS = frozenset(
    {
        "action",
        "subject_id",
        "operator_id",
        "membership_expires_at",
        "confirmation",
    }
)
ROLLBACK_FIELDS = frozenset(
    {
        "action",
        "membership_id",
        "operator_id",
        "reason",
        "confirmation",
    }
)
EMERGENCY_FIELDS = frozenset(
    {
        "action",
        "membership_id",
        "operator_id",
        "incident_reference",
        "reason",
        "confirmation",
    }
)
SAFE_ERROR_CODES = frozenset(
    {
        "postgres_dsn_required",
        "postgres_dsn_invalid",
        "postgres_tls_verify_full_required",
        "postgres_nonlocal_unverified_tls_forbidden",
        "postgres_server_version_unavailable",
        "postgres_server_version_unsupported",
        "postgres_schema_too_new",
        "postgres_migration_ledger_invalid",
        "postgres_repository_unavailable",
        "study_membership_actor_invalid",
        "study_membership_reason_invalid",
        "study_membership_time_invalid",
        "study_membership_bootstrap_invalid",
        "study_membership_bootstrap_closed",
        "study_membership_bootstrap_not_found",
        "study_membership_bootstrap_already_used",
        "study_membership_emergency_invalid",
        "study_membership_emergency_not_found",
        "study_membership_emergency_already_inactive",
        "study_membership_repository_unavailable",
    }
)


def _error(code: str) -> tuple[int, dict[str, object]]:
    return 1, {"status": "error", "code": code}


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _parse_document(payload_text: str) -> dict[str, object]:
    if not isinstance(payload_text, str) or len(payload_text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError(INPUT_ERROR)
    document = json.loads(payload_text, object_pairs_hook=_strict_object)
    if not isinstance(document, dict):
        raise ValueError(INPUT_ERROR)
    return document


def _required_environment(environ: Mapping[str, str]) -> tuple[str, str, str]:
    values = tuple(
        environ.get(name, "").strip()
        for name in (
            "COMPANION_POSTGRES_DSN",
            "COMPANION_ENV",
            "COMPANION_OIDC_PROVIDER_ID",
        )
    )
    if any(not value for value in values):
        raise ValueError(INPUT_ERROR)
    return values


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        raise ValueError(INPUT_ERROR)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(INPUT_ERROR) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(INPUT_ERROR)
    return parsed.astimezone(UTC)


def _clock(value: datetime | None) -> datetime:
    resolved = datetime.now(UTC) if value is None else value
    if not isinstance(resolved, datetime) or resolved.tzinfo is None or resolved.utcoffset() is None:
        raise ValueError(INPUT_ERROR)
    return resolved.astimezone(UTC)


def execute_command(
    payload_text: str,
    *,
    environ: Mapping[str, str] = os.environ,
    repository_factory: Callable[..., PostgresStudyMembershipRepository] = (
        PostgresStudyMembershipRepository
    ),
    now: datetime | None = None,
) -> tuple[int, dict[str, object]]:
    """Execute one strict command without returning identity or connection material."""
    try:
        document = _parse_document(payload_text)
        action = document.get("action")
        expected_fields = (
            BOOTSTRAP_FIELDS
            if action == "bootstrap"
            else ROLLBACK_FIELDS
            if action == "rollback_unused_bootstrap"
            else EMERGENCY_FIELDS
            if action == "emergency_deactivate_bootstrap"
            else None
        )
        if expected_fields is None or set(document) != expected_fields:
            raise ValueError(INPUT_ERROR)
        dsn, environment, provider_id = _required_environment(environ)
        occurred_at = _clock(now)

        if action == "bootstrap":
            if document["confirmation"] != BOOTSTRAP_CONFIRMATION:
                raise ValueError(INPUT_ERROR)
            expires_at = _timestamp(document["membership_expires_at"])
            subject_id = document.pop("subject_id")
            principal_id = institutional_principal_id_from_subject(
                provider_id=provider_id,
                subject_id=subject_id,
            )
            subject_id = None
        elif action == "rollback_unused_bootstrap":
            if document["confirmation"] != ROLLBACK_CONFIRMATION:
                raise ValueError(INPUT_ERROR)
        elif document["confirmation"] != EMERGENCY_CONFIRMATION:
            raise ValueError(INPUT_ERROR)

        repository = repository_factory(dsn, environment=environment)
        repository.prepare()
        if action == "bootstrap":
            record = repository.bootstrap_first_central_data_manager(
                provider_id,
                principal_id,
                actor_username=document["operator_id"],
                granted_at=occurred_at,
                expires_at=expires_at,
            )
            return 0, {
                "status": "granted",
                "membership_id": record.id,
                "role": record.membership.role,
                "centre_code": record.membership.centre_code,
                "valid_from": record.membership.valid_from.isoformat(),
                "expires_at": record.membership.expires_at.isoformat(),
            }

        if action == "rollback_unused_bootstrap":
            record = repository.rollback_unused_central_data_manager_bootstrap(
                document["membership_id"],
                actor_username=document["operator_id"],
                reason=document["reason"],
                rolled_back_at=occurred_at,
            )
            return 0, {
                "status": "rolled_back",
                "membership_id": record.id,
                "active": record.active,
            }

        record = repository.emergency_deactivate_bootstrap_central_data_manager(
            document["membership_id"],
            actor_username=document["operator_id"],
            incident_reference=document["incident_reference"],
            reason=document["reason"],
            deactivated_at=occurred_at,
        )
        return 0, {
            "status": "deactivated",
            "membership_id": record.id,
            "active": record.active,
        }
    except (json.JSONDecodeError, UnicodeError, ValueError, InstitutionalIdentityError):
        return _error(INPUT_ERROR)
    except (
        PostgresConfigurationError,
        PostgresRepositoryError,
        StudyMembershipRepositoryError,
    ) as error:
        code = str(error)
        return _error(code if code in SAFE_ERROR_CODES else UNAVAILABLE_ERROR)
    except Exception:
        return _error(UNAVAILABLE_ERROR)


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            exit_code, response = _error(INPUT_ERROR)
        else:
            exit_code, response = execute_command(raw.decode("utf-8"))
    except (AttributeError, UnicodeError, OSError):
        exit_code, response = _error(INPUT_ERROR)
    print(json.dumps(response, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
