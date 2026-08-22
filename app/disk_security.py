"""Read-only host disk-encryption preflight for centre workstations."""

from __future__ import annotations

import platform
import subprocess
import time
from pathlib import Path
from typing import Any


_STATUS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_STATUS_CACHE_TTL_SECONDS = 30.0


def _bitlocker_is_enabled(text: str) -> bool:
    lowered = text.casefold()
    fully_encrypted = (
        "fully encrypted" in lowered
        or "已完全加密" in lowered
        or ("已加密百分比" in lowered and ("100.0%" in lowered or "100.0％" in lowered))
    )
    protection_on = "protection status" in lowered and "protection on" in lowered
    protection_on = protection_on or "保护已启用" in lowered
    return fully_encrypted and protection_on


def disk_encryption_status(path: Path | None = None) -> dict[str, Any]:
    system = platform.system()
    volume = str(path.drive or "C:") if path is not None and system == "Windows" else "C:"
    cache_key = f"{system}:{volume}"
    cached = _STATUS_CACHE.get(cache_key)
    now = time.monotonic()
    if cached is not None and now - cached[0] < _STATUS_CACHE_TTL_SECONDS:
        return dict(cached[1])
    if system == "Windows":
        status = _windows_bitlocker_status(volume)
    elif system == "Darwin":
        status = _macos_filevault_status()
    else:
        status = {"platform": system.lower() or "unknown", "status": "unsupported", "provider": None}
    _STATUS_CACHE[cache_key] = (now, status)
    return dict(status)


def _windows_bitlocker_status(volume: str = "C:") -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["manage-bde.exe", "-status", volume],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {
            "platform": "windows",
            "status": "unknown",
            "provider": "bitlocker",
            "volume": volume,
            "reason": "administrator_required_or_query_failed",
        }
    if result.returncode != 0:
        combined_output = f"{result.stdout}\n{result.stderr}".lower()
        reason = "administrator_required" if "denied" in combined_output or "access" in combined_output else "query_failed"
        return {
            "platform": "windows",
            "status": "unknown",
            "provider": "bitlocker",
            "volume": volume,
            "reason": reason,
        }
    text = result.stdout or ""
    enabled = _bitlocker_is_enabled(text)
    return {
        "platform": "windows",
        "status": "enabled" if enabled else "disabled",
        "provider": "bitlocker",
        "volume": volume,
    }


def _macos_filevault_status() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["fdesetup", "status"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {"platform": "macos", "status": "unknown", "provider": "filevault"}
    text = (result.stdout or "").lower()
    if "filevault is on" in text:
        status = "enabled"
    elif "filevault is off" in text:
        status = "disabled"
    else:
        status = "unknown"
    return {"platform": "macos", "status": status, "provider": "filevault"}
