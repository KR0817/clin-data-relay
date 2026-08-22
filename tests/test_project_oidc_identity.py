from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.institutional_identity import VerifiedInstitutionalPrincipal
from app.project_oidc_identity import (
    ProjectOidcIdentityError,
    ProjectOidcPolicy,
    principal_from_verified_oidc_claims,
)


AUTH_TIME = 1_787_473_200


def policy() -> ProjectOidcPolicy:
    return ProjectOidcPolicy(
        provider_id="study-keycloak",
        issuer="https://identity.example.test/realms/clin-data-relay",
        client_id="clindata-relay-central",
        required_acr="study-mfa",
        username_claim="preferred_username",
    )


def verified_claims() -> dict[str, object]:
    return {
        "iss": "https://identity.example.test/realms/clin-data-relay",
        "aud": "clindata-relay-central",
        "sub": "2b0dfc86-51c1-48c8-964f-bce155a3e227",
        "preferred_username": "investigator-001",
        "auth_time": AUTH_TIME,
        "acr": "study-mfa",
    }


def test_verified_project_oidc_claims_create_identity_only_principal() -> None:
    claims = verified_claims()
    claims.update(
        {
            "groups": ["principal_investigator"],
            "realm_access": {"roles": ["central_data_manager"]},
            "role": "principal_investigator",
            "centre_code": "CENTRE-UNTRUSTED",
        }
    )

    principal = principal_from_verified_oidc_claims(policy(), claims)

    assert isinstance(principal, VerifiedInstitutionalPrincipal)
    assert principal.provider_id == "study-keycloak"
    assert principal.subject_id == "2b0dfc86-51c1-48c8-964f-bce155a3e227"
    assert principal.username == "investigator-001"
    assert principal.authenticated_at == datetime.fromtimestamp(AUTH_TIME, tz=UTC)
    assert principal.mfa_authenticated is True
    assert not hasattr(principal, "role")
    assert not hasattr(principal, "centre_code")


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("iss", "https://attacker.example/realms/other", "project_oidc_issuer_mismatch"),
        ("aud", "different-client", "project_oidc_audience_mismatch"),
        ("acr", "password-only", "project_oidc_mfa_required"),
    ],
)
def test_security_claim_mismatch_fails_with_bounded_code(
    field: str,
    value: object,
    expected_code: str,
) -> None:
    claims = verified_claims()
    claims[field] = value

    with pytest.raises(ProjectOidcIdentityError, match=f"^{expected_code}$"):
        principal_from_verified_oidc_claims(policy(), claims)


def test_multiple_audiences_require_exact_authorized_party() -> None:
    claims = verified_claims()
    claims["aud"] = ["clindata-relay-central", "account"]

    with pytest.raises(
        ProjectOidcIdentityError,
        match="^project_oidc_audience_mismatch$",
    ):
        principal_from_verified_oidc_claims(policy(), claims)

    claims["azp"] = "clindata-relay-central"
    principal = principal_from_verified_oidc_claims(policy(), claims)
    assert principal.username == "investigator-001"


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("sub", "", "project_oidc_claims_invalid"),
        ("preferred_username", "x", "project_oidc_claims_invalid"),
        ("auth_time", True, "project_oidc_authentication_time_invalid"),
        ("auth_time", "not-a-number", "project_oidc_authentication_time_invalid"),
        ("auth_time", -1, "project_oidc_authentication_time_invalid"),
    ],
)
def test_invalid_identity_claims_fail_closed(
    field: str,
    value: object,
    expected_code: str,
) -> None:
    claims = verified_claims()
    claims[field] = value

    with pytest.raises(ProjectOidcIdentityError, match=f"^{expected_code}$"):
        principal_from_verified_oidc_claims(policy(), claims)


def test_policy_is_non_secret_and_requires_https() -> None:
    configured = policy()
    assert not hasattr(configured, "client_secret")

    with pytest.raises(ProjectOidcIdentityError, match="^project_oidc_policy_invalid$"):
        ProjectOidcPolicy(
            provider_id="study-keycloak",
            issuer="http://identity.example.test/realms/clin-data-relay",
            client_id="clindata-relay-central",
            required_acr="study-mfa",
        )

    with pytest.raises(ProjectOidcIdentityError, match="^project_oidc_policy_invalid$"):
        ProjectOidcPolicy(
            provider_id="study-keycloak",
            issuer="https://[invalid-ipv6/realms/clin-data-relay",
            client_id="clindata-relay-central",
            required_acr="study-mfa",
        )


def test_errors_never_echo_claim_values_or_accept_raw_tokens() -> None:
    sentinel = "sensitive-investigator-value"
    claims = verified_claims()
    claims["sub"] = sentinel + " "

    with pytest.raises(ProjectOidcIdentityError) as raised:
        principal_from_verified_oidc_claims(policy(), claims)

    assert str(raised.value) == "project_oidc_claims_invalid"
    assert sentinel not in str(raised.value)

    with pytest.raises(
        ProjectOidcIdentityError,
        match="^project_oidc_claims_invalid$",
    ):
        principal_from_verified_oidc_claims(policy(), "raw.jwt.value")  # type: ignore[arg-type]
