"""Post-verification institutional identity authorization boundary."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9._-]{1,63}$")
CENTRE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_-]{1,31}$")
STUDY_ROLES = frozenset(
    {
        "site_investigator",
        "principal_investigator",
        "central_data_manager",
        "monitor",
        "auditor",
    }
)
MAX_AUTHENTICATION_AGE = timedelta(hours=8)
MAX_POSITIVE_CLOCK_SKEW = timedelta(minutes=5)


class InstitutionalIdentityError(RuntimeError):
    """Stable fail-closed identity error without provider or user detail."""


def _normalise_time(value: datetime, error_code: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise InstitutionalIdentityError(error_code)
    return value.astimezone(UTC)


def _bounded_opaque(value: object, *, minimum: int, maximum: int) -> bool:
    return bool(
        isinstance(value, str)
        and minimum <= len(value) <= maximum
        and all(not character.isspace() and 32 < ord(character) < 127 for character in value)
    )


@dataclass(frozen=True)
class VerifiedInstitutionalPrincipal:
    provider_id: str
    subject_id: str
    username: str
    authenticated_at: datetime
    mfa_authenticated: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.provider_id, str)
            or not PROVIDER_ID_RE.fullmatch(self.provider_id)
            or not _bounded_opaque(self.subject_id, minimum=1, maximum=255)
            or not _bounded_opaque(self.username, minimum=3, maximum=320)
            or not isinstance(self.mfa_authenticated, bool)
        ):
            raise InstitutionalIdentityError("institutional_identity_claim_invalid")
        object.__setattr__(
            self,
            "authenticated_at",
            _normalise_time(
                self.authenticated_at,
                "institutional_identity_claim_invalid",
            ),
        )


@dataclass(frozen=True)
class StudyMembership:
    provider_id: str
    subject_id: str
    role: str
    centre_code: str | None
    active: bool
    valid_from: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.provider_id, str)
            or not PROVIDER_ID_RE.fullmatch(self.provider_id)
            or not _bounded_opaque(self.subject_id, minimum=1, maximum=255)
            or not isinstance(self.active, bool)
            or self.role not in STUDY_ROLES
        ):
            raise InstitutionalIdentityError("institutional_identity_membership_invalid")
        if self.role == "site_investigator":
            if not isinstance(self.centre_code, str) or not CENTRE_CODE_RE.fullmatch(
                self.centre_code
            ):
                raise InstitutionalIdentityError("institutional_identity_role_scope_invalid")
        elif self.centre_code is not None:
            raise InstitutionalIdentityError("institutional_identity_role_scope_invalid")
        valid_from = _normalise_time(
            self.valid_from,
            "institutional_identity_membership_invalid",
        )
        expires_at = _normalise_time(
            self.expires_at,
            "institutional_identity_membership_invalid",
        )
        if expires_at <= valid_from:
            raise InstitutionalIdentityError("institutional_identity_membership_invalid")
        object.__setattr__(self, "valid_from", valid_from)
        object.__setattr__(self, "expires_at", expires_at)


@dataclass(frozen=True)
class InstitutionalUser:
    id: str
    username: str
    role: str
    centre_code: str | None


def authorize_institutional_principal(
    principal: VerifiedInstitutionalPrincipal,
    membership: StudyMembership,
    *,
    now: datetime,
) -> InstitutionalUser:
    resolved_now = _normalise_time(now, "institutional_identity_clock_invalid")
    if not principal.mfa_authenticated:
        raise InstitutionalIdentityError("institutional_identity_mfa_required")
    if principal.authenticated_at > resolved_now + MAX_POSITIVE_CLOCK_SKEW:
        raise InstitutionalIdentityError(
            "institutional_identity_authentication_time_invalid"
        )
    if resolved_now - principal.authenticated_at > MAX_AUTHENTICATION_AGE:
        raise InstitutionalIdentityError("institutional_identity_authentication_stale")
    if (
        principal.provider_id != membership.provider_id
        or principal.subject_id != membership.subject_id
    ):
        raise InstitutionalIdentityError("institutional_identity_membership_mismatch")
    if not membership.active:
        raise InstitutionalIdentityError("institutional_identity_membership_inactive")
    if not membership.valid_from <= resolved_now < membership.expires_at:
        raise InstitutionalIdentityError(
            "institutional_identity_membership_not_effective"
        )
    digest = hashlib.sha256(
        f"{principal.provider_id}\0{principal.subject_id}".encode("utf-8")
    ).hexdigest()
    return InstitutionalUser(
        id=f"institutional:{digest}",
        username=principal.username,
        role=membership.role,
        centre_code=membership.centre_code,
    )
