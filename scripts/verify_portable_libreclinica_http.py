"""Verify a clean portable OCR-to-LibreClinica path with synthetic data only."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import httpx

from generate_synthetic_check_sheet import create_synthetic_check_sheet


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--db-container", required=True)
    parser.add_argument("--work-directory", type=Path, required=True)
    parser.add_argument("--subject-ref", default="PORTABLE-QA-001")
    parser.add_argument("--event-ref", default="WEEK_0")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.work_directory.mkdir(parents=True, exist_ok=True)
    fixture_path = args.work_directory / "portable_synthetic_lab.png"
    create_synthetic_check_sheet(fixture_path)

    with httpx.Client(base_url=args.base_url, timeout=60) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": "site-a-investigator@example.test", "password": "demo-password"},
        )
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        with fixture_path.open("rb") as image:
            upload = client.post(
                "/api/source-files/upload",
                headers=headers,
                files={"file": (fixture_path.name, image, "image/png")},
                data={
                    "synthetic_attestation": "true",
                    "edc_subject_ref": args.subject_ref,
                    "edc_event_ref": args.event_ref,
                },
            )
        upload.raise_for_status()
        source = upload.json()
        provisioning = source["edc_subject_provisioning"]
        if provisioning["subject_ref"] != args.subject_ref or provisioning["event_ref"] != args.event_ref:
            raise RuntimeError("portable_subject_provisioning_mismatch")

        extraction = client.post(
            f"/api/source-files/{source['id']}/local-ocr-extract",
            headers=headers,
            json={"edc_subject_ref": args.subject_ref, "edc_event_ref": args.event_ref},
        )
        extraction.raise_for_status()
        candidates = extraction.json()
        wbc = next(candidate for candidate in candidates if candidate["field_code"] == "WBC")

        review = client.post(
            f"/api/candidates/{wbc['id']}/review",
            headers=headers,
            json={"decision": "accept", "reason": ""},
        )
        review.raise_for_status()
        transfer = client.post(f"/api/candidates/{wbc['id']}/transfers", headers=headers)
        transfer.raise_for_status()
        submission = client.post(f"/api/transfers/{transfer.json()['id']}/submit", headers=headers)
        submission.raise_for_status()
        submitted = submission.json()
        if submitted["status"] != "submitted" or not submitted["external_reference"]:
            raise RuntimeError("portable_authority_submission_not_confirmed")

    query = (
        "SELECT ss.label,sed.name,i.name,id.value "
        "FROM item_data id "
        "JOIN item i ON i.item_id=id.item_id "
        "JOIN event_crf ec ON ec.event_crf_id=id.event_crf_id "
        "JOIN study_event se ON se.study_event_id=ec.study_event_id "
        "JOIN study_event_definition sed ON sed.study_event_definition_id=se.study_event_definition_id "
        "JOIN study_subject ss ON ss.study_subject_id=se.study_subject_id "
        f"WHERE ss.label='{args.subject_ref}' AND i.name='RCT_W0_WBC' "
        "ORDER BY id.item_data_id DESC LIMIT 1;"
    )
    readback = subprocess.run(
        [
            "docker",
            "exec",
            args.db_container,
            "psql",
            "-U",
            "clinica",
            "-d",
            "libreclinica",
            "-A",
            "-t",
            "-F",
            "\t",
            "-c",
            query,
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip().split("\t")
    if readback != [args.subject_ref, "Synthetic week 0 full validation", "RCT_W0_WBC", "4.50"]:
        raise RuntimeError(f"portable_authority_readback_mismatch:{readback}")

    print(
        json.dumps(
            {
                "subject_ref": args.subject_ref,
                "source_file_id": source["id"],
                "candidate_id": wbc["id"],
                "transfer_id": submitted["id"],
                "authority_value": readback[3],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
