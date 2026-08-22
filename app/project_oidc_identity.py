"""Normalize already verified project OIDC claims into an identity-only principal."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from app.institutional_identity import (
    PROVIDER_ID_RE,
    InstitutionalIdentityError,
    VerifiedInstitutionalPrincipal,
)


_CLAIM_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")


class ProjectOidcIdentityError(RuntimeError):
    """Stable fail-closed OIDC error without claim or provider detail."""


def _bounded_ascii(value: object, *, minimum: int, maximum: int) -> bool:
    return bool(
        isinstance(value, str)
        and minimum <= len(value) <= maximum
        and all(
            not character.isspace() and 32 < ord(character) < 127
            for character in value
        )
    )


def _valid_https_issuer(value: object) -> bool:
    if not _bounded_ascii(value, minimum=9, maximum=2048) or "\\" in value:
        return False
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and hostname
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


@dataclass(frozen=True)
class ProjectOidcPolicy:
    """Non-secret policy for one approved project-controlled OIDC client."""

    provider_id: str
    issuer: str
    client_id: str
    required_acr: str
    username_claim: str = "preferred_username"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.provider_id, str)
            or not PROVIDER_ID_RE.fullmatch(self.provider_id)
            or not _valid_https_issuer(self.issuer)
            or not _bounded_ascii(self.client_id, minimum=1, maximum=255)
            or not _bounded_ascii(self.required_acr, minimum=1, maximum=128)
            or not isinstance(self.username_claim, str)
            or not _CLAIM_NAME_RE.fullmatch(self.username_claim)
        ):
            raise ProjectOidcIdentityError("project_oidc_policy_invalid")


def _validate_audience(policy: ProjectOidcPolicy, claims: Mapping[str, object]) -> None:
    audience = claims.get("aud")
    if isinstance(audience, str):
        valid = audience == policy.client_id
    elif isinstance(audience, list):
        valid = bool(
            1 <= len(audience) <= 16
            and all(isinstance(value, str) for value in audience)
            and len(set(audience)) == len(audience)
            and policy.client_id in audience
            and (
                len(audience) == 1
                or claims.get("azp") == policy.client_id
            )
        )
    else:
        valid = False
    if not valid:
        raise ProjectOidcIdentityError("project_oidc_audience_mismatch")


def _authentication_time(value: object) -> datetime:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ProjectOidcIdentityError("project_oidc_authentication_time_invalid")
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OSError, OverflowError, ValueError):
        raise ProjectOidcIdentityError(
            "project_oidc_authentication_time_invalid"
        ) from None


def principal_from_verified_oidc_claims(
    policy: ProjectOidcPolicy,
    claims: Mapping[str, object],
) -> VerifiedInstitutionalPrincipal:
    """Build a principal from claims already verified by a qualified OIDC client.

    This function does not accept or verify a raw token. Provider authorization
    claims are intentionally ignored; Study Membership supplies role and centre.
    """
    if not isinstance(policy, ProjectOidcPolicy):
        raise ProjectOidcIdentityError("project_oidc_policy_invalid")
    if not isinstance(claims, Mapping):
        raise ProjectOidcIdentityError("project_oidc_claims_invalid")
    if claims.get("iss") != policy.issuer:
        raise ProjectOidcIdentityError("project_oidc_issuer_mismatch")
    _validate_audience(policy, claims)
    if claims.get("acr") != policy.required_acr:
        raise ProjectOidcIdentityError("project_oidc_mfa_required")

    authenticated_at = _authentication_time(claims.get("auth_time"))
    subject_id = claims.get("sub")
    username = claims.get(policy.username_claim)
    if not isinstance(subject_id, str) or not isinstance(username, str):
        raise ProjectOidcIdentityError("project_oidc_claims_invalid")
    try:
        return VerifiedInstitutionalPrincipal(
            provider_id=policy.provider_id,
            subject_id=subject_id,
            username=username,
            authenticated_at=authenticated_at,
            mfa_authenticated=True,
        )
    except InstitutionalIdentityError:
        raise ProjectOidcIdentityError("project_oidc_claims_invalid") from None
