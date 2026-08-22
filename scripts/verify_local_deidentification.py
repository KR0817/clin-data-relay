"""Synthetic-only end-to-end verification for local redaction and candidate extraction."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app.main import create_app


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="clinical-edc-deidentification-") as temporary_directory:
        temporary_path = Path(temporary_directory)
        image_path = temporary_path / "synthetic_identified_check_sheet.png"
        image = Image.new("RGB", (1800, 600), "white")
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 72)
        ImageDraw.Draw(image).text(
            (80, 65),
            "姓名：合成测试对象\nALT 31 9-50 U/L",
            fill="black",
            font=font,
            spacing=70,
        )
        image.save(image_path)
        original_sha256 = hashlib.sha256(image_path.read_bytes()).hexdigest()

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
            draft_response = client.post(
                f"/api/source-files/{upload.json()['id']}/deidentification-drafts",
                headers=headers,
            )
            assert draft_response.status_code == 201, draft_response.text
            draft = draft_response.json()
            assert draft["status"] == "draft", draft
            assert "patient_name" in draft["detected_marker_codes"], draft
            assert draft["derivative_source_file"]["sha256"] != original_sha256, draft

            preview = client.get(
                f"/api/deidentification-drafts/{draft['id']}/image",
                headers=headers,
            )
            assert preview.status_code == 200, preview.text
            assert preview.headers["cache-control"] == "no-store", preview.headers
            assert hashlib.sha256(preview.content).hexdigest() == draft["derivative_source_file"]["sha256"]

            blocked = client.post(
                f"/api/source-files/{draft['derivative_source_file']['id']}/local-ocr-extract",
                headers=headers,
                json={"edc_subject_ref": "SUBJ001", "edc_event_ref": "WEEK_0"},
            )
            assert blocked.status_code == 409, blocked.text
            assert blocked.json()["detail"] == "deidentification_confirmation_required", blocked.text

            confirmed = client.post(
                f"/api/deidentification-drafts/{draft['id']}/confirm",
                headers=headers,
                json={"human_review_attestation": True},
            )
            assert confirmed.status_code == 200, confirmed.text
            extracted = client.post(
                f"/api/source-files/{draft['derivative_source_file']['id']}/local-ocr-extract",
                headers=headers,
                json={"edc_subject_ref": "SUBJ001", "edc_event_ref": "WEEK_0"},
            )
            assert extracted.status_code == 201, extracted.text
            candidates = extracted.json()
            assert [(row["field_code"], row["proposed_value"], row["unit"]) for row in candidates] == [
                ("ALT", "31", "U/L")
            ], candidates
            assert all(row["kimi_model"] == "not_used_local_ocr" for row in candidates)
            print("PASS: local redaction draft removed a synthetic Chinese identifier line.")
            print("PASS: human confirmation unlocked local OCR and persisted one candidate without Kimi.")


if __name__ == "__main__":
    main()
