from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.authentication import UserContext
from app.api.project_session_authentication import (
    create_project_session_auth_module,
)
from app.institutional_identity import InstitutionalUser
from app.postgres_institutional_session_repository import (
    InstitutionalSessionRepositoryError,
)


NOW = datetime(2026, 8, 24, 14, 0, tzinfo=UTC)
SESSION_TOKEN = "cdrs_" + "s" * 43


class MemorySessionRepository:
    def __init__(self) -> None:
        self.active = True
        self.resolve_error: str | None = None
        self.revoke_error: str | None = None

    def resolve_session(
        self,
        token: str,
        *,
        now: datetime,
    ) -> InstitutionalUser | None:
        assert now == NOW
        if self.resolve_error:
            raise InstitutionalSessionRepositoryError(self.resolve_error)
        if token != SESSION_TOKEN or not self.active:
            return None
        return InstitutionalUser(
            id="institutional:" + "a" * 64,
            username="investigator-001",
            role="site_investigator",
            centre_code="SITE_A",
        )

    def revoke_session(
        self,
        token: str,
        *,
        revoked_at: datetime,
    ) -> bool:
        assert revoked_at == NOW
        if self.revoke_error:
            raise InstitutionalSessionRepositoryError(self.revoke_error)
        if token != SESSION_TOKEN:
            return False
        self.active = False
        return True


def build_client(
    repository: MemorySessionRepository,
) -> TestClient:
    auth = create_project_session_auth_module(
        repository,
        clock=lambda: NOW,
    )
    app = FastAPI()
    app.include_router(auth.router)

    @app.get("/protected")
    def protected(
        user: UserContext = Depends(auth.current_user),
    ) -> dict[str, object]:
        return {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "centre_code": user.centre_code,
        }

    return TestClient(app)


def test_valid_project_session_authenticates_and_logout_revokes_it() -> None:
    repository = MemorySessionRepository()
    client = build_client(repository)

    missing = client.get("/protected")
    assert missing.status_code == 401
    assert missing.json() == {"detail": "authentication_required"}
    assert missing.headers["cache-control"] == "no-store"

    malformed = client.get(
        "/protected",
        headers={"Authorization": "Bearer not-a-session"},
    )
    assert malformed.status_code == 401
    assert malformed.json() == {"detail": "invalid_or_expired_token"}

    headers = {"Authorization": f"Bearer {SESSION_TOKEN}"}
    authenticated = client.get("/protected", headers=headers)
    assert authenticated.status_code == 200
    assert authenticated.json() == {
        "id": "institutional:" + "a" * 64,
        "username": "investigator-001",
        "role": "site_investigator",
        "centre_code": "SITE_A",
    }

    logout = client.post("/api/auth/logout", headers=headers)
    assert logout.status_code == 204
    assert logout.content == b""
    assert logout.headers["cache-control"] == "no-store"

    revoked = client.get("/protected", headers=headers)
    assert revoked.status_code == 401
    assert revoked.json() == {"detail": "invalid_or_expired_token"}


def test_project_session_repository_errors_are_bounded() -> None:
    sentinel = "sensitive-repository-error"
    repository = MemorySessionRepository()
    repository.resolve_error = sentinel
    client = build_client(repository)
    headers = {"Authorization": f"Bearer {SESSION_TOKEN}"}

    resolution = client.get("/protected", headers=headers)

    assert resolution.status_code == 503
    assert resolution.json() == {"detail": "project_session_unavailable"}
    assert sentinel not in resolution.text
    assert SESSION_TOKEN not in resolution.text

    repository.resolve_error = None
    repository.revoke_error = sentinel
    revocation = client.post("/api/auth/logout", headers=headers)

    assert revocation.status_code == 503
    assert revocation.json() == {"detail": "project_session_unavailable"}
    assert sentinel not in revocation.text
    assert SESSION_TOKEN not in revocation.text
