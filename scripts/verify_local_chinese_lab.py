"""Synthetic-only real-Tesseract verification for the conservative Chinese table fallback."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app.main import create_app


def create_fixture(output_path: Path) -> None:
    image = Image.new("RGB", (2600, 1050), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 64)
    draw.text((100, 60), "姓名：合成测试对象", fill="black", font=font)
    rows = (
        ((100, 300), "白蛋白定量 42.1 40.0-55.0", (1380, 300), "总胆红素 12.3 5-21"),
        ((100, 600), "全血高敏C-反应蛋白 <0.5 <8", (1380, 600), "白细胞计数 4.50 3.5-9.5"),
    )
    for left_position, left_text, right_position, right_text in rows:
        draw.text(left_position, left_text, fill="black", font=font)
        draw.text(right_position, right_text, fill="black", font=font)
    image.save(output_path)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="clinical-edc-chinese-lab-") as temporary_directory:
        temporary_path = Path(temporary_directory)
        image_path = temporary_path / "synthetic_chinese_lab.png"
        create_fixture(image_path)
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
            draft = client.post(
                f"/api/source-files/{upload.json()['id']}/deidentification-drafts",
                headers=headers,
            )
            assert draft.status_code == 201, draft.text
            assert "patient_name" in draft.json()["detected_marker_codes"], draft.text
            confirmed = client.post(
                f"/api/deidentification-drafts/{draft.json()['id']}/confirm",
                headers=headers,
                json={"human_review_attestation": True},
            )
            assert confirmed.status_code == 200, confirmed.text
            extracted = client.post(
                f"/api/source-files/{draft.json()['derivative_source_file']['id']}/local-ocr-extract",
                headers=headers,
                json={"edc_subject_ref": "SUBJ-ZH", "edc_event_ref": "WEEK_0"},
            )
            assert extracted.status_code == 201, extracted.text
            actual = [(row["field_code"], row["proposed_value"], row["unit"]) for row in extracted.json()]
            expected = [
                ("ALB", "42.1", None),
                ("TBIL", "12.3", None),
                ("CRP", "<0.5", None),
                ("WBC", "4.50", None),
            ]
            assert actual == expected, actual
            assert all("alias=zh-lab-v0.1-exact-labels" in row["ocr_engine_version"] for row in extracted.json())
            assert all(row["kimi_model"] == "not_used_local_ocr" for row in extracted.json())
            print("PASS: Chinese identifier line was redacted before structured table extraction.")
            print("PASS: four exact-label Chinese laboratory candidates persisted without Kimi.")


if __name__ == "__main__":
    main()
