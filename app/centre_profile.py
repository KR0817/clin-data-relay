"""Validated non-secret identity scope for a centre-specific Lite package."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


PROFILE_TYPE = "clinical-edc-centre-lite"
PROFILE_VERSION = 1
MAX_PROFILE_BYTES = 8 * 1024
_CENTRE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_-]{1,31}$")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+$")


class CentreProfileError(ValueError):
    """Raised when a packaged centre profile is absent or malformed."""


@dataclass(frozen=True)
class CentreProfile:
    centre_code: str
    username: str

    def public_payload(self) -> dict[str, str]:
        return {"centre_code": self.centre_code, "username": self.username}


def load_centre_profile(path: Path | None = None) -> CentreProfile | None:
    configured = path
    if configured is None:
        raw_path = os.getenv("COMPANION_CENTRE_PROFILE_FILE", "").strip()
        if not raw_path:
            return None
        configured = Path(raw_path)
    try:
        if configured.stat().st_size > MAX_PROFILE_BYTES:
            raise CentreProfileError("centre_profile_too_large")
        payload = json.loads(configured.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CentreProfileError("centre_profile_invalid") from error
    if not isinstance(payload, dict) or set(payload) != {
        "profile_type",
        "profile_version",
        "centre_code",
        "username",
    }:
        raise CentreProfileError("centre_profile_invalid")
    if payload["profile_type"] != PROFILE_TYPE or payload["profile_version"] != PROFILE_VERSION:
        raise CentreProfileError("centre_profile_version_unsupported")
    centre_code = payload["centre_code"]
    username = payload["username"]
    if not isinstance(centre_code, str) or not _CENTRE_CODE_RE.fullmatch(centre_code):
        raise CentreProfileError("centre_profile_centre_invalid")
    if (
        not isinstance(username, str)
        or len(username) > 254
        or not _USERNAME_RE.fullmatch(username)
        or ".." in username
    ):
        raise CentreProfileError("centre_profile_username_invalid")
    return CentreProfile(centre_code=centre_code, username=username)
