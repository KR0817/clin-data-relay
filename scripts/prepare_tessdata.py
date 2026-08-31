"""Prepare the two pinned Tesseract language files used by portable builds."""

from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESTINATION = PROJECT_ROOT / "vendor" / "tessdata_fast"
UPSTREAM_COMMIT = "87416418657359cb625c412a48b6e1d6d41c29bd"
MAX_DOWNLOAD_BYTES = 16 * 1024 * 1024
LANGUAGE_FILES = {
    "eng.traineddata": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
    "chi_sim.traineddata": "a5fcb6f0db1e1d6d8522f39db4e848f05984669172e584e8d76b6b3141e1f730",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(name: str, destination: Path) -> None:
    url = (
        "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/"
        f"{UPSTREAM_COMMIT}/{name}"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "ClinData-Relay-build"})
    downloaded = 0
    with urllib.request.urlopen(request, timeout=60) as response, destination.open(
        "wb"
    ) as target:
        while chunk := response.read(1024 * 1024):
            downloaded += len(chunk)
            if downloaded > MAX_DOWNLOAD_BYTES:
                raise RuntimeError(f"tessdata_download_too_large:{name}")
            target.write(chunk)


def prepare() -> None:
    missing = [
        name
        for name, expected in LANGUAGE_FILES.items()
        if not (DESTINATION / name).is_file()
        or sha256(DESTINATION / name) != expected
    ]
    if not missing:
        print("PASS: pinned tessdata cache is ready")
        return

    DESTINATION.mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / ".runtime").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="tessdata-", dir=PROJECT_ROOT / ".runtime"
    ) as temporary_directory:
        temporary_root = Path(temporary_directory)
        for name in missing:
            temporary_path = temporary_root / name
            download(name, temporary_path)
            if sha256(temporary_path) != LANGUAGE_FILES[name]:
                raise RuntimeError(f"tessdata_digest_mismatch:{name}")
            os.replace(temporary_path, DESTINATION / name)

    for name, expected in LANGUAGE_FILES.items():
        if sha256(DESTINATION / name) != expected:
            raise RuntimeError(f"tessdata_cache_validation_failed:{name}")
    print("PASS: pinned tessdata cache prepared")


if __name__ == "__main__":
    prepare()
