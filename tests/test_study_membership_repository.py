from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.institutional_identity import (
    StudyMembership,
    VerifiedInstitutionalPrincipal,
    institutional_principal_id,
)
from app.postgres_study_membership_repository import (
    PostgresStudyMembershipRepository,
    StudyMembershipRepositoryError,
)


def principal() -> VerifiedInstitutionalPrincipal:
    unique = uuid4().hex
    return VerifiedInstitutionalPrincipal(
        provider_id="hospital-contract",
        subject_id=f"employee-{unique}",
        username=f"investigator-{unique}@example.test",
        authenticated_at=datetime.now(UTC),
        mfa_authenticated=True,
    )


def membership(
    verified_principal: VerifiedInstitutionalPrincipal,
    *,
    role: str = "site_investigator",
    centre_code: str | None = "SITE_CONTRACT",
) -> StudyMembership:
    now = datetime.now(UTC)
    return StudyMembership(
        provider_id=verified_principal.provider_id,
        principal_id=institutional_principal_id(verified_principal),
        role=role,
        centre_code=centre_code,
        active=True,
        valid_from=now - timedelta(minutes=1),
        expires_at=now + timedelta(days=30),
    )


def test_membership_repository_rejects_unbounded_lifecycle_input_before_io() -> None:
    repository = PostgresStudyMembershipRepository(
        "postgresql://127.0.0.1/unavailable?sslmode=disable",
        environment="test",
    )
    verified_principal = principal()

    with pytest.raises(
        StudyMembershipRepositoryError,
        match="^study_membership_actor_invalid$",
    ):
        repository.grant(
            membership(verified_principal),
            actor_username="invalid actor",
            granted_at=datetime.now(UTC),
        )

    with pytest.raises(
        StudyMembershipRepositoryError,
        match="^study_membership_reason_invalid$",
    ):
        repository.deactivate(
            str(uuid4()),
            actor_username="central-manager@example.test",
            reason=" ",
            deactivated_at=datetime.now(UTC),
        )


@pytest.mark.postgres
def test_postgres_study_membership_lifecycle_and_audit_contract() -> None:
    dsn = os.getenv("CLINDATA_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("CLINDATA_TEST_POSTGRES_DSN is not configured")

    repository = PostgresStudyMembershipRepository(dsn, environment="test")
    repository.prepare()
    verified_principal = principal()
    original_subject = verified_principal.subject_id
    actor = "central-manager@example.test"
    now = datetime.now(UTC)

    first = repository.grant(
        membership(verified_principal),
        actor_username=actor,
        granted_at=now,
    )
    found = repository.find_active(verified_principal)

    assert found == first
    assert original_subject not in repr(first)
    assert first.membership.principal_id == institutional_principal_id(verified_principal)

    with pytest.raises(
        StudyMembershipRepositoryError,
        match="^study_membership_active_exists$",
    ):
        repository.grant(
            membership(verified_principal),
            actor_username=actor,
            granted_at=now + timedelta(seconds=1),
        )

    inactive = repository.deactivate(
        first.id,
        actor_username=actor,
        reason="Investigator left the approved study team.",
        deactivated_at=now + timedelta(seconds=2),
    )
    head_after_deactivation = repository.verify_audit_chain().head_hash
    repeated = repository.deactivate(
        first.id,
        actor_username=actor,
        reason="No duplicate event should be created.",
        deactivated_at=now + timedelta(seconds=3),
    )

    assert inactive.active is False
    assert repeated == inactive
    assert repository.verify_audit_chain().head_hash == head_after_deactivation
    assert repository.find_active(verified_principal) is None

    replacement = repository.grant(
        membership(
            verified_principal,
            role="central_data_manager",
            centre_code=None,
        ),
        actor_username=actor,
        granted_at=now + timedelta(seconds=4),
    )
    assert replacement.id != first.id
    assert repository.find_active(verified_principal) == replacement

    verification = repository.verify_audit_chain()
    assert verification.ok is True
    assert verification.checked >= 3
