from __future__ import annotations

import os

import pytest

from app.postgres_repository import (
    LATEST_POSTGRES_SCHEMA_VERSION,
    PostgresConfigurationError,
    PostgresRepositoryBootstrap,
    PostgresRepositoryError,
)


def test_postgres_bootstrap_requires_verified_tls_outside_local_development() -> None:
    with pytest.raises(PostgresConfigurationError, match="postgres_tls_verify_full_required"):
        PostgresRepositoryBootstrap(
            "postgresql://db.internal/companion?sslmode=require",
            environment="production",
        )

    with pytest.raises(PostgresConfigurationError, match="postgres_nonlocal_unverified_tls_forbidden"):
        PostgresRepositoryBootstrap(
            "postgresql://db.internal/companion?sslmode=disable",
            environment="development",
        )

    repository = PostgresRepositoryBootstrap(
        "postgresql://127.0.0.1/companion?sslmode=disable",
        environment="test",
    )
    assert repository.environment == "test"


def test_postgres_configuration_errors_do_not_echo_connection_material() -> None:
    dsn = "postgresql://sensitive-user@db.internal/sensitive-db?sslmode=require"
    with pytest.raises(PostgresConfigurationError) as raised:
        PostgresRepositoryBootstrap(dsn, environment="production")

    message = str(raised.value)
    assert message == "postgres_tls_verify_full_required"
    assert "sensitive-user" not in message
    assert "sensitive-db" not in message
    assert "db.internal" not in message


@pytest.mark.postgres
def test_postgres_bootstrap_is_idempotent_and_returns_only_redacted_status() -> None:
    dsn = os.getenv("CLINDATA_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("CLINDATA_TEST_POSTGRES_DSN is not configured")

    repository = PostgresRepositoryBootstrap(dsn, environment="test")
    first = repository.prepare()
    second = repository.prepare()

    assert first == second
    assert first.backend == "postgresql"
    assert first.server_major >= 16
    assert first.schema_version == LATEST_POSTGRES_SCHEMA_VERSION == 2
    assert first.migration_count == 2
    assert first.clinical_data_ready is False
    assert first.public_payload() == {
        "backend": "postgresql",
        "server_major": 16,
        "schema_version": 2,
        "migration_count": 2,
        "clinical_data_ready": False,
    }
    assert "postgresql://" not in str(first.public_payload())


@pytest.mark.postgres
def test_postgres_bootstrap_rejects_a_schema_newer_than_the_application() -> None:
    dsn = os.getenv("CLINDATA_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("CLINDATA_TEST_POSTGRES_DSN is not configured")

    psycopg = pytest.importorskip("psycopg")
    repository = PostgresRepositoryBootstrap(dsn, environment="test")
    repository.prepare()
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """
            INSERT INTO companion_schema_migrations (version, name)
            VALUES (%s, %s)
            ON CONFLICT (version) DO NOTHING
            """,
            (999, "synthetic_future_schema"),
        )
    try:
        with pytest.raises(PostgresRepositoryError, match="postgres_schema_too_new") as raised:
            repository.prepare()
        assert "postgresql://" not in str(raised.value)
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute("DELETE FROM companion_schema_migrations WHERE version = %s", (999,))
