from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app.main import create_app


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="clinical-edc-ocr-privacy-") as temporary_directory:
        temporary_path = Path(temporary_directory)
        image_path = temporary_path / "synthetic_direct_identifier_regression.png"
        image = Image.new("RGB", (1600, 500), "white")
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 72)
        ImageDraw.Draw(image).text(
            (80, 70),
            "姓名：合成测试对象\nALT 31 9-50 U/L",
            fill="black",
            font=font,
            spacing=45,
        )
        image.save(image_path)

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
            assert extracted.status_code == 422, extracted.text
            assert extracted.json()["detail"] == "deidentified_text_required", extracted.text
            candidates = client.get("/api/candidates", headers=headers)
            assert candidates.status_code == 200, candidates.text
            assert candidates.json() == [], candidates.text
            print("PASS: Chinese direct-identifier text was rejected before candidate persistence.")


if __name__ == "__main__":
    main()
