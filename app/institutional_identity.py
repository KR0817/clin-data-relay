"""Post-verification institutional identity authorization boundary."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9._-]{1,63}$")
CENTRE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_-]{1,31}$")
PRINCIPAL_ID_RE = re.compile(r"^institutional:[a-f0-9]{64}$")
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


def institutional_principal_id(principal: VerifiedInstitutionalPrincipal) -> str:
    """Derive the sole persisted identity link from a verified principal."""
    return institutional_principal_id_from_subject(
        provider_id=principal.provider_id,
        subject_id=principal.subject_id,
    )


def institutional_principal_id_from_subject(
    *,
    provider_id: str,
    subject_id: str,
) -> str:
    """Derive a pseudonymous identity link without asserting authentication."""
    if (
        not isinstance(provider_id, str)
        or not PROVIDER_ID_RE.fullmatch(provider_id)
        or not _bounded_opaque(subject_id, minimum=1, maximum=255)
    ):
        raise InstitutionalIdentityError("institutional_identity_claim_invalid")
    digest = hashlib.sha256(
        f"{provider_id}\0{subject_id}".encode("utf-8")
    ).hexdigest()
    return f"institutional:{digest}"


@dataclass(frozen=True)
class VerifiedPrincipalLink:
    """Pseudonymous verified identity projection without the provider subject."""

    provider_id: str
    principal_id: str
    username: str
    authenticated_at: datetime
    mfa_authenticated: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.provider_id, str)
            or not PROVIDER_ID_RE.fullmatch(self.provider_id)
            or not isinstance(self.principal_id, str)
            or not PRINCIPAL_ID_RE.fullmatch(self.principal_id)
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


def verified_principal_link(
    principal: VerifiedInstitutionalPrincipal,
) -> VerifiedPrincipalLink:
    """Remove the raw provider subject after deriving its pseudonymous link."""
    return VerifiedPrincipalLink(
        provider_id=principal.provider_id,
        principal_id=institutional_principal_id(principal),
        username=principal.username,
        authenticated_at=principal.authenticated_at,
        mfa_authenticated=principal.mfa_authenticated,
    )


@dataclass(frozen=True)
class StudyMembership:
    provider_id: str
    principal_id: str
    role: str
    centre_code: str | None
    active: bool
    valid_from: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.provider_id, str)
            or not PROVIDER_ID_RE.fullmatch(self.provider_id)
            or not isinstance(self.principal_id, str)
            or not PRINCIPAL_ID_RE.fullmatch(self.principal_id)
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
    return authorize_verified_principal_link(
        verified_principal_link(principal),
        membership,
        now=now,
    )


def authorize_verified_principal_link(
    principal: VerifiedPrincipalLink,
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
        or principal.principal_id != membership.principal_id
    ):
        raise InstitutionalIdentityError("institutional_identity_membership_mismatch")
    if not membership.active:
        raise InstitutionalIdentityError("institutional_identity_membership_inactive")
    if not membership.valid_from <= resolved_now < membership.expires_at:
        raise InstitutionalIdentityError(
            "institutional_identity_membership_not_effective"
        )
    return InstitutionalUser(
        id=membership.principal_id,
        username=principal.username,
        role=membership.role,
        centre_code=membership.centre_code,
    )
