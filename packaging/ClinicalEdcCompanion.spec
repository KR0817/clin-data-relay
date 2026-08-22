import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


project_root = Path.cwd()
binary_name = os.getenv("COMPANION_BINARY_NAME", "ClinicalEdcCompanion")
if binary_name not in {"ClinicalEdcCompanion", "ClinicalReportExtractorLite"}:
    raise ValueError("unsupported_binary_name")
executable_name = (
    "Start-Clinical-EDC-Lite"
    if binary_name == "ClinicalReportExtractorLite"
    else binary_name
)
icon_path = (
    project_root / "packaging" / "assets" / "clinical-report-extractor-lite-icon.ico"
    if binary_name == "ClinicalReportExtractorLite"
    else None
)
datas = [
    (str(project_root / "app" / "static"), "app/static"),
    (str(project_root / "vendor" / "tessdata_fast"), "vendor/tessdata_fast"),
]
if binary_name == "ClinicalReportExtractorLite":
    for config_name in (
        "chinese_lab_aliases.v0.1.json",
        "clinical_quality_rules.v1.json",
        "pulmonary-function-field-dictionary.v1.json",
        "rct-full-field-dictionary.v0.2.json",
        "synthetic_lab_mapping.v0.1.json",
    ):
        datas.append((str(project_root / "config" / config_name), "config"))
else:
    datas.append((str(project_root / "config"), "config"))
hiddenimports = collect_submodules("uvicorn") + collect_submodules("pypdf")

a = Analysis(
    [str(project_root / "app" / "windows_launcher.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=executable_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path is not None else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=binary_name,
    contents_directory="_internal",
)
