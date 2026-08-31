#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PYTHON_BIN:-$project_root/.venv/bin/python}"
verification_port="${VERIFICATION_PORT:-8013}"
host_arch="$(uname -m)"
target_arch="${TARGET_ARCH:-$host_arch}"
binary_name="ClinicalReportExtractorLite"
dist_root="$project_root/dist/macos-$target_arch"
build_root="$project_root/build/pyinstaller-macos-$target_arch"
app_path="$dist_root/$binary_name.app"
package_root="$dist_root/$binary_name-macos-$target_arch"
archive_path="$project_root/dist/ClinicalReportExtractorLite-macos-${target_arch}.zip"
verification_path="$project_root/dist/ClinicalReportExtractorLite-macos-${target_arch}.verification.json"
qa_root="$project_root/.runtime/portable-lite-macos-build-qa-$target_arch"
codesign_identity="${MACOS_CODESIGN_IDENTITY:-}"
notary_profile="${MACOS_NOTARY_KEYCHAIN_PROFILE:-}"

assert_project_descendant() {
  case "$1" in
    "$project_root"/*) ;;
    *) echo "Refusing to modify a path outside the project root: $1" >&2; exit 1 ;;
  esac
}

remove_project_target() {
  assert_project_descendant "$1"
  if [[ -e "$1" ]]; then
    rm -rf -- "$1"
  fi
}

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This build must run on macOS; PyInstaller cannot cross-compile the app." >&2
  exit 1
fi
if [[ "$target_arch" != "arm64" && "$target_arch" != "x86_64" ]]; then
  echo "TARGET_ARCH must be arm64 or x86_64." >&2
  exit 1
fi
if [[ "$host_arch" != "$target_arch" ]]; then
  echo "Native build required: host is $host_arch but TARGET_ARCH is $target_arch." >&2
  exit 1
fi
if [[ ! "$verification_port" =~ ^[0-9]+$ ]] || (( verification_port < 1024 || verification_port > 65535 )); then
  echo "VERIFICATION_PORT must be between 1024 and 65535." >&2
  exit 1
fi
if [[ ! -x "$python_bin" ]]; then
  echo "Project Python is missing: $python_bin" >&2
  exit 1
fi

tesseract_binary="$(command -v tesseract || true)"
if [[ -z "$tesseract_binary" || ! -x "$tesseract_binary" ]]; then
  echo "Tesseract is required on the macOS build host only." >&2
  exit 1
fi

if [[ "${SKIP_TESTS:-false}" != "true" ]]; then
  "$python_bin" -m pytest \
    tests/test_windows_launcher.py \
    tests/test_runtime_scripts.py::test_macos_lite_build_is_native_local_only_and_blackbox_verified \
    tests/test_api.py::test_lite_health_reports_local_only_product_mode \
    tests/test_api.py::test_homepage_contains_lite_profile_for_local_recognition_review_and_export \
    tests/test_pulmonary_function.py \
    tests/test_offline_package.py \
    tests/test_spreadsheet_export.py \
    -q
fi

remove_project_target "$dist_root"
remove_project_target "$build_root"
remove_project_target "$archive_path"
remove_project_target "$verification_path"
remove_project_target "$qa_root"
mkdir -p "$dist_root" "$build_root" "$qa_root"

pyinstaller_args=(
  --noconfirm
  --clean
  --onedir
  --windowed
  --noupx
  --name "$binary_name"
  --distpath "$dist_root"
  --workpath "$build_root"
  --target-arch "$target_arch"
  --osx-bundle-identifier "org.clinicaledc.reportextractorlite"
  --collect-submodules uvicorn
  --collect-submodules pypdf
  --add-data "$project_root/app/static:app/static"
  --add-data "$project_root/vendor/tessdata_fast:vendor/tessdata_fast"
  --add-data "$project_root/config/chinese_lab_aliases.v0.1.json:config"
  --add-data "$project_root/config/clinical_quality_rules.v1.json:config"
  --add-data "$project_root/config/pulmonary-function-field-dictionary.v1.json:config"
  --add-data "$project_root/config/rct-full-field-dictionary.v0.2.json:config"
  --add-data "$project_root/config/synthetic_lab_mapping.v0.1.json:config"
  --add-binary "$tesseract_binary:runtime/tesseract"
)
if [[ -n "$codesign_identity" ]]; then
  pyinstaller_args+=(--codesign-identity "$codesign_identity")
fi

(
  cd "$project_root"
  "$python_bin" -m PyInstaller "${pyinstaller_args[@]}" app/macos_lite_launcher.py
)

if [[ ! -d "$app_path" || ! -x "$app_path/Contents/MacOS/$binary_name" ]]; then
  echo "Built macOS app is missing: $app_path" >&2
  exit 1
fi

codesign --verify --deep --strict --verbose=2 "$app_path"
if [[ -n "$notary_profile" ]]; then
  if [[ -z "$codesign_identity" ]]; then
    echo "MACOS_NOTARY_KEYCHAIN_PROFILE requires MACOS_CODESIGN_IDENTITY." >&2
    exit 1
  fi
  notary_upload="$qa_root/notarization-upload.zip"
  ditto -c -k --keepParent "$app_path" "$notary_upload"
  xcrun notarytool submit "$notary_upload" --keychain-profile "$notary_profile" --wait
  xcrun stapler staple "$app_path"
  xcrun stapler validate "$app_path"
  spctl --assess --type execute --verbose=2 "$app_path"
fi

mkdir -p "$package_root/docs" "$package_root/third-party-licenses"
ditto "$app_path" "$package_root/$binary_name.app"
install -m 755 "$project_root/packaging/Configure-Kimi.command" "$package_root/Configure-Kimi.command"
install -m 644 "$project_root/packaging/README-START-MACOS-LITE.txt" "$package_root/README-START.txt"
install -m 644 "$project_root/packaging/THIRD-PARTY-NOTICES-LITE.txt" "$package_root/THIRD-PARTY-NOTICES.txt"
install -m 644 "$project_root/LICENSE" "$package_root/LICENSE"
install -m 644 "$project_root/packaging/SOURCE-CODE.txt" "$package_root/SOURCE-CODE.txt"
install -m 644 "$project_root/docs/macos-lite-distribution.md" "$package_root/docs/macos-lite-distribution.md"

site_packages="$($python_bin -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
openpyxl_license="$(find "$site_packages" -path '*/openpyxl-*.dist-info/LICENCE.rst' -type f -print -quit)"
pyinstaller_license="$(find "$site_packages" -path '*/pyinstaller-*.dist-info/licenses/COPYING.txt' -type f -print -quit)"
pypdf_license="$(find "$site_packages" -path '*/pypdf-*.dist-info/licenses/LICENSE' -type f -print -quit)"
tesseract_prefix="$(brew --prefix tesseract 2>/dev/null || dirname "$(dirname "$tesseract_binary")")"
tesseract_license="$(find "$tesseract_prefix" -maxdepth 5 -type f -name LICENSE -print -quit)"
for license_path in "$openpyxl_license" "$pyinstaller_license" "$pypdf_license" "$tesseract_license"; do
  if [[ -z "$license_path" || ! -f "$license_path" ]]; then
    echo "A required third-party license text is missing." >&2
    exit 1
  fi
done
install -m 644 "$openpyxl_license" "$package_root/third-party-licenses/openpyxl-LICENCE.rst"
install -m 644 "$pyinstaller_license" "$package_root/third-party-licenses/PyInstaller-COPYING.txt"
install -m 644 "$pypdf_license" "$package_root/third-party-licenses/pypdf-LICENSE.txt"
install -m 644 "$tesseract_license" "$package_root/third-party-licenses/Tesseract-LICENSE.txt"

if find "$package_root" -type f \( -name '.env' -o -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' -o -name '*.log' -o -name '*.key' -o -name '*.pem' \) -print -quit | grep -q .; then
  echo "Forbidden secret or runtime data entered the macOS Lite package." >&2
  exit 1
fi
if find "$package_root" -iname '*libreclinica*' -o -iname '*postgres*' -o -iname '*mailcrab*' -o -iname '*compose*' -o -iname '*docker*' | grep -q .; then
  echo "Authority or container assets entered the macOS Lite package." >&2
  exit 1
fi

synthetic_pdf="$qa_root/synthetic-pulmonary-report.pdf"
"$python_bin" "$project_root/scripts/generate_synthetic_pulmonary_pdf.py" "$synthetic_pdf"
health_json="$qa_root/health.json"
stdout_log="$qa_root/stdout.log"
stderr_log="$qa_root/stderr.log"
COMPANION_PORTABLE_DATA_ROOT="$qa_root/data-root" \
  "$app_path/Contents/MacOS/$binary_name" --port "$verification_port" --no-browser \
  >"$stdout_log" 2>"$stderr_log" &
app_pid=$!
cleanup_process() {
  if kill -0 "$app_pid" 2>/dev/null; then
    kill "$app_pid" 2>/dev/null || true
    wait "$app_pid" 2>/dev/null || true
  fi
}
trap cleanup_process EXIT

for _ in $(seq 1 120); do
  if curl --fail --silent --show-error "http://127.0.0.1:$verification_port/api/health" -o "$health_json"; then
    break
  fi
  if ! kill -0 "$app_pid" 2>/dev/null; then
    echo "Built macOS app exited before health became ready." >&2
    tail -n 60 "$stderr_log" >&2 || true
    exit 1
  fi
  sleep 0.5
done
if [[ ! -s "$health_json" ]]; then
  echo "Built macOS app did not become healthy within 60 seconds." >&2
  exit 1
fi

"$python_bin" - "$health_json" <<'PY'
import json
import sys

health = json.loads(open(sys.argv[1], encoding="utf-8").read())
expected = {
    "status": "ok",
    "product_mode": "lite",
    "data_boundary": "synthetic_only",
    "local_ocr": "local_only",
    "excel_export": "ready",
    "edc_adapter": "fail_closed_simulation_only",
}
for key, value in expected.items():
    if health.get(key) != value:
        raise SystemExit(f"macos_lite_health_mismatch:{key}")
if health.get("production_readiness", {}).get("status") != "BLOCK":
    raise SystemExit("macos_lite_readiness_mismatch")
PY

"$python_bin" "$project_root/scripts/verify_portable_lite_pdf.py" \
  --base-url "http://127.0.0.1:$verification_port" \
  --pdf "$synthetic_pdf"
cleanup_process
trap - EXIT

manifest_path="$package_root/MANIFEST.sha256"
(
  cd "$package_root"
  find . -type f ! -name 'MANIFEST.sha256' -print0 \
    | sort -z \
    | while IFS= read -r -d '' item; do
        hash="$(shasum -a 256 "$item" | awk '{print $1}')"
        printf '%s  %s\n' "$hash" "${item#./}"
      done
) >"$manifest_path"

signing_state="ad_hoc"
notarized="false"
if [[ -n "$codesign_identity" ]]; then signing_state="developer_id"; fi
if [[ -n "$notary_profile" ]]; then notarized="true"; fi
executable_hash="$(shasum -a 256 "$app_path/Contents/MacOS/$binary_name" | awk '{print $1}')"
VERIFICATION_PATH="$verification_path" \
TARGET_ARCH_VALUE="$target_arch" \
EXECUTABLE_HASH_VALUE="$executable_hash" \
SIGNING_STATE_VALUE="$signing_state" \
NOTARIZED_VALUE="$notarized" \
"$python_bin" - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path

payload = {
    "verified_at": datetime.now(timezone.utc).isoformat(),
    "platform": "macOS",
    "architecture": os.environ["TARGET_ARCH_VALUE"],
    "executable_sha256": os.environ["EXECUTABLE_HASH_VALUE"],
    "signing": os.environ["SIGNING_STATE_VALUE"],
    "notarized": os.environ["NOTARIZED_VALUE"] == "true",
    "container_runtime_required": False,
    "authority_edc_included": False,
    "pulmonary_pdf_candidates": 18,
    "human_review": "verified",
    "reviewed_excel_export": "verified",
    "health": {
        "status": "ok",
        "product_mode": "lite",
        "local_ocr": "local_only",
        "excel_export": "ready",
        "edc_adapter": "fail_closed_simulation_only",
        "production_readiness": "BLOCK",
    },
}
Path(os.environ["VERIFICATION_PATH"]).write_text(
    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
PY

ditto -c -k --sequesterRsrc --keepParent "$package_root" "$archive_path"
archive_hash="$(shasum -a 256 "$archive_path" | awk '{print $1}')"
remove_project_target "$qa_root"

echo "PASS: macOS Lite app: $app_path"
echo "PASS: macOS Lite ZIP: $archive_path"
echo "PASS: Verification report: $verification_path"
echo "SHA256: $archive_hash"
