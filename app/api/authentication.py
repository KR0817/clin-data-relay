from dataclasses import dataclass
from typing import Annotated, Callable

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from app.centre_profile import CentreProfile
from app.local_auth import LOGIN_ROLES, authenticate_local_user, resolve_local_session
from app.persistence import Database


CENTRAL_ROLES = {"principal_investigator", "central_data_manager"}
REVIEWER_ROLES = {"site_investigator", "central_data_manager"}
READ_ONLY_ROLES = {"monitor", "auditor"}
GLOBAL_READ_ROLES = CENTRAL_ROLES | READ_ONLY_ROLES
EXPORT_ROLES = {"site_investigator", "principal_investigator", "central_data_manager"}


@dataclass(frozen=True)
class UserContext:
    id: str
    username: str
    centre_code: str | None
    role: str


class LoginPayload(BaseModel):
    username: str
    password: str


@dataclass(frozen=True)
class AuthModule:
    router: APIRouter
    current_user: Callable[..., UserContext]


def create_auth_module(
    database: Database,
    *,
    environment: str,
    centre_profile: CentreProfile | None,
) -> AuthModule:
    """Register local authentication and expose its bearer-session dependency."""

    router = APIRouter()

    def current_user(authorization: Annotated[str | None, Header()] = None) -> UserContext:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication_required")
        token = authorization.removeprefix("Bearer ")
        user = resolve_local_session(database, token)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_or_expired_token")
        return UserContext(
            id=user.id,
            username=user.username,
            centre_code=user.centre_code,
            role=user.role,
        )

    @router.post("/api/auth/login")
    def login(payload: LoginPayload) -> dict[str, object]:
        session = authenticate_local_user(
            database,
            username=payload.username,
            password=payload.password,
            environment=environment,
            centre_profile_present=centre_profile is not None,
        )
        if session is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")
        return {
            "access_token": session.token,
            "token_type": "bearer",
            "user": {
                "username": session.user.username,
                "centre_code": session.user.centre_code,
                "role": session.user.role,
            },
        }

    return AuthModule(router=router, current_user=current_user)
