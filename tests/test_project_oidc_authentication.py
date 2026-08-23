from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse

from app.institutional_identity import InstitutionalUser, VerifiedPrincipalLink
from app.main import create_app
from app.postgres_institutional_session_repository import InstitutionalSession
from app.project_oidc_identity import ProjectOidcPolicy
from app.api.project_oidc_authentication import (
    ProjectOidcClient,
    ProjectOidcClientError,
    ProjectOidcWebConfig,
    create_authlib_project_oidc_client,
    create_project_oidc_auth_router,
)


NOW = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)
EXCHANGE_CODE = "cdre_" + "c" * 43


class MemoryExchangeRepository:
    def __init__(self) -> None:
        self.pending: tuple[VerifiedPrincipalLink, str] | None = None

    def create(
        self,
        principal: VerifiedPrincipalLink,
        *,
        browser_binding: str,
        created_at: datetime,
    ) -> str:
        assert created_at == NOW
        self.pending = (principal, browser_binding)
        return EXCHANGE_CODE

    def consume(
        self,
        exchange_code: str,
        *,
        browser_binding: str,
        consumed_at: datetime,
    ) -> VerifiedPrincipalLink | None:
        if (
            consumed_at != NOW
            or exchange_code != EXCHANGE_CODE
            or self.pending is None
            or self.pending[1] != browser_binding
        ):
            return None
        principal = self.pending[0]
        self.pending = None
        return principal


class MemorySessionRepository:
    def create_session_from_link(
        self,
        principal: VerifiedPrincipalLink,
        *,
        issued_at: datetime,
    ) -> InstitutionalSession:
        assert issued_at == NOW
        return InstitutionalSession(
            token="cdrs_" + "s" * 43,
            user=InstitutionalUser(
                id=principal.principal_id,
                username=principal.username,
                role="site_investigator",
                centre_code="SITE_A",
            ),
            issued_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )


def oidc_client(
    claims: dict[str, object] | None = None,
) -> ProjectOidcClient:
    resolved_claims = claims if claims is not None else {
        "iss": "https://identity.example.test/realms/clin-data-relay",
        "aud": "clindata-relay-central",
        "sub": "project-investigator-001",
        "preferred_username": "investigator-001",
        "auth_time": int(NOW.timestamp()),
        "acr": "study-mfa",
        "groups": ["central_data_manager"],
        "centre_code": "UNTRUSTED",
    }

    async def start_authorization(
        request,
        *,
        redirect_uri: str,
        nonce: str,
        acr_values: str,
        max_age: int,
    ):
        query = urlencode(
            {
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "nonce": nonce,
                "acr_values": acr_values,
                "max_age": max_age,
                "code_challenge_method": "S256",
            }
        )
        return RedirectResponse(
            f"https://identity.example.test/authorize?{query}",
            status_code=302,
        )

    async def finish_authorization(request):
        return resolved_claims

    return ProjectOidcClient(
        start_authorization=start_authorization,
        finish_authorization=finish_authorization,
    )


def build_client(
    *,
    claims: dict[str, object] | None = None,
    client_override: ProjectOidcClient | None = None,
) -> tuple[FastAPI, TestClient, MemoryExchangeRepository]:
    exchange_repository = MemoryExchangeRepository()
    app = FastAPI()
    app.add_middleware(
        SessionMiddleware,
        secret_key="synthetic-test-session-signing-secret",
        same_site="lax",
        https_only=False,
        max_age=300,
    )
    app.include_router(
        create_project_oidc_auth_router(
            policy=ProjectOidcPolicy(
                provider_id="study-keycloak",
                issuer="https://identity.example.test/realms/clin-data-relay",
                client_id="clindata-relay-central",
                required_acr="study-mfa",
            ),
            web_config=ProjectOidcWebConfig(
                callback_url="https://relay.example.test/api/auth/oidc/callback",
                completion_url="https://relay.example.test/oidc-complete",
            ),
            oidc_client=client_override or oidc_client(claims),
            exchange_repository=exchange_repository,
            session_repository=MemorySessionRepository(),
            clock=lambda: NOW,
        )
    )
    return app, TestClient(app), exchange_repository


def test_login_callback_and_same_browser_exchange_never_put_bearer_in_url() -> None:
    _, client, _ = build_client()

    login = client.get("/api/auth/oidc/login", follow_redirects=False)
    assert login.status_code == 302
    login_query = parse_qs(urlsplit(login.headers["location"]).query)
    assert login_query["redirect_uri"] == [
        "https://relay.example.test/api/auth/oidc/callback"
    ]
    assert login_query["acr_values"] == ["study-mfa"]
    assert login_query["max_age"] == ["28800"]
    assert login_query["code_challenge_method"] == ["S256"]
    assert len(login_query["nonce"][0]) >= 43
    assert login.headers["cache-control"] == "no-store"

    callback = client.get(
        "/api/auth/oidc/callback?code=provider-code&state=provider-state",
        follow_redirects=False,
    )
    assert callback.status_code == 303
    location = callback.headers["location"]
    assert location.startswith("https://relay.example.test/oidc-complete?")
    assert parse_qs(urlsplit(location).query) == {
        "oidc_exchange": [EXCHANGE_CODE]
    }
    assert "cdrs_" not in location
    assert "access_token" not in location
    assert "id_token" not in location
    assert "cdrs_" not in callback.text
    assert callback.headers["cache-control"] == "no-store"

    exchanged = client.post(
        "/api/auth/oidc/exchange",
        json={"exchange_code": EXCHANGE_CODE},
    )
    assert exchanged.status_code == 200
    assert exchanged.json() == {
        "access_token": "cdrs_" + "s" * 43,
        "token_type": "bearer",
        "user": {
            "username": "investigator-001",
            "centre_code": "SITE_A",
            "role": "site_investigator",
        },
    }
    assert exchanged.headers["cache-control"] == "no-store"

    replay = client.post(
        "/api/auth/oidc/exchange",
        json={"exchange_code": EXCHANGE_CODE},
    )
    assert replay.status_code == 401
    assert replay.json() == {"detail": "project_oidc_exchange_invalid"}


def test_login_exchange_cannot_be_used_by_a_different_browser() -> None:
    app, client, _ = build_client()
    client.get("/api/auth/oidc/login", follow_redirects=False)
    callback = client.get("/api/auth/oidc/callback", follow_redirects=False)
    exchange_code = parse_qs(urlsplit(callback.headers["location"]).query)[
        "oidc_exchange"
    ][0]

    with TestClient(app) as other_browser:
        response = other_browser.post(
            "/api/auth/oidc/exchange",
            json={"exchange_code": exchange_code},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "project_oidc_exchange_invalid"}

    correct_browser = client.post(
        "/api/auth/oidc/exchange",
        json={"exchange_code": exchange_code},
    )
    assert correct_browser.status_code == 200


def test_invalid_verified_claim_shape_returns_only_a_bounded_error() -> None:
    sentinel = "sensitive-project-subject"
    _, client, _ = build_client(
        claims={
            "iss": "https://identity.example.test/realms/clin-data-relay",
            "aud": "clindata-relay-central",
            "sub": sentinel + " ",
            "preferred_username": "investigator-001",
            "auth_time": int(NOW.timestamp()),
            "acr": "study-mfa",
        }
    )
    client.get("/api/auth/oidc/login", follow_redirects=False)

    response = client.get("/api/auth/oidc/callback", follow_redirects=False)

    assert response.status_code == 401
    assert response.json() == {"detail": "project_oidc_claims_invalid"}
    assert sentinel not in response.text


def test_provider_start_error_cannot_echo_adapter_details() -> None:
    sentinel = "sensitive-provider-error-detail"

    async def fail_start(request, **kwargs):
        raise ProjectOidcClientError(sentinel)

    async def unused_finish(request):
        raise AssertionError("callback must not run")

    _, client, _ = build_client(
        client_override=ProjectOidcClient(
            start_authorization=fail_start,
            finish_authorization=unused_finish,
        )
    )

    response = client.get("/api/auth/oidc/login", follow_redirects=False)

    assert response.status_code == 503
    assert response.json() == {"detail": "project_oidc_provider_unavailable"}
    assert sentinel not in response.text


def test_oidc_web_config_rejects_cross_origin_or_non_https_redirects() -> None:
    for callback_url, completion_url in (
        (
            "http://relay.example.test/api/auth/oidc/callback",
            "https://relay.example.test/oidc-complete",
        ),
        (
            "https://relay.example.test/api/auth/oidc/callback",
            "https://attacker.example/oidc-complete",
        ),
        (
            "https://relay.example.test/api/auth/oidc/callback",
            "https://relay.example.test/oidc complete",
        ),
    ):
        with pytest.raises(
            ProjectOidcClientError,
            match="^project_oidc_web_config_invalid$",
        ):
            ProjectOidcWebConfig(
                callback_url=callback_url,
                completion_url=completion_url,
            )


def test_default_app_keeps_project_oidc_routes_unmounted(tmp_path: Path) -> None:
    app = create_app(
        database_path=tmp_path / "oidc-disabled.db",
        environment="test",
    )

    with TestClient(app) as client:
        response = client.get("/api/auth/oidc/login", follow_redirects=False)

    assert response.status_code == 404


def test_authlib_client_configuration_never_exposes_its_secret() -> None:
    sentinel = "synthetic-client-secret-never-render"
    client = create_authlib_project_oidc_client(
        ProjectOidcPolicy(
            provider_id="study-keycloak",
            issuer="https://identity.example.test/realms/clin-data-relay",
            client_id="clindata-relay-central",
            required_acr="study-mfa",
        ),
        client_secret=sentinel,
    )

    assert sentinel not in repr(client)
    with pytest.raises(
        ProjectOidcClientError,
        match="^project_oidc_client_secret_invalid$",
    ):
        create_authlib_project_oidc_client(
            ProjectOidcPolicy(
                provider_id="study-keycloak",
                issuer="https://identity.example.test/realms/clin-data-relay",
                client_id="clindata-relay-central",
                required_acr="study-mfa",
            ),
            client_secret="short",
        )
