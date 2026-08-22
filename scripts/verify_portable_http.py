"""Exercise the built portable EXE over HTTP with an obviously synthetic report."""

from __future__ import annotations

import argparse
from pathlib import Path

import httpx

from generate_synthetic_check_sheet import create_synthetic_check_sheet


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the running portable companion over localhost HTTP.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8012")
    parser.add_argument("--work-directory", type=Path, required=True)
    args = parser.parse_args()
    args.work_directory.mkdir(parents=True, exist_ok=True)
    image_path = args.work_directory / "synthetic-portable-check-sheet.png"
    create_synthetic_check_sheet(image_path)

    with httpx.Client(base_url=args.base_url, timeout=60) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": "site-a-investigator@example.test", "password": "demo-password"},
        )
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        upload = client.post(
            "/api/source-files/upload",
            headers=headers,
            files={"file": (image_path.name, image_path.read_bytes(), "image/png")},
            data={"synthetic_attestation": "true"},
        )
        upload.raise_for_status()
        extracted = client.post(
            f"/api/source-files/{upload.json()['id']}/local-ocr-extract",
            headers=headers,
            json={"edc_subject_ref": "PORTABLE001", "edc_event_ref": "WEEK_0"},
        )
        extracted.raise_for_status()
        actual = [
            (candidate["field_code"], candidate["proposed_value"], candidate["unit"])
            for candidate in extracted.json()
        ]
        expected = [
            ("WBC", "4.50", "10E9/L"),
            ("ALT", "31", "U/L"),
            ("K", "3.9", "mmol/L"),
            ("CRP", "2.3", "mg/L"),
        ]
        if actual != expected:
            raise RuntimeError(f"portable_ocr_mismatch:{actual!r}")

        workbook = client.get("/api/exports/submitted-data.xlsx", headers=headers)
        workbook.raise_for_status()
        if not workbook.content.startswith(b"PK"):
            raise RuntimeError("portable_excel_export_invalid")

    print("PASS: Built EXE parsed four synthetic OCR values and generated an Excel workbook over HTTP.")


if __name__ == "__main__":
    main()
