"""Synthetic-only live proof: upload, provision, OCR, review, SOAP import, read-back."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx

from generate_synthetic_check_sheet import create_synthetic_check_sheet


BASE_URL = "http://127.0.0.1:8000"
SUBJECT_REF = "SUBJ004"
EVENT_REF = "WEEK_0"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = PROJECT_ROOT / "work" / "live_e2e" / "subj004_synthetic_lab.png"


def main() -> None:
    create_synthetic_check_sheet(FIXTURE_PATH)
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": "site-a-investigator@example.test", "password": "demo-password"},
        )
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        with FIXTURE_PATH.open("rb") as image:
            upload = client.post(
                "/api/source-files/upload",
                headers=headers,
                files={"file": (FIXTURE_PATH.name, image, "image/png")},
                data={
                    "synthetic_attestation": "true",
                    "edc_subject_ref": SUBJECT_REF,
                    "edc_event_ref": EVENT_REF,
                },
            )
        if not upload.is_success:
            raise RuntimeError(f"upload_failed:{upload.status_code}:{upload.text}")
        source = upload.json()
        provision = source["edc_subject_provisioning"]
        if provision["subject_ref"] != SUBJECT_REF or provision["event_ref"] != EVENT_REF:
            raise RuntimeError("unexpected_provisioning_response")

        extracted = client.post(
            f"/api/source-files/{source['id']}/local-ocr-extract",
            headers=headers,
            json={"edc_subject_ref": SUBJECT_REF, "edc_event_ref": EVENT_REF},
        )
        extracted.raise_for_status()
        candidates = extracted.json()
        wbc = next(candidate for candidate in candidates if candidate["field_code"] == "WBC")

        reviewed = client.post(
            f"/api/candidates/{wbc['id']}/review",
            headers=headers,
            json={"decision": "accept", "reason": "Synthetic source checked for live interface verification."},
        )
        reviewed.raise_for_status()

        transfer = client.post(f"/api/candidates/{wbc['id']}/transfers", headers=headers)
        transfer.raise_for_status()
        submitted = client.post(f"/api/transfers/{transfer.json()['id']}/submit", headers=headers)
        submitted.raise_for_status()
        submission = submitted.json()
        if submission["status"] != "submitted" or not submission["external_reference"]:
            raise RuntimeError("authority_submission_not_confirmed")

    query = (
        "SELECT ss.label,sed.name,i.name,id.value,u.user_name "
        "FROM item_data id "
        "JOIN item i ON i.item_id=id.item_id "
        "JOIN event_crf ec ON ec.event_crf_id=id.event_crf_id "
        "JOIN study_event se ON se.study_event_id=ec.study_event_id "
        "JOIN study_event_definition sed ON sed.study_event_definition_id=se.study_event_definition_id "
        "JOIN study_subject ss ON ss.study_subject_id=se.study_subject_id "
        "LEFT JOIN user_account u ON u.user_id=ec.owner_id "
        "WHERE ss.label='SUBJ004' AND sed.name='Synthetic week 0 full validation' "
        "AND i.name='RCT_W0_WBC' ORDER BY id.item_data_id DESC LIMIT 1;"
    )
    readback = subprocess.run(
        [
            "docker", "exec", "libreclinica-synthetic-sandbox-db-1", "psql",
            "-U", "clinica", "-d", "libreclinica", "-A", "-t", "-F", "\t", "-c", query,
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip().split("\t")
    if readback[:4] != [SUBJECT_REF, "Synthetic week 0 full validation", "RCT_W0_WBC", "4.50"]:
        raise RuntimeError(f"unexpected_authority_readback:{readback}")

    print(
        json.dumps(
            {
                "source_file_id": source["id"],
                "subject_provisioning": provision,
                "candidate_id": wbc["id"],
                "transfer_id": submission["id"],
                "external_reference": submission["external_reference"],
                "authority_readback": {
                    "subject_ref": readback[0],
                    "event": readback[1],
                    "item": readback[2],
                    "value": readback[3],
                    "owner": readback[4],
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
