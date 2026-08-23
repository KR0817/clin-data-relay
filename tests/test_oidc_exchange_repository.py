from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from app.institutional_identity import VerifiedPrincipalLink
from app.postgres_oidc_exchange_repository import (
    OidcExchangeRepositoryError,
    PostgresOidcExchangeRepository,
)


BROWSER_BINDING = "cdrb_" + "a" * 43


def principal_link() -> VerifiedPrincipalLink:
    return VerifiedPrincipalLink(
        provider_id="study-keycloak",
        principal_id="institutional:" + "b" * 64,
        username="investigator-001",
        authenticated_at=datetime(2026, 8, 24, 8, 0, tzinfo=UTC),
        mfa_authenticated=True,
    )


def test_malformed_exchange_inputs_fail_before_database_io() -> None:
    repository = PostgresOidcExchangeRepository(
        "postgresql://127.0.0.1/unavailable?sslmode=disable",
        environment="test",
    )

    assert repository.consume(
        "not-an-exchange",
        browser_binding=BROWSER_BINDING,
        consumed_at=datetime.now(UTC),
    ) is None

    with pytest.raises(
        OidcExchangeRepositoryError,
        match="^oidc_exchange_browser_binding_invalid$",
    ):
        repository.create(
            principal_link(),
            browser_binding="invalid binding",
            created_at=datetime.now(UTC),
        )


@pytest.mark.postgres
def test_postgres_login_exchange_is_browser_bound_short_lived_and_one_use() -> None:
    dsn = os.getenv("CLINDATA_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("CLINDATA_TEST_POSTGRES_DSN is not configured")

    repository = PostgresOidcExchangeRepository(dsn, environment="test")
    status = repository.prepare()
    assert status.schema_version == 7
    now = datetime.now(UTC).replace(microsecond=0)

    exchange_code = repository.create(
        principal_link(),
        browser_binding=BROWSER_BINDING,
        created_at=now,
    )

    assert exchange_code.startswith("cdre_")
    assert len(exchange_code) == 48
    assert repository.consume(
        exchange_code,
        browser_binding="cdrb_" + "z" * 43,
        consumed_at=now + timedelta(seconds=10),
    ) is None
    assert repository.consume(
        exchange_code,
        browser_binding=BROWSER_BINDING,
        consumed_at=now + timedelta(seconds=11),
    ) == principal_link()
    assert repository.consume(
        exchange_code,
        browser_binding=BROWSER_BINDING,
        consumed_at=now + timedelta(seconds=12),
    ) is None

    expired_code = repository.create(
        principal_link(),
        browser_binding=BROWSER_BINDING,
        created_at=now,
    )
    assert repository.consume(
        expired_code,
        browser_binding=BROWSER_BINDING,
        consumed_at=now + timedelta(minutes=2),
    ) is None
