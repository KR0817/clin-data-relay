from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.institutional_identity import (
    StudyMembership,
    VerifiedInstitutionalPrincipal,
    institutional_principal_id,
    verified_principal_link,
)
from app.postgres_institutional_session_repository import (
    InstitutionalSessionRepositoryError,
    PostgresInstitutionalSessionRepository,
)
from app.postgres_study_membership_repository import PostgresStudyMembershipRepository


def principal(*, authenticated_at: datetime) -> VerifiedInstitutionalPrincipal:
    unique = uuid4().hex
    return VerifiedInstitutionalPrincipal(
        provider_id="hospital-session-contract",
        subject_id=f"employee-{unique}",
        username=f"investigator-{unique}@example.test",
        authenticated_at=authenticated_at,
        mfa_authenticated=True,
    )


def grant_membership(
    repository: PostgresStudyMembershipRepository,
    verified_principal: VerifiedInstitutionalPrincipal,
    *,
    now: datetime,
    expires_at: datetime,
):
    return repository.grant(
        StudyMembership(
            provider_id=verified_principal.provider_id,
            principal_id=institutional_principal_id(verified_principal),
            role="site_investigator",
            centre_code="SITE_SESSION",
            active=True,
            valid_from=now - timedelta(minutes=1),
            expires_at=expires_at,
        ),
        actor_username="central-manager@example.test",
        granted_at=now - timedelta(minutes=1),
    )


def test_invalid_or_malformed_session_input_fails_before_database_io() -> None:
    repository = PostgresInstitutionalSessionRepository(
        "postgresql://127.0.0.1/unavailable?sslmode=disable",
        environment="test",
    )

    assert repository.resolve_session("not-a-session-token", now=datetime.now(UTC)) is None
    assert repository.revoke_session(
        "not-a-session-token",
        revoked_at=datetime.now(UTC),
    ) is False

    with pytest.raises(
        InstitutionalSessionRepositoryError,
        match="^institutional_session_time_invalid$",
    ):
        repository.resolve_session(
            "cdrs_" + "a" * 43,
            now=datetime(2026, 8, 23, 10, 0),
        )

    with pytest.raises(
        InstitutionalSessionRepositoryError,
        match="^institutional_session_time_invalid$",
    ):
        repository.create_session_from_link(
            verified_principal_link(principal(authenticated_at=datetime.now(UTC))),
            issued_at=datetime(2026, 8, 23, 10, 0),
        )


@pytest.mark.postgres
def test_postgres_institutional_session_lifecycle_contract() -> None:
    dsn = os.getenv("CLINDATA_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("CLINDATA_TEST_POSTGRES_DSN is not configured")

    membership_repository = PostgresStudyMembershipRepository(dsn, environment="test")
    session_repository = PostgresInstitutionalSessionRepository(dsn, environment="test")
    session_repository.prepare()
    now = datetime.now(UTC).replace(microsecond=0)
    verified_principal = principal(authenticated_at=now)
    membership = grant_membership(
        membership_repository,
        verified_principal,
        now=now,
        expires_at=now + timedelta(hours=2),
    )

    first = session_repository.create_session_from_link(
        verified_principal_link(verified_principal),
        issued_at=now,
    )

    assert first.token.startswith("cdrs_")
    assert len(first.token) == 48
    assert first.token not in repr(first)
    assert first.expires_at == now + timedelta(hours=2)
    assert session_repository.resolve_session(first.token, now=now) == first.user

    before_revoke = session_repository.verify_audit_chain().head_hash
    assert session_repository.revoke_session(
        first.token,
        revoked_at=now + timedelta(minutes=1),
    ) is True
    after_revoke = session_repository.verify_audit_chain().head_hash
    assert after_revoke != before_revoke
    assert session_repository.revoke_session(
        first.token,
        revoked_at=now + timedelta(minutes=2),
    ) is True
    assert session_repository.verify_audit_chain().head_hash == after_revoke
    assert session_repository.resolve_session(
        first.token,
        now=now + timedelta(minutes=2),
    ) is None

    second = session_repository.create_session(
        verified_principal,
        issued_at=now + timedelta(minutes=3),
    )
    assert session_repository.resolve_session(
        second.token,
        now=now + timedelta(minutes=3),
    ) == second.user

    membership_repository.deactivate(
        membership.id,
        actor_username="central-manager@example.test",
        reason="Investigator access withdrawn from the approved study team.",
        deactivated_at=now + timedelta(minutes=4),
    )
    assert session_repository.resolve_session(
        second.token,
        now=now + timedelta(minutes=4),
    ) is None
    assert session_repository.verify_audit_chain().ok is True


@pytest.mark.postgres
def test_session_expiry_cannot_outlive_provider_authentication_freshness() -> None:
    dsn = os.getenv("CLINDATA_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("CLINDATA_TEST_POSTGRES_DSN is not configured")

    membership_repository = PostgresStudyMembershipRepository(dsn, environment="test")
    session_repository = PostgresInstitutionalSessionRepository(dsn, environment="test")
    session_repository.prepare()
    now = datetime.now(UTC).replace(microsecond=0)
    unmatched_principal = principal(authenticated_at=now)
    with pytest.raises(
        InstitutionalSessionRepositoryError,
        match="^institutional_session_membership_required$",
    ):
        session_repository.create_session(unmatched_principal, issued_at=now)

    verified_principal = principal(authenticated_at=now - timedelta(hours=7))
    grant_membership(
        membership_repository,
        verified_principal,
        now=now,
        expires_at=now + timedelta(days=30),
    )

    with pytest.raises(
        InstitutionalSessionRepositoryError,
        match="^institutional_identity_mfa_required$",
    ):
        session_repository.create_session(
            replace(verified_principal, mfa_authenticated=False),
            issued_at=now,
        )

    session = session_repository.create_session(verified_principal, issued_at=now)

    assert session.expires_at == now + timedelta(hours=1)
