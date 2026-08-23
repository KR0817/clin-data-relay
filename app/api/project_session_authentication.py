"""Future-central bearer resolution and server-side session logout."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Protocol

from fastapi import APIRouter, Header, HTTPException, Response, status

from app.api.authentication import AuthModule, UserContext
from app.institutional_identity import InstitutionalUser
from app.postgres_institutional_session_repository import (
    InstitutionalSessionRepositoryError,
)


_NO_STORE_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
}


class ProjectSessionRepository(Protocol):
    def resolve_session(
        self,
        token: str,
        *,
        now: datetime,
    ) -> InstitutionalUser | None: ...

    def revoke_session(
        self,
        token: str,
        *,
        revoked_at: datetime,
    ) -> bool: ...


def create_project_session_auth_module(
    repository: ProjectSessionRepository,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> AuthModule:
    """Create the unmounted future-central bearer authentication module."""

    router = APIRouter()

    def resolve(
        authorization: str | None,
    ) -> tuple[str, UserContext]:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication_required",
                headers=_NO_STORE_HEADERS,
            )
        token = authorization.removeprefix("Bearer ")
        try:
            user = repository.resolve_session(token, now=clock())
        except InstitutionalSessionRepositoryError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="project_session_unavailable",
                headers=_NO_STORE_HEADERS,
            ) from None
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_or_expired_token",
                headers=_NO_STORE_HEADERS,
            )
        return token, UserContext(
            id=user.id,
            username=user.username,
            centre_code=user.centre_code,
            role=user.role,
        )

    def current_user(
        authorization: Annotated[str | None, Header()] = None,
    ) -> UserContext:
        return resolve(authorization)[1]

    @router.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout(
        authorization: Annotated[str | None, Header()] = None,
    ) -> Response:
        token, _ = resolve(authorization)
        try:
            revoked = repository.revoke_session(token, revoked_at=clock())
        except InstitutionalSessionRepositoryError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="project_session_unavailable",
                headers=_NO_STORE_HEADERS,
            ) from None
        if not revoked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_or_expired_token",
                headers=_NO_STORE_HEADERS,
            )
        return Response(
            status_code=status.HTTP_204_NO_CONTENT,
            headers=_NO_STORE_HEADERS,
        )

    return AuthModule(router=router, current_user=current_user)
