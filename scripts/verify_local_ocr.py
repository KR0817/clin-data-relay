"""Synthetic-only end-to-end verification for the local Tesseract OCR endpoint."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from generate_synthetic_check_sheet import create_synthetic_check_sheet


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="clinical-edc-ocr-") as temporary_directory:
        temporary_path = Path(temporary_directory)
        image_path = temporary_path / "synthetic_lab_report.png"
        create_synthetic_check_sheet(image_path)

        app = create_app(database_path=temporary_path / "companion.db", environment="test")
        with TestClient(app) as client:
            login = client.post(
                "/api/auth/login",
                json={"username": "site-a-investigator@example.test", "password": "demo-password"},
            )
            assert login.status_code == 200, login.text
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            upload = client.post(
                "/api/source-files/upload",
                headers=headers,
                files={"file": (image_path.name, image_path.read_bytes(), "image/png")},
                data={"synthetic_attestation": "true"},
            )
            assert upload.status_code == 201, upload.text
            extracted = client.post(
                f"/api/source-files/{upload.json()['id']}/local-ocr-extract",
                headers=headers,
                json={"edc_subject_ref": "SUBJ001", "edc_event_ref": "WEEK_0"},
            )
            assert extracted.status_code == 201, extracted.text
            candidates = extracted.json()
            actual = [(candidate["field_code"], candidate["proposed_value"], candidate["unit"]) for candidate in candidates]
            expected = [
                ("WBC", "4.50", "10E9/L"),
                ("ALT", "31", "U/L"),
                ("K", "3.9", "mmol/L"),
                ("CRP", "2.3", "mg/L"),
            ]
            assert actual == expected, actual
            assert all(candidate["kimi_model"] == "not_used_local_ocr" for candidate in candidates)
            listed = client.get("/api/candidates", headers=headers)
            assert listed.status_code == 200, listed.text
            assert {candidate["id"] for candidate in listed.json()} == {candidate["id"] for candidate in candidates}
            print("PASS: local Tesseract OCR parsed a synthetic check sheet and persisted candidates without Kimi.")


if __name__ == "__main__":
    main()
