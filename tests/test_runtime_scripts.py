import json
from pathlib import Path
import subprocess

from PIL import Image
import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_kimi_runtime_configuration_prompts_masked_and_keeps_key_out_of_source() -> None:
    configure_script = (PROJECT_ROOT / "scripts" / "configure_kimi.ps1").read_text(encoding="utf-8-sig")
    start_script = (PROJECT_ROOT / "scripts" / "start_companion_live.ps1").read_text(encoding="utf-8-sig")

    assert "Read-Host" in configure_script
    assert "-AsSecureString" in configure_script
    assert "kimi-api-key.txt" in configure_script
    assert "KIMI_API_KEY_FILE" in start_script
    assert "KIMI_ENABLED" in start_script
    assert "backup_companion_database.py" in start_script
    assert "Automatic database backup and restore check failed" in start_script
    assert "KIMI_API_KEY =" not in configure_script


def test_integrated_portable_entry_points_and_bootstrap_are_fail_closed() -> None:
    start_cmd = (PROJECT_ROOT / "packaging" / "Start-Clinical-EDC.cmd").read_text(encoding="utf-8-sig")
    stop_cmd = (PROJECT_ROOT / "packaging" / "Stop-LibreClinica.cmd").read_text(encoding="utf-8-sig")
    start_script = (PROJECT_ROOT / "scripts" / "start_portable_stack.ps1").read_text(encoding="utf-8-sig")
    stop_script = (PROJECT_ROOT / "scripts" / "stop_portable_stack.ps1").read_text(encoding="utf-8-sig")
    host_preflight = (PROJECT_ROOT / "scripts" / "portable_host_preflight.ps1").read_text(encoding="utf-8-sig")

    assert "start_portable_stack.ps1" in start_cmd
    assert "stop_portable_stack.ps1" in stop_cmd
    assert "Invoke-DockerInfoProbe" in host_preflight
    assert "'info', '--format'" in host_preflight
    assert "docker load" in start_script
    assert "docker compose" in start_script
    assert "OFFLINE-ASSETS.sha256" in start_script
    assert "configure_kimi.ps1" in start_script
    assert "configure_libreclinica.ps1" in start_script
    assert "LibreClinica-ws/ws/studySubject/v1/studySubjectWsdl.wsdl" in start_script
    assert "ClinicalEdcCompanion.exe" in start_script
    assert "down" not in start_script
    assert "--volumes" not in stop_script
    assert "demo-password" not in start_script
    assert "KIMI_API_KEY=" not in start_script

    readiness_script = (PROJECT_ROOT / "scripts" / "check_production_readiness.py").read_text(encoding="utf-8")
    assert 'PROJECT_ROOT / ".runtime" / "backups"' in readiness_script
    assert "evaluate_production_readiness" in readiness_script
    assert "return 0 if report[\"status\"] == \"PASS\" else 1" in readiness_script

    verify_disk = (PROJECT_ROOT / "scripts" / "verify_disk_encryption.ps1").read_text(encoding="utf-8-sig")
    assert "Run this read-only verification script from an elevated PowerShell window" in verify_disk
    assert "manage-bde.exe -status" in verify_disk

    configure_libreclinica = (PROJECT_ROOT / "scripts" / "configure_libreclinica_portable.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "RandomNumberGenerator" in configure_libreclinica
    assert "ConvertFrom-SecureString" in configure_libreclinica
    assert "libreclinica-login.dpapi.json" in configure_libreclinica
    assert "demo-password" not in configure_libreclinica


def test_lite_portable_entrypoint_has_no_container_runtime_dependency() -> None:
    start_cmd = (PROJECT_ROOT / "packaging" / "Start-Clinical-EDC-Lite.cmd").read_text(
        encoding="utf-8-sig"
    )
    configure_cmd = (PROJECT_ROOT / "packaging" / "Configure-Kimi.cmd").read_text(
        encoding="utf-8-sig"
    )
    build_script = (PROJECT_ROOT / "scripts" / "build_windows_lite.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert "Start-Clinical-EDC-Lite.exe" in start_cmd
    assert "--lite" in start_cmd
    assert "docker" not in start_cmd.lower()
    assert "wsl" not in start_cmd.lower()
    assert "configure_kimi.ps1" in configure_cmd
    assert "ClinicalReportExtractorLite-windows-x64.zip" in build_script
    assert "verify_portable_lite_pdf.py" in build_script
    assert "-ArgumentList '--port'" in build_script
    assert "docker " not in build_script.lower()
    assert "docker.exe" not in build_script.lower()


def test_windows_lite_icon_is_branded_portable_and_credential_free() -> None:
    icon_path = PROJECT_ROOT / "packaging" / "assets" / "clinical-report-extractor-lite-icon.ico"
    provenance_path = icon_path.with_suffix(".provenance.json")
    spec = (PROJECT_ROOT / "packaging" / "ClinicalEdcCompanion.spec").read_text(
        encoding="utf-8-sig"
    )
    build_script = (PROJECT_ROOT / "scripts" / "build_windows_lite.ps1").read_text(
        encoding="utf-8-sig"
    )

    with Image.open(icon_path) as icon:
        assert {(16, 16), (32, 32), (48, 48), (256, 256)}.issubset(
            icon.info["sizes"]
        )

    provenance_text = provenance_path.read_text(encoding="utf-8")
    provenance = json.loads(provenance_text)
    assert provenance["provider"] == "Dreamina CLI"
    assert provenance["source_ai_label_present"] is True
    assert provenance["contains_credentials"] is False
    assert "api_key" not in provenance_text.lower()

    assert "clinical-report-extractor-lite-icon.ico" in spec
    assert '"Start-Clinical-EDC-Lite"' in spec
    assert "$executableName = 'Start-Clinical-EDC-Lite'" in build_script
    assert "Start-Clinical-EDC-Lite.lnk" not in build_script
    assert "CreateShortcut" not in build_script
    assert "$compatibilityDirectory" in build_script
    assert "FileAttributes]::Hidden" not in build_script
    assert "Get-ChildItem -LiteralPath $bundleDirectory -Recurse -Force -File" in build_script


def test_centre_package_builder_is_windows_only_profile_scoped_and_blackbox_verified() -> None:
    builder = (PROJECT_ROOT / "scripts" / "build_windows_centre_package.ps1").read_text(
        encoding="utf-8-sig"
    )
    guide = (PROJECT_ROOT / "packaging" / "README-START-CENTRE.txt").read_text(
        encoding="utf-8-sig"
    )

    assert "centre-profile.json" in builder
    assert "verify_portable_lite_pdf.py" in builder
    assert "--centre-code" in builder
    assert "--username" in builder
    assert "--image" in builder
    assert "kimi_local_fallback = 'verified'" in builder
    assert "encrypted_centre_package_export = 'verified'" in builder
    assert "ClinicalReportExtractorLite-$CentreCode-windows-x64.zip" in builder
    assert "build_macos" not in builder
    assert "demo-password" not in guide
    assert "中央管理员账号" in guide
    assert "Reset-Centre-Password.cmd" in builder
    assert "Get-ChildItem -LiteralPath $bundleDirectory -Recurse -Force -File" in builder
    assert "网页" in guide and "Kimi" in guide
    reset_cmd = (PROJECT_ROOT / "packaging" / "Reset-Centre-Password.cmd").read_text(
        encoding="utf-8-sig"
    )
    assert "--reset-centre-password" in reset_cmd


def test_macos_lite_build_is_native_local_only_and_blackbox_verified() -> None:
    build_script = (PROJECT_ROOT / "scripts" / "build_macos_lite.sh").read_text(
        encoding="utf-8"
    )
    configure_script = (PROJECT_ROOT / "packaging" / "Configure-Kimi.command").read_text(
        encoding="utf-8"
    )
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "build-macos-lite.yml").read_text(
        encoding="utf-8"
    )
    constraints = (PROJECT_ROOT / "packaging" / "macos-build-constraints.txt").read_text(
        encoding="utf-8"
    )

    assert '$(uname -s)' in build_script
    assert '$(uname -m)' in build_script
    assert "--windowed" in build_script
    assert "--onedir" in build_script
    assert "--target-arch" in build_script
    assert "--add-binary" in build_script
    assert "verify_portable_lite_pdf.py" in build_script
    assert "ClinicalReportExtractorLite-macos-${target_arch}.zip" in build_script
    assert "codesign --verify" in build_script
    assert "notarytool" in build_script
    assert "docker " not in build_script.lower()
    assert "docker.exe" not in build_script.lower()

    assert "read -r -s" in configure_script
    assert "chmod 600" in configure_script
    assert "kimi-api-key.txt" in configure_script
    assert "KIMI_API_KEY=" not in configure_script

    assert "macos-15" in workflow
    assert "macos-15-intel" in workflow
    assert "arm64" in workflow
    assert "x86_64" in workflow
    assert "build_macos_lite.sh" in workflow
    assert "macos-build-constraints.txt" in workflow
    assert "pyinstaller==6.21.0" in constraints
    assert "pypdf==6.15.0" in constraints


def test_macos_build_source_bundle_excludes_runtime_and_secrets() -> None:
    source_builder = (PROJECT_ROOT / "scripts" / "build_macos_source_bundle.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert "ClinicalReportExtractorLite-macos-build-source.zip" in source_builder
    assert "ZipArchiveMode" in source_builder
    assert ".Replace('\\', '/')" in source_builder
    assert "\\.runtime" in source_builder
    assert "\\.venv" in source_builder
    assert "'.p12'" in source_builder
    assert "'.mobileprovision'" in source_builder
    assert "pulmonary-function-field-dictionary.v1.json" in source_builder


def test_portable_compose_is_local_pinned_and_restores_a_clean_seed() -> None:
    compose_path = PROJECT_ROOT / "infrastructure" / "libreclinica" / "portable" / "compose.portable.yaml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    services = compose["services"]

    assert services["libreclinica"]["image"] == "clinical-edc-companion/libreclinica:1.4.0-sandbox"
    assert services["db"]["image"] == "postgres:16-alpine"
    assert services["smtp"]["image"] == "marlonb/mailcrab:v1.1.0"
    assert services["libreclinica"]["pull_policy"] == "never"
    assert services["db"]["pull_policy"] == "never"
    assert services["smtp"]["pull_policy"] == "never"
    assert services["libreclinica"]["ports"] == ["127.0.0.1:${LIBRECLINICA_HOST_PORT:-8081}:8080"]
    assert services["smtp"]["ports"] == ["127.0.0.1:${LIBRECLINICA_SMTP_HOST_PORT:-1081}:1080"]
    assert "ports" not in services["db"]
    db_volumes = services["db"]["volumes"]
    assert any("/docker-entrypoint-initdb.d/10-restore.sh:ro" in value for value in db_volumes)
    assert any("/seed/libreclinica-portable-synthetic.dump:ro" in value for value in db_volumes)


def test_seed_builder_names_isolated_resources_and_asserts_no_clinical_rows() -> None:
    builder = (PROJECT_ROOT / "scripts" / "build_libreclinica_portable_seed.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert "clinical-edc-portable-seed-builder" in builder
    assert "TRUNCATE TABLE subject CASCADE" in builder
    assert "audit_user_login" in builder
    assert "passwd = repeat('0', 40)" in builder
    assert "study_subject" in builder
    assert "event_crf" in builder
    assert "item_data" in builder
    assert "pg_dump" in builder
    assert "pg_restore" in builder
    assert "libreclinica-synthetic-sandbox" not in builder


def test_virtualization_failure_replaces_docker_named_pipe_500_with_actionable_code() -> None:
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROJECT_ROOT / "scripts" / "verify_portable_host_preflight.ps1"),
            "-Scenario",
            "virtualization_disabled_with_docker_named_pipe_500",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "EDC-HOST-VIRTUALIZATION-DISABLED" in completed.stdout
    assert "dockerDesktopLinuxEngine" not in completed.stdout
    assert "v1.55/info" not in completed.stdout

    stderr_capture = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROJECT_ROOT / "scripts" / "verify_portable_host_preflight.ps1"),
            "-Scenario",
            "docker_named_pipe_stderr_capture",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert stderr_capture.returncode == 0, stderr_capture.stderr
    assert "EDC-HOST-DOCKER-ENGINE-NOT-READY" in stderr_capture.stdout
    assert "dockerDesktopLinuxEngine" not in stderr_capture.stdout
    assert "v1.55/info" not in stderr_capture.stdout


def test_portable_start_uses_host_preflight_before_docker_operations() -> None:
    start_script = (PROJECT_ROOT / "scripts" / "start_portable_stack.ps1").read_text(encoding="utf-8-sig")
    diagnose_cmd = (PROJECT_ROOT / "packaging" / "Diagnose-This-PC.cmd").read_text(encoding="utf-8-sig")
    repair_cmd = (PROJECT_ROOT / "packaging" / "Repair-Docker-Prerequisites.cmd").read_text(
        encoding="utf-8-sig"
    )

    assert ". (Join-Path $PSScriptRoot 'portable_host_preflight.ps1')" in start_script
    assert "Assert-PortableHostReady" in start_script
    assert start_script.index("Assert-PortableHostReady") < start_script.index("docker load")
    assert "diagnose_portable_host.ps1" in diagnose_cmd
    assert "repair_docker_prerequisites.ps1" in repair_cmd


def test_missing_portable_image_is_a_nonterminating_probe_before_offline_load() -> None:
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROJECT_ROOT / "scripts" / "verify_portable_host_preflight.ps1"),
            "-Scenario",
            "native_nonzero_is_nonterminating",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "EDC-HOST-NATIVE-NONZERO-CAPTURED" in completed.stdout
    assert "expected missing artifact" not in completed.stdout
    assert "expected missing artifact" not in completed.stderr

    start_script = (PROJECT_ROOT / "scripts" / "start_portable_stack.ps1").read_text(encoding="utf-8-sig")
    assert "Invoke-PortableProcessQuiet" in start_script
    assert "& docker image inspect" not in start_script
    assert "& docker exec $dbContainer pg_isready" not in start_script
    assert "& docker compose -p $ComposeProject -f $composePath up -d" not in start_script


def test_portable_start_autostarts_and_waits_for_docker_desktop() -> None:
    host_preflight = (PROJECT_ROOT / "scripts" / "portable_host_preflight.ps1").read_text(encoding="utf-8-sig")
    desktop_start_body = host_preflight.split("function Invoke-DockerDesktopStart", 1)[1].split(
        "function Start-DockerDesktopAndWait", 1
    )[0]
    assert "WaitForExit(30000)" in desktop_start_body
    assert "-Wait `" not in desktop_start_body

    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROJECT_ROOT / "scripts" / "verify_portable_host_preflight.ps1"),
            "-Scenario",
            "docker_engine_autostart_ready",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "EDC-HOST-DOCKER-AUTOSTART-READY" in completed.stdout

    timeout_completed = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROJECT_ROOT / "scripts" / "verify_portable_host_preflight.ps1"),
            "-Scenario",
            "docker_engine_autostart_timeout",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert timeout_completed.returncode == 0, timeout_completed.stderr
    assert "EDC-HOST-DOCKER-AUTOSTART-TIMEOUT" in timeout_completed.stdout

    start_script = (PROJECT_ROOT / "scripts" / "start_portable_stack.ps1").read_text(encoding="utf-8-sig")
    assert start_script.index("Start-DockerDesktopAndWait") < start_script.index("Assert-PortableHostReady")


def test_active_windows_hypervisor_prevents_false_slat_block() -> None:
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROJECT_ROOT / "scripts" / "verify_portable_host_preflight.ps1"),
            "-Scenario",
            "active_hypervisor_with_ambiguous_slat",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "EDC-HOST-READY" in completed.stdout


def test_portable_build_reuses_and_verifies_cached_libreclinica_image_offline() -> None:
    build_script = (PROJECT_ROOT / "scripts" / "build_windows_portable.ps1").read_text(encoding="utf-8-sig")

    assert "Test-PortableLibreClinicaImage" in build_script
    assert "docker image inspect $portableImage" in build_script
    assert "sha256sum" in build_script
    assert "25378635ab396195d2bc8d58ee2988383fccf0699d2c5222800c8a37524179c7" in build_script
    assert "1f57e077d30f39b2f6c7b584ddd405420b3a990d33773fdb122019c0a8083487" in build_script
