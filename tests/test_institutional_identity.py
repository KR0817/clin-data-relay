from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.institutional_identity import (
    InstitutionalIdentityError,
    StudyMembership,
    VerifiedInstitutionalPrincipal,
    authorize_institutional_principal,
    institutional_principal_id,
)


def test_mfa_verified_principal_receives_only_the_matching_study_membership() -> None:
    principal = VerifiedInstitutionalPrincipal(
        provider_id="hospital-a",
        subject_id="employee-001",
        username="investigator@example.test",
        authenticated_at=datetime(2026, 8, 22, 8, 0, tzinfo=UTC),
        mfa_authenticated=True,
    )
    membership = StudyMembership(
        provider_id="hospital-a",
        principal_id=institutional_principal_id(principal),
        role="site_investigator",
        centre_code="SITE_A",
        active=True,
        valid_from=datetime(2026, 8, 1, 0, 0, tzinfo=UTC),
        expires_at=datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
    )

    user = authorize_institutional_principal(
        principal,
        membership,
        now=datetime(2026, 8, 22, 9, 0, tzinfo=UTC),
    )

    assert user.id == (
        "institutional:"
        "7fb79e14c5bc8de6673b432c8d00efd3625ce65d965b103181bec2dfb4f41e04"
    )
    assert user.username == "investigator@example.test"
    assert user.role == "site_investigator"
    assert user.centre_code == "SITE_A"
    assert principal.subject_id not in repr(user)
    assert principal.subject_id not in repr(membership)


def principal() -> VerifiedInstitutionalPrincipal:
    return VerifiedInstitutionalPrincipal(
        provider_id="hospital-a",
        subject_id="employee-001",
        username="investigator@example.test",
        authenticated_at=datetime(2026, 8, 22, 8, 0, tzinfo=UTC),
        mfa_authenticated=True,
    )


def membership() -> StudyMembership:
    return StudyMembership(
        provider_id="hospital-a",
        principal_id=institutional_principal_id(principal()),
        role="site_investigator",
        centre_code="SITE_A",
        active=True,
        valid_from=datetime(2026, 8, 1, 0, 0, tzinfo=UTC),
        expires_at=datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("changed_principal", "expected_code"),
    (
        (
            replace(principal(), mfa_authenticated=False),
            "institutional_identity_mfa_required",
        ),
        (
            replace(
                principal(),
                authenticated_at=datetime(2026, 8, 22, 0, 59, tzinfo=UTC),
            ),
            "institutional_identity_authentication_stale",
        ),
        (
            replace(
                principal(),
                authenticated_at=datetime(2026, 8, 22, 9, 6, tzinfo=UTC),
            ),
            "institutional_identity_authentication_time_invalid",
        ),
    ),
)
def test_unverified_stale_or_future_authentication_fails_closed(
    changed_principal: VerifiedInstitutionalPrincipal,
    expected_code: str,
) -> None:
    with pytest.raises(InstitutionalIdentityError, match=f"^{expected_code}$"):
        authorize_institutional_principal(
            changed_principal,
            membership(),
            now=datetime(2026, 8, 22, 9, 0, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    ("changed_membership", "expected_code"),
    (
        (
            replace(membership(), principal_id="institutional:" + "a" * 64),
            "institutional_identity_membership_mismatch",
        ),
        (
            replace(membership(), active=False),
            "institutional_identity_membership_inactive",
        ),
        (
            replace(
                membership(),
                valid_from=datetime(2026, 8, 23, 0, 0, tzinfo=UTC),
                expires_at=datetime(2026, 9, 23, 0, 0, tzinfo=UTC),
            ),
            "institutional_identity_membership_not_effective",
        ),
        (
            replace(
                membership(),
                valid_from=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
                expires_at=datetime(2026, 8, 22, 9, 0, tzinfo=UTC),
            ),
            "institutional_identity_membership_not_effective",
        ),
    ),
)
def test_membership_identity_and_effective_period_fail_closed(
    changed_membership: StudyMembership,
    expected_code: str,
) -> None:
    with pytest.raises(InstitutionalIdentityError, match=f"^{expected_code}$"):
        authorize_institutional_principal(
            principal(),
            changed_membership,
            now=datetime(2026, 8, 22, 9, 0, tzinfo=UTC),
        )


def test_study_role_and_centre_shape_is_validated_before_authorization() -> None:
    with pytest.raises(
        InstitutionalIdentityError,
        match="^institutional_identity_role_scope_invalid$",
    ):
        replace(membership(), centre_code=None)
    with pytest.raises(
        InstitutionalIdentityError,
        match="^institutional_identity_role_scope_invalid$",
    ):
        replace(membership(), role="central_data_manager", centre_code="SITE_A")
    with pytest.raises(
        InstitutionalIdentityError,
        match="^institutional_identity_membership_invalid$",
    ):
        replace(membership(), role="super_admin", centre_code=None)


def test_global_membership_produces_an_existing_compatible_user_shape() -> None:
    global_membership = replace(
        membership(),
        role="central_data_manager",
        centre_code=None,
    )

    user = authorize_institutional_principal(
        principal(),
        global_membership,
        now=datetime(2026, 8, 22, 9, 0, tzinfo=UTC),
    )

    assert (user.username, user.role, user.centre_code) == (
        "investigator@example.test",
        "central_data_manager",
        None,
    )


def test_structural_claim_errors_are_bounded_and_do_not_echo_identity_values() -> None:
    with pytest.raises(InstitutionalIdentityError) as raised:
        replace(principal(), username="invalid username")

    assert str(raised.value) == "institutional_identity_claim_invalid"
    assert "invalid username" not in str(raised.value)


def test_principal_identifier_is_namespaced_deterministic_and_validated() -> None:
    first = institutional_principal_id(principal())
    second = institutional_principal_id(principal())

    assert first == second
    assert first.startswith("institutional:")
    assert len(first) == len("institutional:") + 64

    with pytest.raises(
        InstitutionalIdentityError,
        match="^institutional_identity_membership_invalid$",
    ):
        replace(membership(), principal_id="employee-001")


def test_authorization_rejects_naive_clock_input() -> None:
    with pytest.raises(
        InstitutionalIdentityError,
        match="^institutional_identity_clock_invalid$",
    ):
        authorize_institutional_principal(
            principal(),
            membership(),
            now=datetime(2026, 8, 22, 9, 0),
        )
