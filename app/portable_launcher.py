"""Cross-platform launcher for the portable ClinData Relay profiles."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


UI_CACHE_TOKEN = "20260824-compact-command-deck-v1"
MACOS_LITE_DATA_DIRECTORY = "ClinicalReportExtractorLite"


@dataclass(frozen=True)
class PortablePaths:
    bundle_root: Path
    resource_root: Path
    data_root: Path
    runtime_root: Path


def _local_libreclinica_url_or_default(configured_url: str) -> str:
    try:
        parsed = urlsplit(configured_url)
        port = parsed.port
    except ValueError:
        return "http://127.0.0.1:8081"
    if (
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost"}
        and port is not None
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    ):
        return configured_url.rstrip("/")
    return "http://127.0.0.1:8081"


def _default_data_root(
    *,
    bundle_root: Path,
    platform_name: str,
    home_directory: Path,
) -> Path:
    """Keep signed macOS application bundles immutable while preserving Windows portability."""
    if platform_name == "darwin":
        return home_directory / "Library" / "Application Support" / MACOS_LITE_DATA_DIRECTORY
    return bundle_root


def _bundled_tesseract_executable(
    *,
    bundle_root: Path,
    resource_root: Path,
    platform_name: str,
) -> Path | None:
    candidates = (
        (
            bundle_root / "runtime" / "tesseract" / "tesseract.exe",
            resource_root / "runtime" / "tesseract" / "tesseract.exe",
        )
        if platform_name.startswith("win")
        else (
            resource_root / "runtime" / "tesseract" / "tesseract",
            bundle_root / "runtime" / "tesseract" / "tesseract",
        )
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def configure_portable_environment(
    *,
    bundle_root: Path,
    resource_root: Path,
    product_mode: str = "full",
    platform_name: str | None = None,
    home_directory: Path | None = None,
) -> PortablePaths:
    """Set portable-local paths and ignore unrelated inherited integration settings."""
    if product_mode not in {"full", "lite"}:
        raise ValueError("unsupported_product_mode")
    effective_platform = platform_name or sys.platform
    effective_home = (home_directory or Path.home()).resolve()
    configured_data_root = os.getenv("COMPANION_PORTABLE_DATA_ROOT", "").strip()
    configured_libreclinica_url = os.getenv(
        "COMPANION_PORTABLE_LIBRECLINICA_BASE_URL", ""
    ).strip()
    bundle_root = bundle_root.resolve()
    resource_root = resource_root.resolve()
    data_root = (
        Path(configured_data_root).resolve()
        if configured_data_root
        else _default_data_root(
            bundle_root=bundle_root,
            platform_name=effective_platform,
            home_directory=effective_home,
        ).resolve()
    )
    runtime_root = data_root / ".runtime"
    (data_root / "data").mkdir(parents=True, exist_ok=True)
    runtime_root.mkdir(parents=True, exist_ok=True)

    os.environ["COMPANION_ENV"] = "portable_synthetic"
    os.environ["COMPANION_PRODUCT_MODE"] = product_mode
    os.environ["COMPANION_DATABASE_PATH"] = str(data_root / "data" / "companion.db")
    os.environ["COMPANION_BACKUP_DIRECTORY"] = str(runtime_root / "backups")
    os.environ["COMPANION_AUTO_BACKUP"] = "true"
    os.environ.pop("SPREADSHEET_NODE_EXECUTABLE", None)
    os.environ.pop("COMPANION_CENTRE_PROFILE_FILE", None)
    centre_profile = bundle_root / "centre-profile.json"
    if centre_profile.is_file():
        if product_mode != "lite":
            raise RuntimeError("centre_profile_requires_lite_mode")
        os.environ["COMPANION_CENTRE_PROFILE_FILE"] = str(centre_profile)

    tesseract_executable = _bundled_tesseract_executable(
        bundle_root=bundle_root,
        resource_root=resource_root,
        platform_name=effective_platform,
    )
    tessdata_directory = resource_root / "vendor" / "tessdata_fast"
    if tesseract_executable is not None:
        os.environ["TESSERACT_EXECUTABLE"] = str(tesseract_executable)
    else:
        os.environ.pop("TESSERACT_EXECUTABLE", None)
    if tessdata_directory.is_dir():
        os.environ["TESSERACT_TESSDATA_DIR"] = str(tessdata_directory)
        os.environ["TESSERACT_LANGUAGE"] = "chi_sim+eng"
    else:
        os.environ.pop("TESSERACT_TESSDATA_DIR", None)
        os.environ["TESSERACT_LANGUAGE"] = "eng"

    os.environ.pop("KIMI_API_KEY", None)
    kimi_key_file = runtime_root / "kimi-api-key.txt"
    os.environ["KIMI_API_KEY_FILE"] = str(kimi_key_file)
    if kimi_key_file.is_file():
        os.environ["KIMI_ENABLED"] = "true"
        os.environ["KIMI_API_KEY_FILE"] = str(kimi_key_file)
        os.environ["KIMI_BASE_URL"] = "https://api.moonshot.cn/v1"
        os.environ["KIMI_MODEL"] = "kimi-k3"
    else:
        # Keep the product default on while withholding outbound access until
        # the recipient configures a local key file.
        os.environ["KIMI_ENABLED"] = "true"
        os.environ.pop("KIMI_BASE_URL", None)
        os.environ.pop("KIMI_MODEL", None)

    libreclinica_credentials = runtime_root / "libreclinica-soap-credentials.json"
    libreclinica_variables = (
        "LIBRECLINICA_BASE_URL",
        "LIBRECLINICA_SOAP_CREDENTIALS_FILE",
        "LIBRECLINICA_ODM_MAPPING_FILE",
        "LIBRECLINICA_ALLOW_REMOTE",
        "LIBRECLINICA_ALLOW_SUBJECT_PROVISIONING",
    )
    for variable in libreclinica_variables:
        os.environ.pop(variable, None)
    if product_mode == "full" and libreclinica_credentials.is_file():
        os.environ["COMPANION_EDC_MODE"] = "libreclinica_soap"
        os.environ["LIBRECLINICA_BASE_URL"] = _local_libreclinica_url_or_default(
            configured_libreclinica_url
        )
        os.environ["LIBRECLINICA_SOAP_CREDENTIALS_FILE"] = str(libreclinica_credentials)
        os.environ["LIBRECLINICA_ODM_MAPPING_FILE"] = str(
            resource_root / "config" / "libreclinica-sandbox-odm-map.json"
        )
        os.environ["LIBRECLINICA_ALLOW_REMOTE"] = "false"
        os.environ["LIBRECLINICA_ALLOW_SUBJECT_PROVISIONING"] = "true"
    else:
        os.environ["COMPANION_EDC_MODE"] = "simulation_only"

    return PortablePaths(
        bundle_root=bundle_root,
        resource_root=resource_root,
        data_root=data_root,
        runtime_root=runtime_root,
    )


def _health_payload(url: str) -> dict[str, object] | None:
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=1.5) as response:  # nosec B310: localhost only
            payload = json.loads(response.read())
            return payload if response.status == 200 and isinstance(payload, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, urllib.error.URLError):
        return None


def runtime_identity_matches(
    health: dict[str, object] | None,
    *,
    expected_product_mode: str,
    expected_centre_profile: dict[str, str] | None,
) -> bool:
    """Prevent one local distribution profile from opening another profile's UI."""
    if not health or health.get("status") != "ok":
        return False
    if health.get("product_mode") != expected_product_mode:
        return False
    actual_profile = health.get("centre_profile")
    if expected_centre_profile is None:
        return actual_profile is None
    if not isinstance(actual_profile, dict):
        return False
    return {
        "centre_code": actual_profile.get("centre_code"),
        "username": actual_profile.get("username"),
    } == expected_centre_profile


def _health_is_ready(url: str) -> bool:
    return (_health_payload(url) or {}).get("status") == "ok"


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def browser_url(base_url: str) -> str:
    """Return a versioned entrypoint so an old inline UI cannot survive upgrades."""
    return f"{base_url.rstrip('/')}/?ui={UI_CACHE_TOKEN}"


def _open_browser_when_ready(
    url: str,
    expected_product_mode: str,
    expected_centre_profile: dict[str, str] | None,
) -> None:
    for _ in range(80):
        if runtime_identity_matches(
            _health_payload(url),
            expected_product_mode=expected_product_mode,
            expected_centre_profile=expected_centre_profile,
        ):
            webbrowser.open(browser_url(url))
            return
        time.sleep(0.25)


def _available_port(preferred_port: int, *, fallback_count: int = 10) -> int | None:
    return next(
        (port for port in range(preferred_port, min(preferred_port + fallback_count + 1, 65536)) if _port_available(port)),
        None,
    )


def main(*, default_product_mode: str = "full") -> int:
    if default_product_mode not in {"full", "lite"}:
        raise ValueError("unsupported_product_mode")
    parser = argparse.ArgumentParser(description="Run ClinData Relay on this computer.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--lite", action="store_true")
    parser.add_argument("--reset-centre-password", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")

    frozen = bool(getattr(sys, "frozen", False))
    bundle_root = Path(sys.executable).resolve().parent if frozen else Path(__file__).resolve().parents[1]
    resource_root = Path(getattr(sys, "_MEIPASS", bundle_root)).resolve()
    product_mode = "lite" if args.lite or default_product_mode == "lite" else "full"
    paths = configure_portable_environment(
        bundle_root=bundle_root,
        resource_root=resource_root,
        product_mode=product_mode,
    )
    os.chdir(bundle_root)

    from app.centre_profile import load_centre_profile

    profile = load_centre_profile(bundle_root / "centre-profile.json") if (bundle_root / "centre-profile.json").is_file() else None
    expected_centre_profile = profile.public_payload() if profile is not None else None

    if args.reset_centre_password:
        if product_mode != "lite":
            print("Password reset is available only for a centre Lite package.")
            return 2
        from app.persistence import Database
        from app.security import generate_strong_password, password_hash

        if profile is None:
            print("This installation has no centre profile.")
            return 2
        database = Database(paths.data_root / "data" / "companion.db", centre_profile=profile)
        database.initialise()
        password = generate_strong_password()
        database.reset_centre_password(password_hash(password))
        print(f"Centre: {profile.centre_code}")
        print(f"Username: {profile.username}")
        print(f"New password (shown once): {password}")
        print("Existing browser sessions have been revoked. Store the password, then close this window.")
        return 0

    preferred_url = f"http://127.0.0.1:{args.port}"
    if runtime_identity_matches(
        _health_payload(preferred_url),
        expected_product_mode=product_mode,
        expected_centre_profile=expected_centre_profile,
    ):
        if not args.no_browser:
            webbrowser.open(browser_url(preferred_url))
        print(f"ClinData Relay is already running at {preferred_url}/")
        return 0
    selected_port = _available_port(args.port)
    if selected_port is None:
        print(f"Ports {args.port}-{min(args.port + 10, 65535)} are unavailable. Close another local program and retry.")
        return 2
    if selected_port != args.port:
        print(f"Port {args.port} belongs to a different local instance; using port {selected_port} for this package.")
    url = f"http://127.0.0.1:{selected_port}"

    if not args.no_browser:
        threading.Thread(
            target=_open_browser_when_ready,
            args=(url, product_mode, expected_centre_profile),
            daemon=True,
        ).start()

    from app.main import app as companion_app
    import uvicorn

    print(f"Starting ClinData Relay at {url}/")
    print("Synthetic localhost evaluation only. Press Ctrl+C to stop.")
    uvicorn.run(companion_app, host="127.0.0.1", port=selected_port, log_level="info")
    return 0
