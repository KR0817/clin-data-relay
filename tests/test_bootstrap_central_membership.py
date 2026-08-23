from __future__ import annotations

import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
import subprocess
import sys
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.institutional_identity import StudyMembership, VerifiedPrincipalLink
from app.postgres_institutional_session_repository import (
    PostgresInstitutionalSessionRepository,
)
from app.postgres_study_membership_repository import (
    PostgresStudyMembershipRepository,
    StudyMembershipRecord,
    StudyMembershipRepositoryError,
)
from scripts.bootstrap_central_membership import execute_command


FIXED_NOW = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
FIXED_EXPIRY = datetime(2027, 8, 24, 8, 0, tzinfo=UTC)
OPERATOR_ID = "operator:approved-admin"
PROVIDER_ID = "project-keycloak"
TEST_DSN = "postgresql://bootstrap-secret@127.0.0.1/test?sslmode=disable"


class FakeMembershipRepository:
    def __init__(self) -> None:
        self.bootstrap_arguments: dict[str, object] | None = None
        self.rollback_arguments: dict[str, object] | None = None

    def prepare(self) -> None:
        return None

    def bootstrap_first_central_data_manager(
        self,
        provider_id: str,
        principal_id: str,
        *,
        actor_username: str,
        granted_at: datetime,
        expires_at: datetime,
    ) -> StudyMembershipRecord:
        self.bootstrap_arguments = {
            "provider_id": provider_id,
            "principal_id": principal_id,
            "actor_username": actor_username,
            "granted_at": granted_at,
            "expires_at": expires_at,
        }
        return StudyMembershipRecord(
            id="membership-bootstrap-001",
            membership=StudyMembership(
                provider_id=provider_id,
                principal_id=principal_id,
                role="central_data_manager",
                centre_code=None,
                active=True,
                valid_from=granted_at,
                expires_at=expires_at,
            ),
            created_by=actor_username,
            created_at=granted_at,
            deactivated_by=None,
            deactivated_at=None,
            deactivation_reason=None,
        )

    def rollback_unused_central_data_manager_bootstrap(
        self,
        membership_id: str,
        *,
        actor_username: str,
        reason: str,
        rolled_back_at: datetime,
    ) -> StudyMembershipRecord:
        self.rollback_arguments = {
            "membership_id": membership_id,
            "actor_username": actor_username,
            "reason": reason,
            "rolled_back_at": rolled_back_at,
        }
        return StudyMembershipRecord(
            id=membership_id,
            membership=StudyMembership(
                provider_id=PROVIDER_ID,
                principal_id="institutional:" + "a" * 64,
                role="central_data_manager",
                centre_code=None,
                active=False,
                valid_from=FIXED_NOW - timedelta(minutes=1),
                expires_at=FIXED_EXPIRY,
            ),
            created_by=OPERATOR_ID,
            created_at=FIXED_NOW - timedelta(minutes=1),
            deactivated_by=actor_username,
            deactivated_at=rolled_back_at,
            deactivation_reason=reason,
        )


def command_environment() -> dict[str, str]:
    return {
        "COMPANION_POSTGRES_DSN": TEST_DSN,
        "COMPANION_ENV": "test",
        "COMPANION_OIDC_PROVIDER_ID": PROVIDER_ID,
    }


def repository_factory(
    repository: FakeMembershipRepository,
):
    def create(dsn: str, *, environment: str) -> FakeMembershipRepository:
        assert dsn == TEST_DSN
        assert environment == "test"
        return repository

    return create


@pytest.fixture
def postgres_bootstrap_dsn() -> Iterator[str]:
    base_dsn = os.getenv("CLINDATA_TEST_POSTGRES_DSN", "").strip()
    if not base_dsn:
        pytest.skip("CLINDATA_TEST_POSTGRES_DSN is not configured")
    schema_name = f"bootstrap_contract_{uuid4().hex}"
    with psycopg.connect(base_dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
    existing_options = str(
        conninfo_to_dict(base_dsn).get("options") or ""
    ).strip()
    isolated_dsn = make_conninfo(
        base_dsn,
        options=f"{existing_options} -csearch_path={schema_name}".strip(),
    )
    try:
        yield isolated_dsn
    finally:
        with psycopg.connect(base_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


def test_bootstrap_command_derives_identity_and_returns_only_safe_membership_data() -> None:
    raw_subject = "qualified-client-subject-SENSITIVE-4815"
    repository = FakeMembershipRepository()
    raw_input = json.dumps(
        {
            "action": "bootstrap",
            "subject_id": raw_subject,
            "operator_id": OPERATOR_ID,
            "membership_expires_at": "2027-08-24T08:00:00Z",
            "confirmation": "BOOTSTRAP_FIRST_CENTRAL_DATA_MANAGER",
        }
    )

    exit_code, response = execute_command(
        raw_input,
        environ=command_environment(),
        repository_factory=repository_factory(repository),
        now=FIXED_NOW,
    )

    assert exit_code == 0
    assert response == {
        "status": "granted",
        "membership_id": "membership-bootstrap-001",
        "role": "central_data_manager",
        "centre_code": None,
        "valid_from": "2026-08-24T08:00:00+00:00",
        "expires_at": "2027-08-24T08:00:00+00:00",
    }
    assert repository.bootstrap_arguments is not None
    assert repository.bootstrap_arguments["provider_id"] == PROVIDER_ID
    assert str(repository.bootstrap_arguments["principal_id"]).startswith(
        "institutional:"
    )
    assert raw_subject not in repr(repository.bootstrap_arguments)
    assert raw_subject not in repr(response)
    assert TEST_DSN not in repr(response)
    assert "principal_id" not in response
    assert "username" not in response


def test_rollback_command_returns_no_identity_or_connection_material() -> None:
    repository = FakeMembershipRepository()
    membership_id = "membership-bootstrap-001"
    reason = "Correcting the witnessed pre-login subject mapping."
    raw_input = json.dumps(
        {
            "action": "rollback_unused_bootstrap",
            "membership_id": membership_id,
            "operator_id": OPERATOR_ID,
            "reason": reason,
            "confirmation": "ROLLBACK_UNUSED_CENTRAL_DATA_MANAGER_BOOTSTRAP",
        }
    )

    exit_code, response = execute_command(
        raw_input,
        environ=command_environment(),
        repository_factory=repository_factory(repository),
        now=FIXED_NOW,
    )

    assert exit_code == 0
    assert response == {
        "status": "rolled_back",
        "membership_id": membership_id,
        "active": False,
    }
    assert repository.rollback_arguments == {
        "membership_id": membership_id,
        "actor_username": OPERATOR_ID,
        "reason": reason,
        "rolled_back_at": FIXED_NOW,
    }
    assert PROVIDER_ID not in repr(response)
    assert TEST_DSN not in repr(response)
    assert "principal_id" not in response


@pytest.mark.parametrize(
    "payload",
    [
        {
            "action": "bootstrap",
            "subject_id": "qualified-subject",
            "operator_id": OPERATOR_ID,
            "membership_expires_at": "2027-08-24T08:00:00Z",
        },
        {
            "action": "bootstrap",
            "subject_id": "qualified-subject",
            "operator_id": OPERATOR_ID,
            "membership_expires_at": "2027-08-24T08:00:00Z",
            "confirmation": "yes",
        },
        {
            "action": "bootstrap",
            "subject_id": "qualified-subject",
            "operator_id": OPERATOR_ID,
            "membership_expires_at": "2027-08-24T08:00:00Z",
            "confirmation": "BOOTSTRAP_FIRST_CENTRAL_DATA_MANAGER",
            "unexpected": True,
        },
        {
            "action": "bootstrap",
            "subject_id": "qualified-subject",
            "operator_id": OPERATOR_ID,
            "membership_expires_at": "2027-08-24T08:00:00",
            "confirmation": "BOOTSTRAP_FIRST_CENTRAL_DATA_MANAGER",
        },
        {
            "action": "rollback_unused_bootstrap",
            "membership_id": "membership-bootstrap-001",
            "operator_id": OPERATOR_ID,
            "reason": "Correcting the witnessed pre-login subject mapping.",
            "confirmation": "yes",
        },
    ],
)
def test_command_rejects_non_exact_or_unconfirmed_documents_before_repository_io(
    payload: dict[str, object],
) -> None:
    def fail_if_created(*_args, **_kwargs):
        raise AssertionError("invalid commands must not open the repository")

    exit_code, response = execute_command(
        json.dumps(payload),
        environ=command_environment(),
        repository_factory=fail_if_created,
        now=FIXED_NOW,
    )

    assert exit_code == 1
    assert response == {
        "status": "error",
        "code": "study_membership_bootstrap_input_invalid",
    }
    assert "qualified-subject" not in repr(response)
    assert TEST_DSN not in repr(response)


@pytest.mark.parametrize(
    "raw_input",
    [
        "not-json",
        "[]",
        "{}",
        (
            '{"action":"bootstrap","subject_id":"first",'
            '"subject_id":"second","operator_id":"operator:approved-admin",'
            '"membership_expires_at":"2027-08-24T08:00:00Z",'
            '"confirmation":"BOOTSTRAP_FIRST_CENTRAL_DATA_MANAGER"}'
        ),
        json.dumps(
            {
                "action": "rollback_unused_bootstrap",
                "membership_id": "membership-bootstrap-001",
                "operator_id": OPERATOR_ID,
                "reason": "x" * (8 * 1024),
                "confirmation": "ROLLBACK_UNUSED_CENTRAL_DATA_MANAGER_BOOTSTRAP",
            }
        ),
    ],
)
def test_command_rejects_non_object_or_malformed_json_without_echoing_it(
    raw_input: str,
) -> None:
    def fail_if_created(*_args, **_kwargs):
        raise AssertionError("invalid commands must not open the repository")

    exit_code, response = execute_command(
        raw_input,
        environ=command_environment(),
        repository_factory=fail_if_created,
        now=FIXED_NOW,
    )

    assert exit_code == 1
    assert response == {
        "status": "error",
        "code": "study_membership_bootstrap_input_invalid",
    }
    assert raw_input not in repr(response)


def test_command_rejects_missing_environment_before_repository_io() -> None:
    raw_input = json.dumps(
        {
            "action": "bootstrap",
            "subject_id": "qualified-subject",
            "operator_id": OPERATOR_ID,
            "membership_expires_at": "2027-08-24T08:00:00Z",
            "confirmation": "BOOTSTRAP_FIRST_CENTRAL_DATA_MANAGER",
        }
    )

    exit_code, response = execute_command(
        raw_input,
        environ={},
        repository_factory=lambda *_args, **_kwargs: pytest.fail(
            "missing configuration must not open the repository"
        ),
        now=FIXED_NOW,
    )

    assert exit_code == 1
    assert response == {
        "status": "error",
        "code": "study_membership_bootstrap_input_invalid",
    }


def test_command_does_not_echo_untrusted_repository_error_text() -> None:
    raw_subject = "qualified-client-subject-SENSITIVE-9931"
    raw_input = json.dumps(
        {
            "action": "bootstrap",
            "subject_id": raw_subject,
            "operator_id": OPERATOR_ID,
            "membership_expires_at": "2027-08-24T08:00:00Z",
            "confirmation": "BOOTSTRAP_FIRST_CENTRAL_DATA_MANAGER",
        }
    )

    def failing_repository(*_args, **_kwargs):
        raise StudyMembershipRepositoryError(
            f"untrusted:{raw_subject}:{TEST_DSN}"
        )

    exit_code, response = execute_command(
        raw_input,
        environ=command_environment(),
        repository_factory=failing_repository,
        now=FIXED_NOW,
    )

    assert exit_code == 1
    assert response == {
        "status": "error",
        "code": "study_membership_bootstrap_unavailable",
    }
    assert raw_subject not in repr(response)
    assert TEST_DSN not in repr(response)


def test_command_process_returns_one_redacted_json_line() -> None:
    sentinel = "malformed-SENSITIVE-subject-5881"
    project_root = Path(__file__).resolve().parents[1]

    completed = subprocess.run(
        [sys.executable, "scripts/bootstrap_central_membership.py"],
        cwd=project_root,
        input=sentinel,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert completed.stderr == ""
    assert completed.stdout.count("\n") == 1
    assert json.loads(completed.stdout) == {
        "status": "error",
        "code": "study_membership_bootstrap_input_invalid",
    }
    assert sentinel not in completed.stdout


@pytest.mark.postgres
def test_postgres_first_membership_bootstrap_is_atomic_and_closes_after_session(
    postgres_bootstrap_dsn: str,
) -> None:
    dsn = postgres_bootstrap_dsn
    preparing_repository = PostgresStudyMembershipRepository(dsn, environment="test")
    preparing_repository.prepare()
    now = datetime.now(UTC).replace(microsecond=0)
    provider_id = "project-bootstrap-contract"
    principals = (
        "institutional:" + "1" * 64,
        "institutional:" + "2" * 64,
    )
    barrier = Barrier(len(principals))

    def attempt(principal_id: str):
        repository = PostgresStudyMembershipRepository(dsn, environment="test")
        barrier.wait()
        try:
            record = repository.bootstrap_first_central_data_manager(
                provider_id,
                principal_id,
                actor_username=OPERATOR_ID,
                granted_at=now,
                expires_at=now + timedelta(days=30),
            )
            return "granted", record
        except StudyMembershipRepositoryError as error:
            return "error", str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(attempt, principals))

    granted = [value for status, value in outcomes if status == "granted"]
    errors = [value for status, value in outcomes if status == "error"]
    assert len(granted) == 1
    assert errors == ["study_membership_bootstrap_closed"]

    membership = granted[0]
    assert isinstance(membership, StudyMembershipRecord)
    assert membership.membership.role == "central_data_manager"
    assert membership.membership.centre_code is None

    rolled_back = preparing_repository.rollback_unused_central_data_manager_bootstrap(
        membership.id,
        actor_username=OPERATOR_ID,
        reason="Correcting the witnessed pre-login subject mapping.",
        rolled_back_at=now + timedelta(seconds=1),
    )
    audit_head_after_rollback = preparing_repository.verify_audit_chain().head_hash
    repeated = preparing_repository.rollback_unused_central_data_manager_bootstrap(
        membership.id,
        actor_username=OPERATOR_ID,
        reason="No duplicate rollback event should be created.",
        rolled_back_at=now + timedelta(seconds=2),
    )
    assert rolled_back.active is False
    assert repeated == rolled_back
    assert preparing_repository.verify_audit_chain().head_hash == audit_head_after_rollback

    membership = preparing_repository.bootstrap_first_central_data_manager(
        provider_id,
        "institutional:" + "3" * 64,
        actor_username=OPERATOR_ID,
        granted_at=now + timedelta(seconds=3),
        expires_at=now + timedelta(days=30),
    )

    session_repository = PostgresInstitutionalSessionRepository(
        dsn,
        environment="test",
    )
    session = session_repository.create_session_from_link(
        VerifiedPrincipalLink(
            provider_id=provider_id,
            principal_id=membership.membership.principal_id,
            username="central-manager@example.test",
            authenticated_at=now,
            mfa_authenticated=True,
        ),
        issued_at=now + timedelta(seconds=4),
    )
    assert session.user.role == "central_data_manager"
    assert session.user.centre_code is None

    with pytest.raises(
        StudyMembershipRepositoryError,
        match="^study_membership_bootstrap_already_used$",
    ):
        preparing_repository.rollback_unused_central_data_manager_bootstrap(
            membership.id,
            actor_username=OPERATOR_ID,
            reason="This correction is no longer permitted after session use.",
            rolled_back_at=now + timedelta(seconds=5),
        )

    assert session_repository.resolve_session(
        session.token,
        now=now + timedelta(seconds=5),
    ) == session.user


@pytest.mark.postgres
def test_generic_deactivation_cannot_reopen_central_bootstrap(
    postgres_bootstrap_dsn: str,
) -> None:
    repository = PostgresStudyMembershipRepository(
        postgres_bootstrap_dsn,
        environment="test",
    )
    repository.prepare()
    now = datetime.now(UTC).replace(microsecond=0)
    membership = repository.bootstrap_first_central_data_manager(
        PROVIDER_ID,
        "institutional:" + "4" * 64,
        actor_username=OPERATOR_ID,
        granted_at=now,
        expires_at=now + timedelta(days=30),
    )
    repository.deactivate(
        membership.id,
        actor_username=OPERATOR_ID,
        reason="Generic deactivation must not authorize a replacement bootstrap.",
        deactivated_at=now + timedelta(seconds=1),
    )

    with pytest.raises(
        StudyMembershipRepositoryError,
        match="^study_membership_bootstrap_invalid$",
    ):
        repository.rollback_unused_central_data_manager_bootstrap(
            membership.id,
            actor_username=OPERATOR_ID,
            reason="A generic deactivation is not a dedicated bootstrap rollback.",
            rolled_back_at=now + timedelta(seconds=2),
        )

    with pytest.raises(
        StudyMembershipRepositoryError,
        match="^study_membership_bootstrap_closed$",
    ):
        repository.bootstrap_first_central_data_manager(
            PROVIDER_ID,
            "institutional:" + "5" * 64,
            actor_username=OPERATOR_ID,
            granted_at=now + timedelta(seconds=3),
            expires_at=now + timedelta(days=30),
        )

    normal_membership = repository.grant(
        StudyMembership(
            provider_id=PROVIDER_ID,
            principal_id="institutional:" + "6" * 64,
            role="central_data_manager",
            centre_code=None,
            active=True,
            valid_from=now + timedelta(seconds=4),
            expires_at=now + timedelta(days=30),
        ),
        actor_username=OPERATOR_ID,
        granted_at=now + timedelta(seconds=4),
    )
    with pytest.raises(
        StudyMembershipRepositoryError,
        match="^study_membership_bootstrap_invalid$",
    ):
        repository.rollback_unused_central_data_manager_bootstrap(
            normal_membership.id,
            actor_username=OPERATOR_ID,
            reason="Normal grants are outside the bootstrap rollback path.",
            rolled_back_at=now + timedelta(seconds=5),
        )


@pytest.mark.postgres
def test_any_session_history_closes_bootstrap_recovery(
    postgres_bootstrap_dsn: str,
) -> None:
    membership_repository = PostgresStudyMembershipRepository(
        postgres_bootstrap_dsn,
        environment="test",
    )
    session_repository = PostgresInstitutionalSessionRepository(
        postgres_bootstrap_dsn,
        environment="test",
    )
    membership_repository.prepare()
    now = datetime.now(UTC).replace(microsecond=0)
    bootstrap_membership = (
        membership_repository.bootstrap_first_central_data_manager(
            PROVIDER_ID,
            "institutional:" + "7" * 64,
            actor_username=OPERATOR_ID,
            granted_at=now,
            expires_at=now + timedelta(days=30),
        )
    )
    site_principal_id = "institutional:" + "8" * 64
    site_membership = membership_repository.grant(
        StudyMembership(
            provider_id=PROVIDER_ID,
            principal_id=site_principal_id,
            role="site_investigator",
            centre_code="SITE_BOOTSTRAP",
            active=True,
            valid_from=now,
            expires_at=now + timedelta(days=30),
        ),
        actor_username=OPERATOR_ID,
        granted_at=now,
    )
    session_repository.create_session_from_link(
        VerifiedPrincipalLink(
            provider_id=PROVIDER_ID,
            principal_id=site_principal_id,
            username="site-investigator@example.test",
            authenticated_at=now,
            mfa_authenticated=True,
        ),
        issued_at=now + timedelta(seconds=1),
    )

    with pytest.raises(
        StudyMembershipRepositoryError,
        match="^study_membership_bootstrap_already_used$",
    ):
        membership_repository.rollback_unused_central_data_manager_bootstrap(
            bootstrap_membership.id,
            actor_username=OPERATOR_ID,
            reason="Any Companion Session permanently closes recovery.",
            rolled_back_at=now + timedelta(seconds=2),
        )
    with pytest.raises(
        StudyMembershipRepositoryError,
        match="^study_membership_bootstrap_invalid$",
    ):
        membership_repository.rollback_unused_central_data_manager_bootstrap(
            site_membership.id,
            actor_username=OPERATOR_ID,
            reason="Site memberships are never bootstrap rollback targets.",
            rolled_back_at=now + timedelta(seconds=2),
        )
    with pytest.raises(
        StudyMembershipRepositoryError,
        match="^study_membership_bootstrap_closed$",
    ):
        membership_repository.bootstrap_first_central_data_manager(
            PROVIDER_ID,
            "institutional:" + "9" * 64,
            actor_username=OPERATOR_ID,
            granted_at=now + timedelta(seconds=3),
            expires_at=now + timedelta(days=30),
        )
