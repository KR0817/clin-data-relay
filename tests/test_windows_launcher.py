from __future__ import annotations

from collections.abc import Iterator
import os
from pathlib import Path

import pytest

from app.windows_launcher import (
    browser_url,
    configure_portable_environment,
    default_product_mode,
    runtime_identity_matches,
)


PORTABLE_ENVIRONMENT_NAMES = (
    "COMPANION_ENV",
    "COMPANION_PRODUCT_MODE",
    "COMPANION_DATABASE_PATH",
    "COMPANION_BACKUP_DIRECTORY",
    "COMPANION_AUTO_BACKUP",
    "COMPANION_CENTRE_PROFILE_FILE",
    "COMPANION_EDC_MODE",
    "SPREADSHEET_NODE_EXECUTABLE",
    "TESSERACT_EXECUTABLE",
    "TESSERACT_TESSDATA_DIR",
    "TESSERACT_LANGUAGE",
    "KIMI_API_KEY",
    "KIMI_API_KEY_FILE",
    "KIMI_ENABLED",
    "KIMI_BASE_URL",
    "KIMI_MODEL",
    "LIBRECLINICA_BASE_URL",
    "LIBRECLINICA_SOAP_CREDENTIALS_FILE",
    "LIBRECLINICA_ODM_MAPPING_FILE",
    "LIBRECLINICA_ALLOW_REMOTE",
    "LIBRECLINICA_ALLOW_SUBJECT_PROVISIONING",
)


@pytest.fixture(autouse=True)
def restore_portable_environment() -> Iterator[None]:
    snapshot = {name: os.environ.get(name) for name in PORTABLE_ENVIRONMENT_NAMES}
    yield
    for name, value in snapshot.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def test_browser_url_uses_a_versioned_ui_entrypoint() -> None:
    assert browser_url("http://127.0.0.1:8000") == (
        "http://127.0.0.1:8000/?ui=20260814-kimi-bulk-all-v4"
    )


def test_default_product_mode_follows_the_packaged_executable_name() -> None:
    assert default_product_mode("C:/Portable/Start-Clinical-EDC-Lite.exe") == "lite"
    assert default_product_mode("C:/Portable/ClinicalReportExtractorLite.exe") == "lite"
    assert default_product_mode("C:/Portable/ClinicalEdcCompanion.exe") == "full"


def test_runtime_identity_rejects_a_different_local_product_or_centre() -> None:
    site_a_profile = {"centre_code": "SITE_A", "username": "site-a-investigator"}

    assert not runtime_identity_matches(
        {"status": "ok", "product_mode": "full", "centre_profile": None},
        expected_product_mode="lite",
        expected_centre_profile=site_a_profile,
    )
    assert not runtime_identity_matches(
        {
            "status": "ok",
            "product_mode": "lite",
            "centre_profile": {"centre_code": "SITE_B", "username": "site-b-investigator"},
        },
        expected_product_mode="lite",
        expected_centre_profile=site_a_profile,
    )
    assert runtime_identity_matches(
        {
            "status": "ok",
            "product_mode": "lite",
            "centre_profile": site_a_profile,
        },
        expected_product_mode="lite",
        expected_centre_profile=site_a_profile,
    )


def test_portable_environment_is_local_and_fail_closed_without_credentials(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle_root = tmp_path / "ClinicalEdcCompanion"
    resource_root = bundle_root / "_internal"
    tesseract = bundle_root / "runtime" / "tesseract" / "tesseract.exe"
    tessdata = resource_root / "vendor" / "tessdata_fast"
    tesseract.parent.mkdir(parents=True)
    tesseract.write_bytes(b"")
    tessdata.mkdir(parents=True)

    monkeypatch.setenv("KIMI_API_KEY", "must-not-survive")
    monkeypatch.setenv("COMPANION_EDC_MODE", "libreclinica_soap")
    monkeypatch.setenv("LIBRECLINICA_SOAP_CREDENTIALS_FILE", "outside-bundle.json")

    paths = configure_portable_environment(bundle_root=bundle_root, resource_root=resource_root)

    assert paths.data_root == bundle_root
    assert os.environ["COMPANION_DATABASE_PATH"] == str(bundle_root / "data" / "companion.db")
    assert os.environ["COMPANION_BACKUP_DIRECTORY"] == str(bundle_root / ".runtime" / "backups")
    assert os.environ["COMPANION_EDC_MODE"] == "simulation_only"
    assert "LIBRECLINICA_SOAP_CREDENTIALS_FILE" not in os.environ
    assert os.environ["KIMI_ENABLED"] == "true"
    assert os.environ["KIMI_API_KEY_FILE"] == str(bundle_root / ".runtime" / "kimi-api-key.txt")
    assert "KIMI_API_KEY" not in os.environ
    assert os.environ["TESSERACT_EXECUTABLE"] == str(tesseract)
    assert os.environ["TESSERACT_TESSDATA_DIR"] == str(tessdata)


def test_portable_environment_enables_only_local_credential_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle_root = tmp_path / "ClinicalEdcCompanion"
    resource_root = bundle_root / "_internal"
    runtime_root = bundle_root / ".runtime"
    runtime_root.mkdir(parents=True)
    kimi_key = runtime_root / "kimi-api-key.txt"
    libreclinica_credentials = runtime_root / "libreclinica-soap-credentials.json"
    kimi_key.write_text("recipient-specific-placeholder", encoding="utf-8")
    libreclinica_credentials.write_text("{}", encoding="utf-8")

    configure_portable_environment(bundle_root=bundle_root, resource_root=resource_root)

    assert os.environ["KIMI_ENABLED"] == "true"
    assert os.environ["KIMI_API_KEY_FILE"] == str(kimi_key)
    assert os.environ["COMPANION_EDC_MODE"] == "libreclinica_soap"
    assert os.environ["LIBRECLINICA_BASE_URL"] == "http://127.0.0.1:8081"
    assert os.environ["LIBRECLINICA_SOAP_CREDENTIALS_FILE"] == str(libreclinica_credentials)
    assert os.environ["LIBRECLINICA_ALLOW_REMOTE"] == "false"
    assert os.environ["LIBRECLINICA_ALLOW_SUBJECT_PROVISIONING"] == "true"


def test_lite_portable_environment_forces_local_mode_even_when_edc_credentials_exist(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle_root = tmp_path / "ClinicalReportExtractorLite"
    resource_root = bundle_root / "_internal"
    runtime_root = bundle_root / ".runtime"
    runtime_root.mkdir(parents=True)
    (runtime_root / "libreclinica-soap-credentials.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("COMPANION_EDC_MODE", "libreclinica_soap")
    monkeypatch.setenv("LIBRECLINICA_BASE_URL", "https://untrusted.example")

    configure_portable_environment(
        bundle_root=bundle_root,
        resource_root=resource_root,
        product_mode="lite",
    )

    assert os.environ["COMPANION_PRODUCT_MODE"] == "lite"
    assert os.environ["COMPANION_EDC_MODE"] == "simulation_only"
    assert "LIBRECLINICA_BASE_URL" not in os.environ
    assert "LIBRECLINICA_SOAP_CREDENTIALS_FILE" not in os.environ


def test_lite_portable_environment_uses_only_bundle_local_centre_profile(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle_root = tmp_path / "ClinicalReportExtractorLite"
    resource_root = bundle_root / "_internal"
    bundle_root.mkdir(parents=True)
    profile = bundle_root / "centre-profile.json"
    profile.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("COMPANION_CENTRE_PROFILE_FILE", "outside-bundle.json")

    configure_portable_environment(
        bundle_root=bundle_root,
        resource_root=resource_root,
        product_mode="lite",
    )

    assert os.environ["COMPANION_CENTRE_PROFILE_FILE"] == str(profile)

    profile.unlink()
    configure_portable_environment(
        bundle_root=bundle_root,
        resource_root=resource_root,
        product_mode="lite",
    )
    assert "COMPANION_CENTRE_PROFILE_FILE" not in os.environ


def test_macos_lite_environment_uses_application_support_and_bundled_tesseract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app_root = tmp_path / "ClinicalReportExtractorLite.app" / "Contents" / "MacOS"
    resource_root = tmp_path / "ClinicalReportExtractorLite.app" / "Contents" / "Resources"
    tesseract = resource_root / "runtime" / "tesseract" / "tesseract"
    tessdata = resource_root / "vendor" / "tessdata_fast"
    home_directory = tmp_path / "recipient-home"
    tesseract.parent.mkdir(parents=True)
    tesseract.write_bytes(b"")
    tessdata.mkdir(parents=True)

    paths = configure_portable_environment(
        bundle_root=app_root,
        resource_root=resource_root,
        product_mode="lite",
        platform_name="darwin",
        home_directory=home_directory,
    )

    expected_data_root = (
        home_directory / "Library" / "Application Support" / "ClinicalReportExtractorLite"
    )
    assert paths.data_root == expected_data_root
    assert os.environ["COMPANION_DATABASE_PATH"] == str(
        expected_data_root / "data" / "companion.db"
    )
    assert os.environ["TESSERACT_EXECUTABLE"] == str(tesseract)
    assert os.environ["TESSERACT_TESSDATA_DIR"] == str(tessdata)
    assert os.environ["COMPANION_PRODUCT_MODE"] == "lite"
    assert os.environ["COMPANION_EDC_MODE"] == "simulation_only"


def test_macos_entrypoint_forces_lite_mode() -> None:
    from app.macos_lite_launcher import DEFAULT_PRODUCT_MODE

    assert DEFAULT_PRODUCT_MODE == "lite"


def test_portable_environment_accepts_only_a_local_libreclinica_base_url_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle_root = tmp_path / "ClinicalEdcCompanion"
    resource_root = bundle_root / "_internal"
    runtime_root = bundle_root / ".runtime"
    runtime_root.mkdir(parents=True)
    (runtime_root / "libreclinica-soap-credentials.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("COMPANION_PORTABLE_LIBRECLINICA_BASE_URL", "http://127.0.0.1:18081")

    configure_portable_environment(bundle_root=bundle_root, resource_root=resource_root)

    assert os.environ["LIBRECLINICA_BASE_URL"] == "http://127.0.0.1:18081"

    monkeypatch.setenv("COMPANION_PORTABLE_LIBRECLINICA_BASE_URL", "https://example.test")
    configure_portable_environment(bundle_root=bundle_root, resource_root=resource_root)

    assert os.environ["LIBRECLINICA_BASE_URL"] == "http://127.0.0.1:8081"

    monkeypatch.setenv("COMPANION_PORTABLE_LIBRECLINICA_BASE_URL", "http://127.0.0.1:not-a-port")
    configure_portable_environment(bundle_root=bundle_root, resource_root=resource_root)

    assert os.environ["LIBRECLINICA_BASE_URL"] == "http://127.0.0.1:8081"
