"""Future-central project OIDC browser flow with one-time session exchange."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, HTTPException, Request, status
from starlette.responses import JSONResponse, RedirectResponse, Response

from app.institutional_identity import VerifiedPrincipalLink, verified_principal_link
from app.postgres_institutional_session_repository import (
    InstitutionalSession,
    InstitutionalSessionRepositoryError,
)
from app.postgres_oidc_exchange_repository import (
    BROWSER_BINDING_RE,
    OidcExchangeRepositoryError,
)
from app.project_oidc_identity import (
    ProjectOidcIdentityError,
    ProjectOidcPolicy,
    principal_from_verified_oidc_claims,
)


_BROWSER_BINDING_SESSION_KEY = "project_oidc_browser_binding"
_MAX_AUTHENTICATION_AGE_SECONDS = 8 * 60 * 60


class ProjectOidcClientError(RuntimeError):
    """Stable external OIDC client error without provider response detail."""


class OidcExchangeRepository(Protocol):
    def create(
        self,
        principal: VerifiedPrincipalLink,
        *,
        browser_binding: str,
        created_at: datetime,
    ) -> str: ...

    def consume(
        self,
        exchange_code: str,
        *,
        browser_binding: str,
        consumed_at: datetime,
    ) -> VerifiedPrincipalLink | None: ...


class CompanionSessionRepository(Protocol):
    def create_session_from_link(
        self,
        principal: VerifiedPrincipalLink,
        *,
        issued_at: datetime,
    ) -> InstitutionalSession: ...


@dataclass(frozen=True)
class ProjectOidcClient:
    """Bounded async client operations implemented by Authlib in central mode."""

    start_authorization: Callable[..., Awaitable[Response]]
    finish_authorization: Callable[[Request], Awaitable[Mapping[str, object]]]


def _validated_https_url(value: object) -> tuple[str, str, int | None]:
    if (
        not isinstance(value, str)
        or not 9 <= len(value) <= 2048
        or "\\" in value
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        raise ValueError
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError from None
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
    ):
        raise ValueError
    return parsed.scheme, hostname, port


@dataclass(frozen=True)
class ProjectOidcWebConfig:
    callback_url: str
    completion_url: str

    def __post_init__(self) -> None:
        try:
            callback_origin = _validated_https_url(self.callback_url)
            completion_origin = _validated_https_url(self.completion_url)
        except ValueError:
            raise ProjectOidcClientError("project_oidc_web_config_invalid") from None
        if callback_origin != completion_origin:
            raise ProjectOidcClientError("project_oidc_web_config_invalid")


def create_authlib_project_oidc_client(
    policy: ProjectOidcPolicy,
    *,
    client_secret: str,
) -> ProjectOidcClient:
    """Create the maintained Authlib adapter without retaining returned tokens."""
    if not isinstance(client_secret, str) or not 8 <= len(client_secret) <= 4096:
        raise ProjectOidcClientError("project_oidc_client_secret_invalid")

    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    remote = oauth.register(
        name="project_identity",
        client_id=policy.client_id,
        client_secret=client_secret,
        server_metadata_url=(
            f"{policy.issuer.rstrip('/')}/.well-known/openid-configuration"
        ),
        client_kwargs={
            "scope": "openid",
            "code_challenge_method": "S256",
            "token_endpoint_auth_method": "client_secret_basic",
        },
    )

    async def start_authorization(
        request: Request,
        *,
        redirect_uri: str,
        nonce: str,
        acr_values: str,
        max_age: int,
    ) -> Response:
        try:
            return await remote.authorize_redirect(
                request,
                redirect_uri,
                nonce=nonce,
                acr_values=acr_values,
                max_age=max_age,
            )
        except Exception:
            raise ProjectOidcClientError(
                "project_oidc_provider_unavailable"
            ) from None

    async def finish_authorization(request: Request) -> Mapping[str, object]:
        try:
            token = await remote.authorize_access_token(request)
            userinfo = token.get("userinfo") if isinstance(token, Mapping) else None
            if not isinstance(userinfo, Mapping):
                raise ProjectOidcClientError("project_oidc_callback_failed")
            return dict(userinfo)
        except ProjectOidcClientError:
            raise
        except Exception:
            raise ProjectOidcClientError("project_oidc_callback_failed") from None

    return ProjectOidcClient(
        start_authorization=start_authorization,
        finish_authorization=finish_authorization,
    )


def _browser_session(request: Request) -> dict[str, object]:
    try:
        return request.session
    except AssertionError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="project_oidc_browser_session_required",
        ) from None


def _no_store(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def create_project_oidc_auth_router(
    *,
    policy: ProjectOidcPolicy,
    web_config: ProjectOidcWebConfig,
    oidc_client: ProjectOidcClient,
    exchange_repository: OidcExchangeRepository,
    session_repository: CompanionSessionRepository,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> APIRouter:
    """Create the unmounted future-central OIDC login router."""
    router = APIRouter()

    @router.get("/api/auth/oidc/login")
    async def login(request: Request) -> Response:
        browser_session = _browser_session(request)
        browser_binding = f"cdrb_{secrets.token_urlsafe(32)}"
        if not BROWSER_BINDING_RE.fullmatch(browser_binding):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="project_oidc_provider_unavailable",
            )
        browser_session[_BROWSER_BINDING_SESSION_KEY] = browser_binding
        try:
            response = await oidc_client.start_authorization(
                request,
                redirect_uri=web_config.callback_url,
                nonce=secrets.token_urlsafe(32),
                acr_values=policy.required_acr,
                max_age=_MAX_AUTHENTICATION_AGE_SECONDS,
            )
        except ProjectOidcClientError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="project_oidc_provider_unavailable",
            ) from None
        return _no_store(response)

    @router.get("/api/auth/oidc/callback")
    async def callback(request: Request) -> Response:
        browser_session = _browser_session(request)
        browser_binding = browser_session.get(_BROWSER_BINDING_SESSION_KEY)
        if not isinstance(browser_binding, str) or not BROWSER_BINDING_RE.fullmatch(
            browser_binding
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="project_oidc_browser_session_required",
            )
        try:
            claims = await oidc_client.finish_authorization(request)
            principal = principal_from_verified_oidc_claims(policy, claims)
            exchange_code = exchange_repository.create(
                verified_principal_link(principal),
                browser_binding=browser_binding,
                created_at=clock(),
            )
        except ProjectOidcClientError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="project_oidc_callback_failed",
            ) from None
        except ProjectOidcIdentityError as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(error),
            ) from None
        except OidcExchangeRepositoryError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="project_oidc_session_unavailable",
            ) from None

        location = f"{web_config.completion_url}?{urlencode({'oidc_exchange': exchange_code})}"
        return _no_store(RedirectResponse(location, status_code=303))

    @router.post("/api/auth/oidc/exchange")
    async def exchange(request: Request) -> Response:
        browser_session = _browser_session(request)
        browser_binding = browser_session.get(_BROWSER_BINDING_SESSION_KEY)
        try:
            payload = await request.json()
        except Exception:
            payload = None
        exchange_code = (
            payload.get("exchange_code")
            if isinstance(payload, dict) and set(payload) == {"exchange_code"}
            else None
        )
        if not isinstance(browser_binding, str) or not isinstance(exchange_code, str):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="project_oidc_exchange_invalid",
            )
        try:
            principal = exchange_repository.consume(
                exchange_code,
                browser_binding=browser_binding,
                consumed_at=clock(),
            )
        except OidcExchangeRepositoryError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="project_oidc_session_unavailable",
            ) from None
        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="project_oidc_exchange_invalid",
            )
        try:
            session = session_repository.create_session_from_link(
                principal,
                issued_at=clock(),
            )
        except InstitutionalSessionRepositoryError as error:
            detail = (
                "project_oidc_session_unavailable"
                if str(error) == "institutional_session_repository_unavailable"
                else "project_oidc_access_denied"
            )
            http_status = (
                status.HTTP_503_SERVICE_UNAVAILABLE
                if detail == "project_oidc_session_unavailable"
                else status.HTTP_403_FORBIDDEN
            )
            raise HTTPException(status_code=http_status, detail=detail) from None

        browser_session.pop(_BROWSER_BINDING_SESSION_KEY, None)
        return _no_store(
            JSONResponse(
                {
                    "access_token": session.token,
                    "token_type": "bearer",
                    "user": {
                        "username": session.user.username,
                        "centre_code": session.user.centre_code,
                        "role": session.user.role,
                    },
                }
            )
        )

    return router
