"""Digest-backed PostgreSQL exchanges between OIDC callback and app session."""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg

from app.institutional_identity import InstitutionalIdentityError, VerifiedPrincipalLink
from app.postgres_repository import PostgresRepositoryBootstrap, PostgresRepositoryStatus


EXCHANGE_LIFETIME = timedelta(minutes=2)
EXCHANGE_CODE_RE = re.compile(r"^cdre_[A-Za-z0-9_-]{43}$")
BROWSER_BINDING_RE = re.compile(r"^cdrb_[A-Za-z0-9_-]{43}$")


class OidcExchangeRepositoryError(RuntimeError):
    """Stable fail-closed exchange error without identity or connection detail."""


def _validated_time(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise OidcExchangeRepositoryError("oidc_exchange_time_invalid")
    return value.astimezone(UTC)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


class PostgresOidcExchangeRepository:
    """Create and atomically consume browser-bound OIDC login exchanges."""

    def __init__(self, dsn: str, *, environment: str) -> None:
        self._bootstrap = PostgresRepositoryBootstrap(dsn, environment=environment)

    def prepare(self) -> PostgresRepositoryStatus:
        return self._bootstrap.prepare()

    def create(
        self,
        principal: VerifiedPrincipalLink,
        *,
        browser_binding: str,
        created_at: datetime,
    ) -> str:
        if not isinstance(principal, VerifiedPrincipalLink):
            raise OidcExchangeRepositoryError("oidc_exchange_principal_invalid")
        if not isinstance(browser_binding, str) or not BROWSER_BINDING_RE.fullmatch(
            browser_binding
        ):
            raise OidcExchangeRepositoryError(
                "oidc_exchange_browser_binding_invalid"
            )
        occurred_at = _validated_time(created_at)
        exchange_code = f"cdre_{secrets.token_urlsafe(32)}"
        if not EXCHANGE_CODE_RE.fullmatch(exchange_code):
            raise OidcExchangeRepositoryError("oidc_exchange_code_invalid")
        try:
            with self._bootstrap._open_connection() as connection:
                connection.execute(
                    """
                    INSERT INTO oidc_login_exchanges (
                        id, code_sha256, browser_binding_sha256,
                        provider_id, principal_id, username, authenticated_at,
                        mfa_authenticated, created_at, expires_at, consumed_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)
                    """,
                    (
                        str(uuid4()),
                        _digest(exchange_code),
                        _digest(browser_binding),
                        principal.provider_id,
                        principal.principal_id,
                        principal.username,
                        principal.authenticated_at,
                        principal.mfa_authenticated,
                        occurred_at,
                        occurred_at + EXCHANGE_LIFETIME,
                    ),
                )
            return exchange_code
        except psycopg.Error:
            raise OidcExchangeRepositoryError(
                "oidc_exchange_repository_unavailable"
            ) from None

    def consume(
        self,
        exchange_code: str,
        *,
        browser_binding: str,
        consumed_at: datetime,
    ) -> VerifiedPrincipalLink | None:
        occurred_at = _validated_time(consumed_at)
        if (
            not isinstance(exchange_code, str)
            or not EXCHANGE_CODE_RE.fullmatch(exchange_code)
            or not isinstance(browser_binding, str)
            or not BROWSER_BINDING_RE.fullmatch(browser_binding)
        ):
            return None
        try:
            with self._bootstrap._open_connection() as connection:
                row = connection.execute(
                    """
                    SELECT id, provider_id, principal_id, username,
                           authenticated_at, mfa_authenticated
                    FROM oidc_login_exchanges
                    WHERE code_sha256 = %s
                      AND browser_binding_sha256 = %s
                      AND consumed_at IS NULL
                      AND created_at <= %s
                      AND expires_at > %s
                    FOR UPDATE
                    """,
                    (
                        _digest(exchange_code),
                        _digest(browser_binding),
                        occurred_at,
                        occurred_at,
                    ),
                ).fetchone()
                if row is None:
                    return None
                connection.execute(
                    """
                    UPDATE oidc_login_exchanges
                    SET consumed_at = %s
                    WHERE id = %s
                    """,
                    (occurred_at, row["id"]),
                )
            return VerifiedPrincipalLink(
                provider_id=str(row["provider_id"]),
                principal_id=str(row["principal_id"]),
                username=str(row["username"]),
                authenticated_at=row["authenticated_at"],
                mfa_authenticated=bool(row["mfa_authenticated"]),
            )
        except (psycopg.Error, InstitutionalIdentityError, TypeError, ValueError):
            raise OidcExchangeRepositoryError(
                "oidc_exchange_repository_unavailable"
            ) from None
