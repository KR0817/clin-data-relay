from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.api.authentication import REVIEWER_ROLES, UserContext
from app.centre_profile import CentreProfile
from app.kimi import KimiClient, write_local_api_key
from app.persistence import Database


class KimiKeyPayload(BaseModel):
    key: str = Field(min_length=16, max_length=512)

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        if value != value.strip() or any(not 33 <= ord(character) <= 126 for character in value):
            raise ValueError("key must contain visible non-whitespace ASCII characters")
        return value


def kimi_status_payload(kimi_client: KimiClient) -> dict[str, object]:
    """Return only the non-secret Kimi capability state used by HTTP responses."""

    if getattr(kimi_client, "ready", False):
        status = "ready"
    elif not kimi_client.enabled:
        status = "disabled"
    elif not kimi_client.settings.api_key:
        status = "key_required"
    else:
        status = "misconfigured"
    return {
        "configured": status == "ready",
        "status": status,
        "model": kimi_client.settings.model,
    }


def create_kimi_settings_router(
    database: Database,
    *,
    kimi_client: KimiClient,
    product_mode: str,
    centre_profile: CentreProfile | None,
    current_user: Callable[..., UserContext],
) -> APIRouter:
    """Create the centre-local, redacted Kimi settings interface."""

    router = APIRouter()

    def credential_path_for(user: UserContext) -> Path:
        if user.role not in REVIEWER_ROLES:
            raise HTTPException(status_code=403, detail="read_only_role")
        if product_mode != "lite" or centre_profile is None:
            raise HTTPException(status_code=409, detail="centre_kimi_configuration_unavailable")
        if user.username != centre_profile.username or user.centre_code != centre_profile.centre_code:
            raise HTTPException(status_code=403, detail="centre_kimi_configuration_forbidden")
        configured_path = os.getenv("KIMI_API_KEY_FILE", "").strip()
        if not configured_path:
            raise HTTPException(status_code=409, detail="centre_kimi_configuration_unavailable")
        return Path(configured_path)

    @router.get("/api/settings/kimi")
    def read_kimi_settings(
        user: UserContext = Depends(current_user),
    ) -> dict[str, object]:
        credential_path_for(user)
        return kimi_status_payload(kimi_client)

    @router.put("/api/settings/kimi")
    def configure_kimi(
        payload: KimiKeyPayload,
        user: UserContext = Depends(current_user),
    ) -> dict[str, object]:
        credential_path = credential_path_for(user)
        try:
            write_local_api_key(credential_path, payload.key)
            kimi_client.reload_from_environment()
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=500, detail="kimi_credential_write_failed") from error
        if not kimi_client.ready:
            raise HTTPException(status_code=409, detail="kimi_configuration_invalid")
        with database.connect() as connection:
            database.append_audit_event(
                connection,
                candidate_id=None,
                centre_code=user.centre_code or "CENTRAL",
                event_type="kimi_credential_configured",
                actor_username=user.username,
                details={"model": kimi_client.settings.model},
            )
        return kimi_status_payload(kimi_client)

    return router
