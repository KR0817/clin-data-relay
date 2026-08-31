from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.edc_adapter import EdcAdapterError, EdcProvisioningResult, EdcSubmissionResult
from app.kimi import KimiCandidate, KimiServiceError
from app.main import create_app
from app.runtime_config import RuntimeConfigurationError


def synthetic_png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
    return buffer.getvalue()


SYNTHETIC_PNG_BYTES = synthetic_png_bytes()


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(database_path=tmp_path / "companion.db", environment="test")
    with TestClient(app) as test_client:
        yield test_client


def auth_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": "demo-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def workbench_script(client: TestClient) -> str:
    response = client.get("/static/js/workbench.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"
    return response.text


def create_candidate(
    client: TestClient,
    headers: dict[str, str],
    *,
    field_code: str = "ALT",
    proposed_value: str = "32",
) -> dict:
    source_response = client.post(
        "/api/source-files",
        headers=headers,
        json={
            "source_filename": "synthetic_lab_report.png",
            "sha256": "a" * 64,
            "mime_type": "image/png",
            "storage_key": "synthetic/site-a/synthetic_lab_report.png",
        },
    )
    assert source_response.status_code == 201
    source_file = source_response.json()

    candidate_response = client.post(
        "/api/candidates",
        headers=headers,
        json={
            "source_file_id": source_file["id"],
            "edc_subject_ref": "SUBJ001",
            "edc_event_ref": "WEEK_0",
            "field_code": field_code,
            "proposed_value": proposed_value,
            "unit": "U/L",
            "ocr_engine_version": "demo-ocr-0.1",
            "kimi_model": "kimi-k3",
            "schema_version": "lab-candidate-v1",
            "confidence": 0.87,
        },
    )
    assert candidate_response.status_code == 201
    return candidate_response.json()


def mark_candidate_as_confirmed_risky(
    client: TestClient,
    candidate: dict,
    *,
    extraction_agreement: str,
    local_value: str = "31",
) -> None:
    source_id = candidate["source_file_id"]
    original_source_id = f"original-{source_id}"
    now = "2026-08-17T00:00:00+00:00"
    with client.app.state.database.connect() as connection:
        connection.execute(
            """
            INSERT INTO source_files (
                id, centre_code, source_filename, sha256, mime_type, storage_key,
                created_by, created_at
            ) VALUES (?, 'SITE_A', 'original.png', ?, 'image/png', ?, ?, ?)
            """,
            (
                original_source_id,
                "b" * 64,
                f"synthetic/SITE_A/{original_source_id}.png",
                "site-a-investigator@example.test",
                now,
            ),
        )
        connection.execute(
            "UPDATE source_files SET storage_key = ? WHERE id = ?",
            (f"deidentified/SITE_A/{source_id}.png", source_id),
        )
        connection.execute(
            """
            INSERT INTO deidentification_drafts (
                id, original_source_file_id, derivative_source_file_id, centre_code,
                status, detected_marker_codes_json, ocr_engine_version,
                created_by, created_at, confirmed_by, confirmed_at
            ) VALUES (?, ?, ?, 'SITE_A', 'confirmed', '[]', 'test-redactor', ?, ?, ?, ?)
            """,
            (
                f"draft-{source_id}",
                original_source_id,
                source_id,
                "site-a-investigator@example.test",
                now,
                "site-a-investigator@example.test",
                now,
            ),
        )
        connection.execute(
            """
            UPDATE candidates
            SET extraction_agreement = ?, local_ocr_value = ?, local_ocr_unit = 'U/L'
            WHERE id = ?
            """,
            (extraction_agreement, local_value, candidate["id"]),
        )
    evidence_path = (
        client.app.state.database.database_path.parent
        / "deidentified_uploads"
        / "SITE_A"
        / f"{source_id}.png"
    )
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_bytes(SYNTHETIC_PNG_BYTES)


def test_centre_user_cannot_read_another_centre_candidate(client: TestClient) -> None:
    centre_a_headers = auth_headers(client, "site-a-investigator@example.test")
    candidate = create_candidate(client, centre_a_headers)

    centre_b_headers = auth_headers(client, "site-b-investigator@example.test")
    list_response = client.get("/api/candidates", headers=centre_b_headers)
    assert list_response.status_code == 200
    assert list_response.json() == []
    detail_response = client.get(f"/api/candidates/{candidate['id']}", headers=centre_b_headers)
    assert detail_response.status_code == 404


def test_recognition_job_ledger_is_role_scoped_and_cancellable(client: TestClient) -> None:
    site_a_headers = auth_headers(client, "site-a-investigator@example.test")
    source_response = client.post(
        "/api/source-files",
        headers=site_a_headers,
        json={
            "source_filename": "synthetic_job_report.png",
            "sha256": "b" * 64,
            "mime_type": "image/png",
            "storage_key": "synthetic/SITE_A/synthetic_job_report.png",
        },
    )
    assert source_response.status_code == 201
    source_file_id = source_response.json()["id"]

    created = client.post(
        "/api/recognition-jobs",
        headers=site_a_headers,
        json={
            "items": [
                {
                    "source_file_id": source_file_id,
                    "edc_subject_ref": "SUBJJOB",
                    "edc_event_ref": "WEEK_0",
                    "field_codes": ["ALT"],
                }
            ]
        },
    )
    assert created.status_code == 201
    job = created.json()
    assert job["status"] == "queued"
    assert job["items"][0]["status"] == "queued"
    assert "storage_key" not in json.dumps(job)

    site_b_headers = auth_headers(client, "site-b-investigator@example.test")
    assert client.get("/api/recognition-jobs", headers=site_b_headers).json() == []
    assert client.get(f"/api/recognition-jobs/{job['id']}", headers=site_b_headers).status_code == 404

    central_headers = auth_headers(client, "central-data-manager@example.test")
    monitor_created = client.post(
        "/api/admin/users",
        headers=central_headers,
        json={"username": "monitor@example.test", "role": "monitor"},
    )
    assert monitor_created.status_code == 201
    monitor_login = client.post(
        "/api/auth/login",
        json={"username": "monitor@example.test", "password": monitor_created.json()["bootstrap_password"]},
    )
    assert monitor_login.status_code == 200
    monitor_headers = {"Authorization": f"Bearer {monitor_login.json()['access_token']}"}
    assert client.post(
        "/api/recognition-jobs",
        headers=monitor_headers,
        json={
            "items": [
                {
                    "source_file_id": source_file_id,
                    "edc_subject_ref": "SUBJJOB",
                    "edc_event_ref": "WEEK_0",
                }
            ]
        },
    ).status_code == 403

    cancelled = client.post(f"/api/recognition-jobs/{job['id']}/cancel", headers=site_a_headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["items"][0]["status"] == "cancelled"

    retry = client.post(f"/api/recognition-jobs/{job['id']}/retry", headers=site_a_headers)
    assert retry.status_code == 409
    assert retry.json()["detail"] == "recognition_job_no_failed_items"

    runnable = client.post(
        "/api/recognition-jobs",
        headers=site_a_headers,
        json={
            "items": [
                {
                    "source_file_id": source_file_id,
                    "edc_subject_ref": "SUBJJOB",
                    "edc_event_ref": "WEEK_0",
                    "field_codes": ["ALT"],
                }
            ]
        },
    ).json()
    run = client.post(f"/api/recognition-jobs/{runnable['id']}/run", headers=site_a_headers)
    assert run.status_code == 200
    assert run.json()["status"] == "failed"
    assert run.json()["items"][0]["status"] == "failed"
    retried = client.post(f"/api/recognition-jobs/{runnable['id']}/retry", headers=site_a_headers)
    assert retried.status_code == 200
    assert retried.json()["status"] == "queued"


def test_recognition_job_rejects_duplicate_run_and_running_cancel(client: TestClient) -> None:
    headers = auth_headers(client, "site-a-investigator@example.test")
    source = client.post(
        "/api/source-files",
        headers=headers,
        json={
            "source_filename": "synthetic_running_job.png",
            "sha256": "c" * 64,
            "mime_type": "image/png",
            "storage_key": "synthetic/SITE_A/synthetic_running_job.png",
        },
    )
    assert source.status_code == 201
    created = client.post(
        "/api/recognition-jobs",
        headers=headers,
        json={
            "items": [
                {
                    "source_file_id": source.json()["id"],
                    "edc_subject_ref": "SUBJRUNNING",
                    "edc_event_ref": "WEEK_0",
                    "field_codes": ["ALT"],
                }
            ]
        },
    )
    assert created.status_code == 201
    job_id = created.json()["id"]

    with client.app.state.database.connect() as connection:
        connection.execute(
            "UPDATE recognition_jobs SET status = 'running' WHERE id = ?",
            (job_id,),
        )

    run = client.post(f"/api/recognition-jobs/{job_id}/run", headers=headers)
    assert run.status_code == 409
    assert run.json()["detail"] == "recognition_job_already_running"

    cancel = client.post(f"/api/recognition-jobs/{job_id}/cancel", headers=headers)
    assert cancel.status_code == 409
    assert cancel.json()["detail"] == "recognition_job_running"

def test_central_data_manager_can_view_and_update_an_effective_crf_header(client: TestClient) -> None:
    headers = auth_headers(client, "central-data-manager@example.test")

    listed = client.get("/api/admin/field-dictionary", headers=headers)

    assert listed.status_code == 200
    assert listed.json()["dictionary_id"] == (
        "iit-pss-rct-full-header-map+pulmonary-function-workbook-headers"
    )
    assert listed.json()["header_count"] == 239
    original = next(
        item
        for item in listed.json()["headers"]
        if item["event_ref"] == "WEEK_0" and item["field_code"] == "WBC"
    )
    assert original["source_header"] == "WBC"
    assert original["display_header"] == "WBC"
    assert original["editable"] is True
    assert original["revision"] == 0

    updated = client.put(
        "/api/admin/field-dictionary/WEEK_0/WBC",
        headers=headers,
        json={"display_header": "白细胞计数（管理员修订）"},
    )

    assert updated.status_code == 200
    assert updated.json()["field_code"] == "WBC"
    assert updated.json()["source_header"] == "WBC"
    assert updated.json()["display_header"] == "白细胞计数（管理员修订）"
    assert updated.json()["revision"] == 1
    assert updated.json()["updated_by"] == "central-data-manager@example.test"
    refreshed = client.get("/api/admin/field-dictionary", headers=headers).json()
    effective = next(
        item
        for item in refreshed["headers"]
        if item["event_ref"] == "WEEK_0" and item["field_code"] == "WBC"
    )
    assert effective["display_header"] == "白细胞计数（管理员修订）"
    assert effective["field_code"] == "WBC"


def test_site_investigator_cannot_view_or_modify_the_field_dictionary(client: TestClient) -> None:
    headers = auth_headers(client, "site-a-investigator@example.test")

    listed = client.get("/api/admin/field-dictionary", headers=headers)
    updated = client.put(
        "/api/admin/field-dictionary/WEEK_0/WBC",
        headers=headers,
        json={"display_header": "不应被保存"},
    )

    assert listed.status_code == 403
    assert updated.status_code == 403
    assert listed.json()["detail"] == "central_data_manager_required"
    assert updated.json()["detail"] == "central_data_manager_required"


def test_candidate_requires_human_confirmation_before_simulated_transfer(client: TestClient) -> None:
    entry_headers = auth_headers(client, "site-a-investigator@example.test")
    candidate = create_candidate(client, entry_headers)

    blocked_transfer = client.post(f"/api/candidates/{candidate['id']}/transfers", headers=entry_headers)
    assert blocked_transfer.status_code == 409
    assert blocked_transfer.json()["detail"] == "candidate_not_human_confirmed"

    reviewer_headers = auth_headers(client, "site-a-investigator@example.test")
    review_response = client.post(
        f"/api/candidates/{candidate['id']}/review",
        headers=reviewer_headers,
        json={"decision": "accept", "reason": "Synthetic report checked against source."},
    )
    assert review_response.status_code == 200
    assert review_response.json()["status"] == "human_confirmed"

    transfer_response = client.post(f"/api/candidates/{candidate['id']}/transfers", headers=entry_headers)
    assert transfer_response.status_code == 201
    assert transfer_response.json()["mode"] == "simulation"
    assert transfer_response.json()["status"] == "queued"
    assert transfer_response.json()["target"] == "not_configured"
    assert re.fullmatch(r"[a-f0-9]{64}", transfer_response.json()["package_sha256"])

    audit_response = client.get(f"/api/candidates/{candidate['id']}/audit", headers=reviewer_headers)
    assert audit_response.status_code == 200
    assert [event["event_type"] for event in audit_response.json()] == [
        "candidate_created",
        "candidate_quality_evaluated",
        "candidate_human_confirmed",
        "transfer_simulated",
    ]
    assert audit_response.json()[-1]["details"]["package_sha256"] == transfer_response.json()["package_sha256"]


@pytest.mark.parametrize(
    ("review_payload", "expected_status", "expected_final_value"),
    [
        ({"decision": "accept"}, "human_confirmed", "32"),
        ({"decision": "edit", "edited_value": "31", "reason": "   "}, "human_confirmed", "31"),
        ({"decision": "reject"}, "rejected", None),
    ],
)
def test_candidate_review_reason_is_optional_for_all_decisions(
    client: TestClient,
    review_payload: dict[str, str],
    expected_status: str,
    expected_final_value: str | None,
) -> None:
    headers = auth_headers(client, "site-a-investigator@example.test")
    candidate = create_candidate(client, headers)

    response = client.post(
        f"/api/candidates/{candidate['id']}/review",
        headers=headers,
        json=review_payload,
    )

    assert response.status_code == 200
    assert response.json()["status"] == expected_status
    assert response.json()["final_value"] == expected_final_value
    assert response.json()["review_reason"] is None
    audit_response = client.get(f"/api/candidates/{candidate['id']}/audit", headers=headers)
    assert audit_response.status_code == 200
    assert audit_response.json()[-1]["details"]["reason"] is None


def test_reviewer_can_accept_every_candidate_from_the_current_batch_in_one_request(
    client: TestClient,
) -> None:
    site_a_headers = auth_headers(client, "site-a-investigator@example.test")
    batch_candidates = [
        create_candidate(client, site_a_headers),
        create_candidate(client, site_a_headers),
    ]
    site_b_headers = auth_headers(client, "site-b-investigator@example.test")
    outside_batch = create_candidate(client, site_b_headers)

    response = client.post(
        "/api/candidate-reviews/bulk-accept",
        headers=site_a_headers,
        json={"candidate_ids": [candidate["id"] for candidate in batch_candidates]},
    )

    assert response.status_code == 200
    assert response.json()["accepted_count"] == 2
    assert response.json()["skipped_count"] == 0
    assert {candidate["status"] for candidate in response.json()["candidates"]} == {"human_confirmed"}
    refreshed = client.get("/api/candidates", headers=site_a_headers)
    assert refreshed.status_code == 200
    assert {
        candidate["status"]
        for candidate in refreshed.json()
        if candidate["id"] in {item["id"] for item in batch_candidates}
    } == {"human_confirmed"}
    for candidate in batch_candidates:
        audit_events = client.get(f"/api/candidates/{candidate['id']}/audit", headers=site_a_headers).json()
        assert audit_events[-1]["event_type"] == "candidate_human_confirmed"
        assert audit_events[-1]["details"]["mode"] == "bulk_accept"
    outside_detail = client.get(f"/api/candidates/{outside_batch['id']}", headers=site_b_headers)
    assert outside_detail.json()["status"] == "candidate"


@pytest.mark.parametrize("extraction_agreement", ["conflict", "kimi_only"])
def test_bulk_accept_routes_kimi_review_candidates_to_item_review(
    client: TestClient,
    extraction_agreement: str,
) -> None:
    headers = auth_headers(client, "site-a-investigator@example.test")
    candidate = create_candidate(client, headers)
    with client.app.state.database.connect() as connection:
        connection.execute(
            "UPDATE candidates SET extraction_agreement = ? WHERE id = ?",
            (extraction_agreement, candidate["id"]),
        )

    response = client.post(
        "/api/candidate-reviews/bulk-accept",
        headers=headers,
        json={"candidate_ids": [candidate["id"]]},
    )

    assert response.status_code == 200
    assert response.json()["accepted_count"] == 0
    assert response.json()["skipped_count"] == 1
    assert response.json()["skipped"][0]["reason"] == "item_review_required"
    detail = client.get(f"/api/candidates/{candidate['id']}", headers=headers)
    assert detail.json()["status"] == "candidate"


def test_conflict_review_requires_explicit_source_and_confirmed_evidence(client: TestClient) -> None:
    headers = auth_headers(client, "site-a-investigator@example.test")
    candidate = create_candidate(client, headers, proposed_value="32")
    mark_candidate_as_confirmed_risky(client, candidate, extraction_agreement="conflict")

    missing_source = client.post(
        f"/api/candidates/{candidate['id']}/review",
        headers=headers,
        json={"decision": "accept"},
    )
    missing_evidence = client.post(
        f"/api/candidates/{candidate['id']}/review",
        headers=headers,
        json={"decision": "accept", "selected_source": "local"},
    )
    evidence = client.get(f"/api/candidates/{candidate['id']}/evidence-image", headers=headers)
    accepted = client.post(
        f"/api/candidates/{candidate['id']}/review",
        headers=headers,
        json={
            "decision": "accept",
            "selected_source": "local",
            "evidence_acknowledged": True,
            "evidence_source_file_id": candidate["source_file_id"],
        },
    )

    assert missing_source.status_code == 422
    assert missing_source.json()["detail"] == "conflict_source_selection_required"
    assert missing_evidence.status_code == 422
    assert missing_evidence.json()["detail"] == "candidate_evidence_acknowledgement_required"
    assert evidence.status_code == 200
    assert evidence.headers["cache-control"] == "no-store"
    assert accepted.status_code == 200
    assert accepted.json()["final_value"] == "31"
    audit_events = client.get(f"/api/candidates/{candidate['id']}/audit", headers=headers).json()
    review_event = audit_events[-1]
    assert review_event["details"]["review_mode"] == "single"
    assert review_event["details"]["selected_source"] == "local"
    assert review_event["details"]["evidence_source_file_id"] == candidate["source_file_id"]
    assert len(review_event["event_hash"]) == 64


def test_central_bulk_override_requires_reason_evidence_and_records_summary(client: TestClient) -> None:
    site_headers = auth_headers(client, "site-a-investigator@example.test")
    candidate = create_candidate(client, site_headers, proposed_value="32")
    mark_candidate_as_confirmed_risky(client, candidate, extraction_agreement="conflict")

    forbidden = client.post(
        "/api/candidate-reviews/bulk-accept",
        headers=site_headers,
        json={
            "candidate_ids": [candidate["id"]],
            "override_sources": ["conflict"],
            "override_reason": "Site request must not bypass the central gate.",
            "conflict_value_source": "local",
            "evidence_acknowledged_candidate_ids": [candidate["id"]],
        },
    )
    central_headers = auth_headers(client, "central-data-manager@example.test")
    missing_reason = client.post(
        "/api/candidate-reviews/bulk-accept",
        headers=central_headers,
        json={
            "candidate_ids": [candidate["id"]],
            "override_sources": ["conflict"],
            "conflict_value_source": "local",
            "evidence_acknowledged_candidate_ids": [candidate["id"]],
        },
    )
    accepted = client.post(
        "/api/candidate-reviews/bulk-accept",
        headers=central_headers,
        json={
            "candidate_ids": [candidate["id"]],
            "review_batch_id": "review-batch-001",
            "override_sources": ["conflict"],
            "override_reason": "Central reviewer verified the deidentified evidence image.",
            "conflict_value_source": "local",
            "evidence_acknowledged_candidate_ids": [candidate["id"]],
        },
    )

    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "bulk_override_forbidden"
    assert missing_reason.status_code == 422
    assert missing_reason.json()["detail"] == "bulk_override_reason_required"
    assert accepted.status_code == 200
    assert accepted.json()["accepted_count"] == 1
    assert accepted.json()["candidates"][0]["final_value"] == "31"
    assert accepted.json()["summary"]["override"]["used"] is True
    audit = client.get(
        "/api/audit-events?review_mode=bulk&review_batch_id=review-batch-001",
        headers=central_headers,
    )
    assert audit.status_code == 200
    assert {event["event_type"] for event in audit.json()["events"]} == {
        "candidate_human_confirmed",
        "bulk_review_completed",
    }
    candidate_event = next(
        event for event in audit.json()["events"] if event["candidate_id"] == candidate["id"]
    )
    assert candidate_event["details"]["selected_source"] == "local"
    assert len(candidate_event["details"]["bulk_policy_summary_sha256"]) == 64
    assert len(candidate_event["event_hash"]) == 64


def test_audit_chain_anchor_is_central_only_and_tampering_blocks_new_anchor(client: TestClient) -> None:
    site_headers = auth_headers(client, "site-a-investigator@example.test")
    central_headers = auth_headers(client, "central-data-manager@example.test")

    forbidden = client.get("/api/audit-chain/anchor", headers=site_headers)
    anchor = client.get("/api/audit-chain/anchor", headers=central_headers)

    assert forbidden.status_code == 403
    assert anchor.status_code == 200
    assert anchor.json()["version"] == "audit-chain-v1"
    assert len(anchor.json()["head_hash"]) == 64

    with client.app.state.database.connect() as connection:
        connection.execute(
            "UPDATE audit_events SET details_json = ? WHERE rowid = 1",
            ('{"tampered":true}',),
        )

    verification = client.get("/api/audit-chain/verify", headers=central_headers)
    rejected_anchor = client.get("/api/audit-chain/anchor", headers=central_headers)
    assert verification.status_code == 200
    assert verification.json()["ok"] is False
    assert rejected_anchor.status_code == 409
    assert rejected_anchor.json()["detail"] == "audit_chain_verification_failed"


def test_transfer_creation_replays_the_same_record_for_the_same_idempotency_key(client: TestClient) -> None:
    entry_headers = auth_headers(client, "site-a-investigator@example.test")
    candidate = create_candidate(client, entry_headers)
    reviewer_headers = auth_headers(client, "site-a-investigator@example.test")
    review_response = client.post(
        f"/api/candidates/{candidate['id']}/review",
        headers=reviewer_headers,
        json={"decision": "accept", "reason": "Synthetic source checked."},
    )
    assert review_response.status_code == 200

    idempotent_headers = {**entry_headers, "Idempotency-Key": "synthetic-transfer-attempt-001"}
    first_response = client.post(
        f"/api/candidates/{candidate['id']}/transfers",
        headers=idempotent_headers,
    )
    replay_response = client.post(
        f"/api/candidates/{candidate['id']}/transfers",
        headers=idempotent_headers,
    )

    assert first_response.status_code == 201
    assert first_response.json()["replayed"] is False
    assert replay_response.status_code == 200
    assert replay_response.json() == {**first_response.json(), "replayed": True}
    assert replay_response.json()["idempotency_key"] == "synthetic-transfer-attempt-001"

    audit_response = client.get(f"/api/candidates/{candidate['id']}/audit", headers=reviewer_headers)
    assert audit_response.status_code == 200
    assert [event["event_type"] for event in audit_response.json()] == [
        "candidate_created",
        "candidate_quality_evaluated",
        "candidate_human_confirmed",
        "transfer_simulated",
        "transfer_request_replayed",
    ]
    assert audit_response.json()[-1]["details"] == {
        "idempotency_key": "synthetic-transfer-attempt-001",
        "transfer_id": first_response.json()["id"],
    }


def test_transfer_creation_rejects_an_idempotency_key_reused_for_another_candidate(client: TestClient) -> None:
    entry_headers = auth_headers(client, "site-a-investigator@example.test")
    reviewer_headers = auth_headers(client, "site-a-investigator@example.test")
    first_candidate = create_candidate(client, entry_headers)
    second_candidate = create_candidate(client, entry_headers)
    for candidate in (first_candidate, second_candidate):
        review_response = client.post(
            f"/api/candidates/{candidate['id']}/review",
            headers=reviewer_headers,
            json={"decision": "accept", "reason": "Synthetic source checked."},
        )
        assert review_response.status_code == 200

    idempotent_headers = {**entry_headers, "Idempotency-Key": "synthetic-transfer-attempt-002"}
    first_response = client.post(
        f"/api/candidates/{first_candidate['id']}/transfers",
        headers=idempotent_headers,
    )
    conflicting_response = client.post(
        f"/api/candidates/{second_candidate['id']}/transfers",
        headers=idempotent_headers,
    )

    assert first_response.status_code == 201
    assert conflicting_response.status_code == 409
    assert conflicting_response.json()["detail"] == "idempotency_key_conflict"

    audit_response = client.get(f"/api/candidates/{second_candidate['id']}/audit", headers=reviewer_headers)
    assert audit_response.status_code == 200
    assert [event["event_type"] for event in audit_response.json()] == [
        "candidate_created",
        "candidate_quality_evaluated",
        "candidate_human_confirmed",
    ]


def test_transfer_creation_rejects_an_invalid_idempotency_key(client: TestClient) -> None:
    entry_headers = auth_headers(client, "site-a-investigator@example.test")
    candidate = create_candidate(client, entry_headers)
    reviewer_headers = auth_headers(client, "site-a-investigator@example.test")
    review_response = client.post(
        f"/api/candidates/{candidate['id']}/review",
        headers=reviewer_headers,
        json={"decision": "accept", "reason": "Synthetic source checked."},
    )
    assert review_response.status_code == 200

    response = client.post(
        f"/api/candidates/{candidate['id']}/transfers",
        headers={**entry_headers, "Idempotency-Key": "contains spaces"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_idempotency_key"


def test_simulated_transfer_exposes_the_frozen_canonical_package(client: TestClient) -> None:
    entry_headers = auth_headers(client, "site-a-investigator@example.test")
    candidate = create_candidate(client, entry_headers)
    reviewer_headers = auth_headers(client, "site-a-investigator@example.test")
    review_response = client.post(
        f"/api/candidates/{candidate['id']}/review",
        headers=reviewer_headers,
        json={"decision": "edit", "edited_value": "31", "reason": "Synthetic source checked."},
    )
    assert review_response.status_code == 200
    reviewed = review_response.json()

    transfer_response = client.post(f"/api/candidates/{candidate['id']}/transfers", headers=entry_headers)
    assert transfer_response.status_code == 201
    transfer = transfer_response.json()

    package_response = client.get(f"/api/transfers/{transfer['id']}/package", headers=entry_headers)
    assert package_response.status_code == 200
    exported = package_response.json()
    expected_package = {
        "protocol": "clinical-edc-companion-transfer-v1",
        "candidate": {
            "id": candidate["id"],
            "centre_code": "SITE_A",
            "source_sha256": "a" * 64,
        },
        "edc_record": {
            "subject_ref": "SUBJ001",
            "event_ref": "WEEK_0",
            "field_code": "ALT",
        },
        "value": {"final_value": "31", "unit": "U/L"},
        "review": {
            "reviewed_by": "site-a-investigator@example.test",
            "reviewed_at": reviewed["reviewed_at"],
        },
    }
    expected_sha256 = hashlib.sha256(
        json.dumps(expected_package, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert exported == {
        "transfer_id": transfer["id"],
        "candidate_id": candidate["id"],
        "package_sha256": expected_sha256,
        "package": expected_package,
    }
    assert transfer["package_sha256"] == expected_sha256

    centre_b_headers = auth_headers(client, "site-b-investigator@example.test")
    assert client.get(f"/api/transfers/{transfer['id']}/package", headers=centre_b_headers).status_code == 404
    assert client.get(f"/api/transfers/{transfer['id']}/integrity", headers=centre_b_headers).status_code == 404
    assert client.post(f"/api/transfers/{transfer['id']}/submit", headers=centre_b_headers).status_code == 404


def test_transfer_integrity_endpoint_recomputes_the_frozen_package_hash(client: TestClient) -> None:
    entry_headers = auth_headers(client, "site-a-investigator@example.test")
    candidate = create_candidate(client, entry_headers)
    reviewer_headers = auth_headers(client, "site-a-investigator@example.test")
    review_response = client.post(
        f"/api/candidates/{candidate['id']}/review",
        headers=reviewer_headers,
        json={"decision": "accept", "reason": "Synthetic source checked."},
    )
    assert review_response.status_code == 200
    transfer_response = client.post(f"/api/candidates/{candidate['id']}/transfers", headers=entry_headers)
    assert transfer_response.status_code == 201
    transfer = transfer_response.json()

    integrity_response = client.get(f"/api/transfers/{transfer['id']}/integrity", headers=entry_headers)
    assert integrity_response.status_code == 200
    assert integrity_response.json() == {
        "transfer_id": transfer["id"],
        "integrity_valid": True,
        "recorded_sha256": transfer["package_sha256"],
        "recomputed_sha256": transfer["package_sha256"],
    }


def test_simulated_transfer_receipt_is_downloadable_and_hash_verifiable(client: TestClient) -> None:
    entry_headers = auth_headers(client, "site-a-investigator@example.test")
    candidate = create_candidate(client, entry_headers)
    reviewer_headers = auth_headers(client, "site-a-investigator@example.test")
    review_response = client.post(
        f"/api/candidates/{candidate['id']}/review",
        headers=reviewer_headers,
        json={"decision": "accept", "reason": "Synthetic source checked."},
    )
    assert review_response.status_code == 200
    idempotent_headers = {**entry_headers, "Idempotency-Key": "synthetic-transfer-attempt-003"}
    transfer_response = client.post(
        f"/api/candidates/{candidate['id']}/transfers",
        headers=idempotent_headers,
    )
    assert transfer_response.status_code == 201
    transfer = transfer_response.json()

    receipt_response = client.get(f"/api/transfers/{transfer['id']}/receipt", headers=entry_headers)

    assert receipt_response.status_code == 200
    assert receipt_response.headers["content-type"] == "application/json"
    assert receipt_response.headers["content-disposition"] == (
        f'attachment; filename="transfer-{transfer["id"]}-receipt.json"'
    )
    expected_receipt = {
        "protocol": "clinical-edc-companion-receipt-v1",
        "transfer": {
            "id": transfer["id"],
            "candidate_id": candidate["id"],
            "mode": "simulation",
            "status": "queued",
            "target": "not_configured",
            "package_sha256": transfer["package_sha256"],
        },
        "request": {
            "idempotency_key": "synthetic-transfer-attempt-003",
            "created_by": "site-a-investigator@example.test",
            "created_at": transfer["created_at"],
        },
    }
    expected_receipt_sha256 = hashlib.sha256(
        json.dumps(expected_receipt, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert receipt_response.json() == {
        "receipt_sha256": expected_receipt_sha256,
        "receipt": expected_receipt,
    }


def test_transfer_reconciliation_ledger_is_centre_scoped(client: TestClient) -> None:
    entry_headers = auth_headers(client, "site-a-investigator@example.test")
    candidate = create_candidate(client, entry_headers)
    reviewer_headers = auth_headers(client, "site-a-investigator@example.test")
    review_response = client.post(
        f"/api/candidates/{candidate['id']}/review",
        headers=reviewer_headers,
        json={"decision": "accept", "reason": "Synthetic source checked."},
    )
    assert review_response.status_code == 200
    transfer_response = client.post(f"/api/candidates/{candidate['id']}/transfers", headers=entry_headers)
    assert transfer_response.status_code == 201
    transfer = transfer_response.json()

    centre_a_response = client.get("/api/transfers", headers=entry_headers)
    centre_b_response = client.get("/api/transfers", headers=auth_headers(client, "site-b-investigator@example.test"))
    central_response = client.get("/api/transfers", headers=auth_headers(client, "central-data-manager@example.test"))

    assert centre_a_response.status_code == 200
    assert centre_a_response.json() == [
        {
            "id": transfer["id"],
            "candidate_id": candidate["id"],
            "centre_code": "SITE_A",
            "mode": "simulation",
            "status": "queued",
            "target": "not_configured",
            "package_sha256": transfer["package_sha256"],
            "idempotency_key": transfer["idempotency_key"],
            "attempt_count": 0,
            "retry_count": 0,
            "last_error": None,
            "reconciliation": None,
            "external_reference": None,
            "authority_response_sha256": None,
            "submitted_at": None,
            "readback_status": "not_checked",
            "readback_checked_at": None,
            "readback_attempt_count": 0,
            "created_by": "site-a-investigator@example.test",
            "created_at": transfer["created_at"],
            "updated_at": transfer["created_at"],
        }
    ]
    assert centre_b_response.status_code == 200
    assert centre_b_response.json() == []
    assert central_response.status_code == 200
    assert central_response.json() == centre_a_response.json()


def test_blocked_submission_persists_a_structured_failure_without_rewriting_the_receipt(
    client: TestClient,
) -> None:
    entry_headers = auth_headers(client, "site-a-investigator@example.test")
    candidate = create_candidate(client, entry_headers)
    reviewer_headers = auth_headers(client, "site-a-investigator@example.test")
    review_response = client.post(
        f"/api/candidates/{candidate['id']}/review",
        headers=reviewer_headers,
        json={"decision": "accept", "reason": "Synthetic source checked."},
    )
    assert review_response.status_code == 200
    transfer_response = client.post(f"/api/candidates/{candidate['id']}/transfers", headers=entry_headers)
    assert transfer_response.status_code == 201
    transfer = transfer_response.json()
    original_receipt = client.get(f"/api/transfers/{transfer['id']}/receipt", headers=entry_headers)
    assert original_receipt.status_code == 200

    submit_response = client.post(f"/api/transfers/{transfer['id']}/submit", headers=entry_headers)

    assert submit_response.status_code == 409
    assert submit_response.json()["detail"] == "edc_adapter_disabled"
    ledger_response = client.get("/api/transfers", headers=entry_headers)
    assert ledger_response.status_code == 200
    failed = ledger_response.json()[0]
    assert failed["status"] == "failed"
    assert failed["attempt_count"] == 1
    assert failed["retry_count"] == 0
    assert failed["last_error"] == {
        "code": "edc_adapter_disabled",
        "message": "Authority EDC adapter is disabled; no submission occurred.",
    }
    assert failed["reconciliation"] is None
    frozen_receipt = client.get(f"/api/transfers/{transfer['id']}/receipt", headers=entry_headers)
    assert frozen_receipt.status_code == 200
    assert frozen_receipt.json() == original_receipt.json()


def test_failed_transfer_can_be_explicitly_requeued_with_a_cumulative_retry_count(client: TestClient) -> None:
    entry_headers = auth_headers(client, "site-a-investigator@example.test")
    candidate = create_candidate(client, entry_headers)
    reviewer_headers = auth_headers(client, "site-a-investigator@example.test")
    review_response = client.post(
        f"/api/candidates/{candidate['id']}/review",
        headers=reviewer_headers,
        json={"decision": "accept", "reason": "Synthetic source checked."},
    )
    assert review_response.status_code == 200
    transfer_response = client.post(f"/api/candidates/{candidate['id']}/transfers", headers=entry_headers)
    assert transfer_response.status_code == 201
    transfer = transfer_response.json()

    premature_retry = client.post(f"/api/transfers/{transfer['id']}/retry", headers=entry_headers)
    assert premature_retry.status_code == 409
    assert premature_retry.json()["detail"] == "transfer_not_failed"
    assert client.post(f"/api/transfers/{transfer['id']}/submit", headers=entry_headers).status_code == 409

    retry_response = client.post(f"/api/transfers/{transfer['id']}/retry", headers=entry_headers)

    assert retry_response.status_code == 200
    retried = retry_response.json()
    assert retried["id"] == transfer["id"]
    assert retried["status"] == "queued"
    assert retried["attempt_count"] == 1
    assert retried["retry_count"] == 1
    assert retried["last_error"]["code"] == "edc_adapter_disabled"
    repeated_retry = client.post(f"/api/transfers/{transfer['id']}/retry", headers=entry_headers)
    assert repeated_retry.status_code == 409
    assert repeated_retry.json()["detail"] == "transfer_not_failed"

    audit_response = client.get(f"/api/candidates/{candidate['id']}/audit", headers=reviewer_headers)
    assert audit_response.status_code == 200
    assert audit_response.json()[-1]["event_type"] == "transfer_retry_queued"
    assert audit_response.json()[-1]["details"] == {
        "retry_count": 1,
        "transfer_id": transfer["id"],
    }


def test_central_manager_can_reconcile_a_failed_site_transfer(client: TestClient) -> None:
    site_headers = auth_headers(client, "site-a-investigator@example.test")
    candidate = create_candidate(client, site_headers)
    review_response = client.post(
        f"/api/candidates/{candidate['id']}/review",
        headers=site_headers,
        json={"decision": "accept", "reason": "Synthetic source checked."},
    )
    assert review_response.status_code == 200
    transfer_response = client.post(f"/api/candidates/{candidate['id']}/transfers", headers=site_headers)
    assert transfer_response.status_code == 201
    transfer = transfer_response.json()
    assert client.post(f"/api/transfers/{transfer['id']}/submit", headers=site_headers).status_code == 409
    reconciliation_payload = {"note": "Synthetic discrepancy reviewed; no Authority EDC entry exists."}
    central_headers = auth_headers(client, "central-data-manager@example.test")

    reviewer_response = client.post(
        f"/api/transfers/{transfer['id']}/reconcile",
        headers=central_headers,
        json=reconciliation_payload,
    )

    assert reviewer_response.status_code == 200
    reconciled = reviewer_response.json()
    assert reconciled["status"] == "reconciled"
    assert reconciled["attempt_count"] == 1
    assert reconciled["last_error"]["code"] == "edc_adapter_disabled"
    assert reconciled["reconciliation"] == {
        "reconciled_by": "central-data-manager@example.test",
        "reconciled_at": reconciled["reconciliation"]["reconciled_at"],
        "note": reconciliation_payload["note"],
    }
    repeated_response = client.post(
        f"/api/transfers/{transfer['id']}/reconcile",
        headers=central_headers,
        json=reconciliation_payload,
    )
    assert repeated_response.status_code == 409
    assert repeated_response.json()["detail"] == "transfer_not_failed"

    audit_response = client.get(f"/api/candidates/{candidate['id']}/audit", headers=central_headers)
    assert audit_response.status_code == 200
    assert audit_response.json()[-1]["event_type"] == "transfer_reconciled"
    assert audit_response.json()[-1]["details"] == {
        "note": reconciliation_payload["note"],
        "transfer_id": transfer["id"],
    }


def test_submit_only_accepts_a_queued_transfer_and_never_overwrites_reconciliation(client: TestClient) -> None:
    entry_headers = auth_headers(client, "site-a-investigator@example.test")
    candidate = create_candidate(client, entry_headers)
    reviewer_headers = auth_headers(client, "site-a-investigator@example.test")
    review_response = client.post(
        f"/api/candidates/{candidate['id']}/review",
        headers=reviewer_headers,
        json={"decision": "accept", "reason": "Synthetic source checked."},
    )
    assert review_response.status_code == 200
    transfer_response = client.post(f"/api/candidates/{candidate['id']}/transfers", headers=entry_headers)
    assert transfer_response.status_code == 201
    transfer = transfer_response.json()
    assert client.post(f"/api/transfers/{transfer['id']}/submit", headers=entry_headers).status_code == 409

    repeated_failed_submit = client.post(f"/api/transfers/{transfer['id']}/submit", headers=entry_headers)
    assert repeated_failed_submit.status_code == 409
    assert repeated_failed_submit.json()["detail"] == "transfer_not_queued"
    failed = client.get("/api/transfers", headers=entry_headers).json()[0]
    assert failed["status"] == "failed"
    assert failed["attempt_count"] == 1

    reconcile_response = client.post(
        f"/api/transfers/{transfer['id']}/reconcile",
        headers=reviewer_headers,
        json={"note": "Synthetic discrepancy reviewed; no Authority EDC entry exists."},
    )
    assert reconcile_response.status_code == 200
    repeated_reconciled_submit = client.post(f"/api/transfers/{transfer['id']}/submit", headers=entry_headers)
    assert repeated_reconciled_submit.status_code == 409
    assert repeated_reconciled_submit.json()["detail"] == "transfer_not_queued"
    reconciled = client.get("/api/transfers", headers=entry_headers).json()[0]
    assert reconciled["status"] == "reconciled"
    assert reconciled["attempt_count"] == 1
    assert reconciled["reconciliation"] == reconcile_response.json()["reconciliation"]


def test_transfer_submission_is_blocked_and_audited_while_adapter_is_disabled(client: TestClient) -> None:
    entry_headers = auth_headers(client, "site-a-investigator@example.test")
    candidate = create_candidate(client, entry_headers)
    reviewer_headers = auth_headers(client, "site-a-investigator@example.test")
    review_response = client.post(
        f"/api/candidates/{candidate['id']}/review",
        headers=reviewer_headers,
        json={"decision": "accept", "reason": "Synthetic source checked."},
    )
    assert review_response.status_code == 200
    transfer_response = client.post(f"/api/candidates/{candidate['id']}/transfers", headers=entry_headers)
    assert transfer_response.status_code == 201
    transfer = transfer_response.json()

    submit_response = client.post(f"/api/transfers/{transfer['id']}/submit", headers=entry_headers)
    assert submit_response.status_code == 409
    assert submit_response.json()["detail"] == "edc_adapter_disabled"

    audit_response = client.get(f"/api/candidates/{candidate['id']}/audit", headers=reviewer_headers)
    assert audit_response.status_code == 200
    blocked_event = audit_response.json()[-1]
    assert blocked_event["event_type"] == "transfer_submission_blocked"
    assert blocked_event["actor_username"] == "site-a-investigator@example.test"
    assert blocked_event["details"] == {
        "transfer_id": transfer["id"],
        "reason": "edc_adapter_disabled",
        "target": "not_configured",
    }


def test_edc_adapter_readiness_is_explicitly_fail_closed(client: TestClient) -> None:
    response = client.get("/api/edc-adapter/readiness")

    assert response.status_code == 200
    readiness = response.json()
    assert readiness["authority_edc"] == "LibreClinica"
    assert readiness["mode"] == "simulation_only"
    assert readiness["write_path"] == "disabled"
    assert readiness["status"] == "blocked"
    assert "direct database write is prohibited" in readiness["blockers"]


def test_configured_adapter_submits_only_the_frozen_human_confirmed_package(tmp_path: Path) -> None:
    class RecordingAdapter:
        mode = "libreclinica_soap"
        target_kind = "libreclinica"

        def __init__(self) -> None:
            self.calls: list[tuple[dict, str]] = []

        def readiness(self) -> dict[str, object]:
            return {
                "authority_edc": "LibreClinica",
                "mode": self.mode,
                "write_path": "human_triggered",
                "status": "ready",
                "blockers": [],
            }

        def submit(self, transfer_package: dict, *, idempotency_key: str) -> EdcSubmissionResult:
            self.calls.append((transfer_package, idempotency_key))
            return EdcSubmissionResult(
                external_reference="S_TEST/SS_TEST/SE_TEST:1/F_TEST/I_TEST",
                response_sha256="d" * 64,
            )

    adapter = RecordingAdapter()
    app = create_app(
        database_path=tmp_path / "companion-live.db",
        environment="test",
        edc_adapter=adapter,
    )
    with TestClient(app) as live_client:
        headers = auth_headers(live_client, "site-a-investigator@example.test")
        candidate = create_candidate(live_client, headers)
        assert live_client.post(
            f"/api/candidates/{candidate['id']}/review",
            headers=headers,
            json={"decision": "accept", "reason": "Synthetic source checked."},
        ).status_code == 200
        created = live_client.post(
            f"/api/candidates/{candidate['id']}/transfers",
            headers=headers,
        )
        assert created.status_code == 201
        transfer = created.json()
        original_receipt = live_client.get(
            f"/api/transfers/{transfer['id']}/receipt",
            headers=headers,
        ).json()

        submitted_response = live_client.post(
            f"/api/transfers/{transfer['id']}/submit",
            headers=headers,
        )

        assert submitted_response.status_code == 200
        submitted = submitted_response.json()
        assert transfer["mode"] == "libreclinica_soap"
        assert transfer["target"] == "libreclinica"
        assert submitted["status"] == "submitted"
        assert submitted["attempt_count"] == 1
        assert submitted["external_reference"] == "S_TEST/SS_TEST/SE_TEST:1/F_TEST/I_TEST"
        assert submitted["authority_response_sha256"] == "d" * 64
        assert submitted["submitted_at"]
        assert len(adapter.calls) == 1
        assert adapter.calls[0][0]["value"]["final_value"] == "32"
        assert live_client.get(
            f"/api/transfers/{transfer['id']}/receipt",
            headers=headers,
        ).json() == original_receipt
        audit_events = live_client.get(
            f"/api/candidates/{candidate['id']}/audit",
            headers=headers,
        ).json()
        assert audit_events[-3]["event_type"] == "transfer_created"
        assert audit_events[-2]["event_type"] == "transfer_submitted"
        assert audit_events[-1]["event_type"] == "authority_readback_unsupported"


def test_one_click_excel_export_contains_only_submitted_records_in_the_users_scope(
    tmp_path: Path,
) -> None:
    class ImmediateAdapter:
        mode = "libreclinica_soap"
        target_kind = "libreclinica"

        def readiness(self) -> dict[str, object]:
            return {
                "authority_edc": "LibreClinica",
                "mode": self.mode,
                "write_path": "human_triggered",
                "status": "ready",
                "blockers": [],
            }

        def submit(self, _transfer_package: dict, *, idempotency_key: str) -> EdcSubmissionResult:
            return EdcSubmissionResult(
                external_reference=f"S_TEST/{idempotency_key[-12:]}",
                response_sha256="e" * 64,
            )

    class RecordingSpreadsheetExporter:
        ready = True

        def __init__(self) -> None:
            self.payloads: list[dict[str, object]] = []

        def export(self, payload: dict[str, object]) -> bytes:
            self.payloads.append(payload)
            return b"synthetic-xlsx"

    exporter = RecordingSpreadsheetExporter()
    app = create_app(
        database_path=tmp_path / "export.db",
        environment="test",
        edc_adapter=ImmediateAdapter(),
        spreadsheet_exporter=exporter,
    )
    with TestClient(app) as local_client:
        for username in (
            "site-a-investigator@example.test",
            "site-b-investigator@example.test",
        ):
            headers = auth_headers(local_client, username)
            candidate = create_candidate(local_client, headers)
            assert local_client.post(
                f"/api/candidates/{candidate['id']}/review",
                headers=headers,
                json={"decision": "accept"},
            ).status_code == 200
            transfer = local_client.post(
                f"/api/candidates/{candidate['id']}/transfers",
                headers=headers,
            ).json()
            assert local_client.post(
                f"/api/transfers/{transfer['id']}/submit",
                headers=headers,
            ).status_code == 200

        site_a_headers = auth_headers(local_client, "site-a-investigator@example.test")
        site_export = local_client.get("/api/exports/submitted-data.xlsx", headers=site_a_headers)

        assert site_export.status_code == 200
        assert site_export.content == b"synthetic-xlsx"
        assert site_export.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert site_export.headers["content-disposition"].endswith('.xlsx"')
        site_payload = exporter.payloads[-1]
        assert site_payload["scope"] == "SITE_A"
        assert [row["centre_code"] for row in site_payload["events"]["WEEK_0"]["rows"]] == ["SITE_A"]

        central_headers = auth_headers(local_client, "central-data-manager@example.test")
        central_export = local_client.get("/api/exports/submitted-data.xlsx", headers=central_headers)

        assert central_export.status_code == 200
        central_payload = exporter.payloads[-1]
        assert central_payload["scope"] == "ALL_CENTRES"
        assert {
            row["centre_code"]
            for row in central_payload["events"]["WEEK_0"]["rows"]
        } == {"SITE_A", "SITE_B"}

        reviewed_export = local_client.get(
            "/api/exports/reviewed-recognition-data.xlsx",
            headers=site_a_headers,
        )
        assert reviewed_export.status_code == 200
        reviewed_payload = exporter.payloads[-1]
        assert reviewed_payload["events"]["WEEK_0"]["rows"][0]["authority_status"] == "all_submitted"


def test_reviewed_recognition_export_contains_only_actual_confirmed_fields(
    tmp_path: Path,
) -> None:
    class RecordingSpreadsheetExporter:
        ready = True

        def __init__(self) -> None:
            self.payloads: list[dict[str, object]] = []

        def export(self, payload: dict[str, object]) -> bytes:
            self.payloads.append(payload)
            return b"synthetic-xlsx"

    exporter = RecordingSpreadsheetExporter()
    app = create_app(
        database_path=tmp_path / "reviewed-export.db",
        environment="test",
        spreadsheet_exporter=exporter,
    )
    with TestClient(app) as local_client:
        headers = auth_headers(local_client, "site-a-investigator@example.test")
        candidates = [
            create_candidate(local_client, headers, field_code="ALT", proposed_value="32"),
            create_candidate(local_client, headers, field_code="PFT_FVC", proposed_value="3.20"),
        ]
        for candidate in candidates:
            assert local_client.post(
                f"/api/candidates/{candidate['id']}/review",
                headers=headers,
                json={"decision": "accept"},
            ).status_code == 200

        site_b_headers = auth_headers(local_client, "site-b-investigator@example.test")
        site_b_candidate = create_candidate(
            local_client,
            site_b_headers,
            field_code="AST",
            proposed_value="24",
        )
        assert local_client.post(
            f"/api/candidates/{site_b_candidate['id']}/review",
            headers=site_b_headers,
            json={"decision": "accept"},
        ).status_code == 200

        exported = local_client.get(
            "/api/exports/reviewed-recognition-data.xlsx",
            headers=headers,
        )
        site_payload = exporter.payloads[-1]
        central_exported = local_client.get(
            "/api/exports/reviewed-recognition-data.xlsx",
            headers=auth_headers(local_client, "central-data-manager@example.test"),
        )
        central_payload = exporter.payloads[-1]

    assert exported.status_code == 200
    assert exported.content == b"synthetic-xlsx"
    payload = site_payload
    assert payload["export_kind"] == "reviewed_recognition"
    assert payload["reviewed_value_count"] == 2
    assert list(payload["events"]) == ["WEEK_0"]
    assert {
        column["field_code"]
        for column in payload["events"]["WEEK_0"]["columns"]
    } == {"ALT", "PFT_FVC"}
    assert payload["events"]["WEEK_0"]["rows"][0]["authority_status"] == "not_submitted"
    assert {
        item["field_code"] for item in payload["field_mapping"]
    } == {"ALT", "PFT_FVC"}
    assert central_exported.status_code == 200
    assert central_payload["scope"] == "ALL_CENTRES"
    assert central_payload["reviewed_value_count"] == 3
    assert {
        row["centre_code"] for row in central_payload["events"]["WEEK_0"]["rows"]
    } == {"SITE_A", "SITE_B"}


def test_historical_simulation_transfer_cannot_drift_into_live_adapter(tmp_path: Path) -> None:
    database_path = tmp_path / "adapter-drift.db"
    simulation_app = create_app(database_path=database_path, environment="test")
    with TestClient(simulation_app) as simulation_client:
        headers = auth_headers(simulation_client, "site-a-investigator@example.test")
        candidate = create_candidate(simulation_client, headers)
        assert simulation_client.post(
            f"/api/candidates/{candidate['id']}/review",
            headers=headers,
            json={"decision": "accept", "reason": "Synthetic source checked."},
        ).status_code == 200
        old_transfer_response = simulation_client.post(
            f"/api/candidates/{candidate['id']}/transfers",
            headers=headers,
        )
        assert old_transfer_response.status_code == 201
        old_transfer = old_transfer_response.json()
        assert old_transfer["target"] == "not_configured"

    class RecordingAdapter:
        mode = "libreclinica_soap"
        target_kind = "libreclinica"

        def __init__(self) -> None:
            self.calls: list[tuple[dict, str]] = []

        def readiness(self) -> dict[str, object]:
            return {
                "authority_edc": "LibreClinica",
                "mode": self.mode,
                "write_path": "human_triggered",
                "status": "ready",
                "blockers": [],
            }

        def submit(self, transfer_package: dict, *, idempotency_key: str) -> EdcSubmissionResult:
            self.calls.append((transfer_package, idempotency_key))
            return EdcSubmissionResult(
                external_reference="must-not-be-used",
                response_sha256="e" * 64,
            )

    adapter = RecordingAdapter()
    live_app = create_app(
        database_path=database_path,
        environment="test",
        edc_adapter=adapter,
    )
    with TestClient(live_app) as live_client:
        headers = auth_headers(live_client, "site-a-investigator@example.test")
        blocked_response = live_client.post(
            f"/api/transfers/{old_transfer['id']}/submit",
            headers=headers,
        )
        assert blocked_response.status_code == 409
        assert blocked_response.json()["detail"] == "transfer_adapter_mismatch"
        assert adapter.calls == []

        ledger = live_client.get("/api/transfers", headers=headers).json()
        unchanged_old_transfer = next(row for row in ledger if row["id"] == old_transfer["id"])
        assert unchanged_old_transfer["status"] == "queued"
        assert unchanged_old_transfer["attempt_count"] == 0

        new_transfer_response = live_client.post(
            f"/api/candidates/{candidate['id']}/transfers",
            headers=headers,
        )
        assert new_transfer_response.status_code == 201
        new_transfer = new_transfer_response.json()
        assert new_transfer["id"] != old_transfer["id"]
        assert new_transfer["target"] == "libreclinica"
        assert new_transfer["mode"] == "libreclinica_soap"


def test_health_reports_the_versioned_synthetic_crf_mapping(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    health = response.json()
    assert health["crf_mapping_id"] == (
        "iit-pss-rct-full-header-map+pulmonary-function-workbook-headers"
    )
    assert health["crf_mapping_version"] == (
        "v0.2-synthetic-sandbox+v1.0-2026-08-11"
    )


def test_health_reports_redacted_runtime_profile_and_database_backend(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    health = response.json()
    assert health["application_version"] == "0.2.1"
    assert health["deployment_profile"] == "local"
    assert health["database_backend"] == "sqlite"
    assert health["database_schema_version"] == 1
    assert "database_path" not in health
    assert "database_url" not in health


def test_central_profile_fails_closed_instead_of_falling_back_to_sqlite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMPANION_DEPLOYMENT_PROFILE", "central")

    with pytest.raises(RuntimeConfigurationError, match="postgresql"):
        create_app(database_path=tmp_path / "central.db", environment="test")


def test_lite_health_reports_local_only_product_mode(tmp_path: Path) -> None:
    lite_app = create_app(
        database_path=tmp_path / "lite-health.db",
        environment="test",
        product_mode="lite",
    )

    with TestClient(lite_app) as lite_client:
        health = lite_client.get("/api/health")

    assert health.status_code == 200
    assert health.json()["product_mode"] == "lite"
    assert health.json()["edc_adapter"] == "fail_closed_simulation_only"
    assert health.json()["excel_export"] == "ready"


def test_candidate_exposes_required_provenance_after_review(client: TestClient) -> None:
    entry_headers = auth_headers(client, "site-a-investigator@example.test")
    candidate = create_candidate(client, entry_headers)

    reviewer_headers = auth_headers(client, "site-a-investigator@example.test")
    review_response = client.post(
        f"/api/candidates/{candidate['id']}/review",
        headers=reviewer_headers,
        json={
            "decision": "edit",
            "edited_value": "31",
            "reason": "Synthetic source value is 31 U/L.",
        },
    )
    assert review_response.status_code == 200
    assert review_response.json()["status"] == "human_confirmed"
    assert review_response.json()["final_value"] == "31"

    detail_response = client.get(f"/api/candidates/{candidate['id']}", headers=reviewer_headers)
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["status"] == "human_confirmed"
    assert detail["source_sha256"] == "a" * 64
    assert detail["ocr_engine_version"] == "demo-ocr-0.1"
    assert detail["kimi_model"] == "kimi-k3"
    assert detail["schema_version"] == "lab-candidate-v1"
    assert detail["reviewed_by"] == "site-a-investigator@example.test"


def test_synthetic_image_upload_records_a_hash_and_requires_attestation(client: TestClient) -> None:
    entry_headers = auth_headers(client, "site-a-investigator@example.test")
    content = SYNTHETIC_PNG_BYTES
    rejected = client.post(
        "/api/source-files/upload",
        headers=entry_headers,
        files={"file": ("synthetic.png", content, "image/png")},
        data={"synthetic_attestation": "false"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "synthetic_attestation_required"

    response = client.post(
        "/api/source-files/upload",
        headers=entry_headers,
        files={"file": ("synthetic.png", content, "image/png")},
        data={"synthetic_attestation": "true"},
    )
    assert response.status_code == 201
    source_file = response.json()
    assert source_file["centre_code"] == "SITE_A"
    assert source_file["sha256"] == hashlib.sha256(content).hexdigest()


def test_local_candidate_upload_does_not_require_edc_subject_provisioning(client: TestClient) -> None:
    headers = auth_headers(client, "site-a-investigator@example.test")

    response = client.post(
        "/api/source-files/upload",
        headers=headers,
        files={"file": ("synthetic.pdf", b"%PDF-1.7\n%%EOF", "application/pdf")},
        data={
            "synthetic_attestation": "true",
            "edc_subject_ref": "SUBJ_LOCAL_001",
            "edc_event_ref": "WEEK_0",
        },
    )

    assert response.status_code == 201
    assert response.json()["edc_subject_provisioning"] is None


def test_dragged_pdf_with_generic_browser_mime_is_detected_by_filename_and_magic(
    client: TestClient,
) -> None:
    headers = auth_headers(client, "site-a-investigator@example.test")

    response = client.post(
        "/api/source-files/upload",
        headers=headers,
        files={
            "file": (
                "synthetic-pulmonary.pdf",
                b"%PDF-1.7\n%%EOF",
                "application/octet-stream",
            )
        },
        data={"synthetic_attestation": "true"},
    )

    assert response.status_code == 201
    assert response.json()["mime_type"] == "application/pdf"


@pytest.mark.parametrize("stored_candidate_ids", [None, "[]"])
def test_pulmonary_pdf_upload_and_local_extraction_create_review_candidates_without_identifiers(
    tmp_path: Path,
    stored_candidate_ids: str | None,
) -> None:
    class SyntheticPulmonaryParser:
        def extract(self, pdf_path: Path):
            assert pdf_path.read_bytes().startswith(b"%PDF-")
            candidate = lambda code, value, unit: type(
                "PulmonaryCandidate",
                (),
                {
                    "field_code": code,
                    "proposed_value": value,
                    "unit": unit,
                    "evidence_text": f"PDF row {code}; selected=measured",
                },
            )()
            return type(
                "PulmonaryExtraction",
                (),
                {
                    "candidates": (
                        candidate("PFT_FEV1", "2.45", "L"),
                        candidate("PFT_FVC", "3.20", "L"),
                    ),
                    "engine_version": "pypdf-test",
                },
            )()

    app = create_app(
        database_path=tmp_path / "pulmonary.db",
        environment="test",
        pulmonary_parser=SyntheticPulmonaryParser(),
    )
    with TestClient(app) as test_client:
        headers = auth_headers(test_client, "site-a-investigator@example.test")
        upload = test_client.post(
            "/api/source-files/upload",
            headers=headers,
            files={"file": ("synthetic-pulmonary.pdf", b"%PDF-1.7\n%%EOF", "application/pdf")},
            data={"synthetic_attestation": "true"},
        )
        assert upload.status_code == 201

        extracted = test_client.post(
            f"/api/source-files/{upload.json()['id']}/pulmonary-function-extract",
            headers=headers,
            json={"edc_subject_ref": "SUBJ001", "edc_event_ref": "WEEK_0"},
        )
        recognition_job = test_client.post(
            "/api/recognition-jobs",
            headers=headers,
            json={
                "items": [
                    {
                        "source_file_id": upload.json()["id"],
                        "edc_subject_ref": "SUBJ001",
                        "edc_event_ref": "WEEK_0",
                        "field_codes": ["PFT_FEV1", "PFT_FVC"],
                    }
                ]
            },
        )
        assert recognition_job.status_code == 201
        completed_job = test_client.post(
            f"/api/recognition-jobs/{recognition_job.json()['id']}/run",
            headers=headers,
        )
        with test_client.app.state.database.connect() as connection:
            connection.execute(
                "UPDATE recognition_job_items SET candidate_ids_json = ? WHERE job_id = ?",
                (stored_candidate_ids, recognition_job.json()["id"]),
            )
        restored_job = test_client.get(
            f"/api/recognition-jobs/{recognition_job.json()['id']}",
            headers=headers,
        )
        repeated = test_client.post(
            f"/api/source-files/{upload.json()['id']}/pulmonary-function-extract",
            headers=headers,
            json={"edc_subject_ref": "SUBJ001", "edc_event_ref": "WEEK_0"},
        )
        conflict = test_client.post(
            f"/api/source-files/{upload.json()['id']}/pulmonary-function-extract",
            headers=headers,
            json={"edc_subject_ref": "SUBJ002", "edc_event_ref": "WEEK_0"},
        )

    assert extracted.status_code == 201
    assert [candidate["field_code"] for candidate in extracted.json()] == ["PFT_FEV1", "PFT_FVC"]
    assert all(candidate["kimi_model"] == "not_used_local_pdf" for candidate in extracted.json())
    assert all(candidate["status"] == "candidate" for candidate in extracted.json())
    assert completed_job.status_code == 200
    assert completed_job.json()["status"] == "succeeded"
    expected_candidate_ids = {candidate["id"] for candidate in extracted.json()}
    assert set(completed_job.json()["items"][0]["candidate_ids"]) == expected_candidate_ids
    assert set(restored_job.json()["items"][0]["candidate_ids"]) == expected_candidate_ids
    assert repeated.status_code == 200
    assert {candidate["id"] for candidate in repeated.json()} == {
        candidate["id"] for candidate in extracted.json()
    }
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "source_event_subject_conflict"
    assert not {"姓名", "住院号", "测试号"} & {
        candidate["field_code"] for candidate in extracted.json()
    }


def test_reviewer_can_list_and_select_only_requested_pulmonary_fields(
    tmp_path: Path,
) -> None:
    class SyntheticPulmonaryParser:
        def extract(self, _pdf_path: Path):
            def candidate(code: str, value: str):
                return type(
                    "PulmonaryCandidate",
                    (),
                    {
                        "field_code": code,
                        "proposed_value": value,
                        "unit": "L",
                        "evidence_text": f"PDF row {code}; selected=measured",
                    },
                )()

            return type(
                "PulmonaryExtraction",
                (),
                {
                    "candidates": (
                        candidate("PFT_FEV1", "2.45"),
                        candidate("PFT_FVC", "3.20"),
                    ),
                    "engine_version": "pypdf-test",
                },
            )()

    app = create_app(
        database_path=tmp_path / "selective-pulmonary.db",
        environment="test",
        pulmonary_parser=SyntheticPulmonaryParser(),
    )
    with TestClient(app) as test_client:
        headers = auth_headers(test_client, "site-a-investigator@example.test")
        options = test_client.get(
            "/api/recognition-fields?event_ref=WEEK_0",
            headers=headers,
        )
        upload = test_client.post(
            "/api/source-files/upload",
            headers=headers,
            files={"file": ("synthetic-pulmonary.pdf", b"%PDF-1.7\n%%EOF", "application/pdf")},
            data={"synthetic_attestation": "true"},
        )
        invalid = test_client.post(
            f"/api/source-files/{upload.json()['id']}/pulmonary-function-extract",
            headers=headers,
            json={
                "edc_subject_ref": "SUBJ001",
                "edc_event_ref": "WEEK_0",
                "field_codes": ["NOT_A_REAL_FIELD"],
            },
        )
        extracted = test_client.post(
            f"/api/source-files/{upload.json()['id']}/pulmonary-function-extract",
            headers=headers,
            json={
                "edc_subject_ref": "SUBJ001",
                "edc_event_ref": "WEEK_0",
                "field_codes": ["PFT_FVC"],
            },
        )

    assert options.status_code == 200
    pulmonary_options = [
        item for item in options.json()["fields"]
        if item["category"] == "pulmonary_function"
    ]
    assert len(pulmonary_options) == 18
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "recognition_field_not_allowed"
    assert extracted.status_code == 201
    assert [candidate["field_code"] for candidate in extracted.json()] == ["PFT_FVC"]


def test_pulmonary_extraction_rejects_non_pdf_source(client: TestClient) -> None:
    headers = auth_headers(client, "site-a-investigator@example.test")
    upload = client.post(
        "/api/source-files/upload",
        headers=headers,
        files={"file": ("synthetic.png", SYNTHETIC_PNG_BYTES, "image/png")},
        data={"synthetic_attestation": "true"},
    )

    extracted = client.post(
        f"/api/source-files/{upload.json()['id']}/pulmonary-function-extract",
        headers=headers,
        json={"edc_subject_ref": "SUBJ001", "edc_event_ref": "WEEK_0"},
    )

    assert extracted.status_code == 422
    assert extracted.json()["detail"] == "pulmonary_pdf_required"


def test_upload_provisions_libreclinica_subject_and_event_when_research_code_is_supplied(tmp_path: Path) -> None:
    class ProvisioningAdapter:
        mode = "libreclinica_soap"
        target_kind = "libreclinica"

        def __init__(self) -> None:
            self.provision_calls: list[tuple[str, str]] = []

        def readiness(self) -> dict[str, object]:
            return {"status": "ready", "write_path": "human_triggered"}

        def provision_subject(self, subject_ref: str, event_ref: str, *, enrollment_date) -> EdcProvisioningResult:
            assert enrollment_date
            self.provision_calls.append((subject_ref, event_ref))
            return EdcProvisioningResult(
                subject_ref=subject_ref,
                subject_oid="SS_SYNTH_010",
                event_ref=event_ref,
                subject_created=True,
                event_scheduled=True,
            )

        def submit(self, transfer_package: dict, *, idempotency_key: str) -> EdcSubmissionResult:
            raise AssertionError((transfer_package, idempotency_key))

    adapter = ProvisioningAdapter()
    app = create_app(
        database_path=tmp_path / "companion-provision.db",
        environment="test",
        edc_adapter=adapter,
    )
    with TestClient(app) as live_client:
        headers = auth_headers(live_client, "site-a-investigator@example.test")
        missing_reference = live_client.post(
            "/api/source-files/upload",
            headers=headers,
            files={"file": ("synthetic.png", SYNTHETIC_PNG_BYTES, "image/png")},
            data={"synthetic_attestation": "true"},
        )
        assert missing_reference.status_code == 422
        assert missing_reference.json()["detail"] == "subject_and_event_required_for_live_edc"
        response = live_client.post(
            "/api/source-files/upload",
            headers=headers,
            files={"file": ("synthetic.png", SYNTHETIC_PNG_BYTES, "image/png")},
            data={
                "synthetic_attestation": "true",
                "edc_subject_ref": "subj010",
                "edc_event_ref": "week_0",
            },
        )

    assert response.status_code == 201
    assert adapter.provision_calls == [("SUBJ010", "WEEK_0")]
    assert response.json()["edc_subject_provisioning"] == {
        "status": "completed",
        "subject_ref": "SUBJ010",
        "event_ref": "WEEK_0",
        "subject_oid": "SS_SYNTH_010",
        "subject_created": True,
        "event_scheduled": True,
        "provisioned_at": response.json()["edc_subject_provisioning"]["provisioned_at"],
        "error_code": None,
    }


def test_libreclinica_outage_does_not_block_local_pdf_review_or_reviewed_excel_export(
    tmp_path: Path,
) -> None:
    class UnreachableAdapter:
        mode = "libreclinica_soap"
        target_kind = "libreclinica"

        def __init__(self) -> None:
            self.provision_calls = 0

        def readiness(self) -> dict[str, object]:
            return {"status": "blocked", "write_path": "disabled"}

        def provision_subject(self, subject_ref: str, event_ref: str, *, enrollment_date):
            assert enrollment_date
            self.provision_calls += 1
            if self.provision_calls == 1:
                raise EdcAdapterError(
                    "libreclinica_unreachable",
                    "LibreClinica is unavailable.",
                    retryable=True,
                )
            return EdcProvisioningResult(
                subject_ref=subject_ref,
                subject_oid="SS_SUBJ011",
                event_ref=event_ref,
                subject_created=True,
                event_scheduled=True,
            )

        def submit(self, _transfer_package: dict, *, idempotency_key: str) -> EdcSubmissionResult:
            assert self.provision_calls == 2
            return EdcSubmissionResult(
                external_reference="S_TEST/SS_SUBJ011/SE_WEEK_0/F_TEST/I_PFT_FVC",
                response_sha256=hashlib.sha256(idempotency_key.encode()).hexdigest(),
            )

    class SyntheticPulmonaryParser:
        def extract(self, _pdf_path: Path):
            candidate = type(
                "PulmonaryCandidate",
                (),
                {
                    "field_code": "PFT_FVC",
                    "proposed_value": "3.20",
                    "unit": "L",
                    "evidence_text": "PDF row FVC; selected=measured",
                },
            )()
            return type(
                "PulmonaryExtraction",
                (),
                {"candidates": (candidate,), "engine_version": "pypdf-test"},
            )()

    class RecordingSpreadsheetExporter:
        ready = True

        def __init__(self) -> None:
            self.payloads: list[dict[str, object]] = []

        def export(self, payload: dict[str, object]) -> bytes:
            self.payloads.append(payload)
            return b"synthetic-xlsx"

    exporter = RecordingSpreadsheetExporter()
    adapter = UnreachableAdapter()
    app = create_app(
        database_path=tmp_path / "libreclinica-outage.db",
        environment="test",
        edc_adapter=adapter,
        pulmonary_parser=SyntheticPulmonaryParser(),
        spreadsheet_exporter=exporter,
    )
    with TestClient(app) as local_client:
        headers = auth_headers(local_client, "site-a-investigator@example.test")
        upload = local_client.post(
            "/api/source-files/upload",
            headers=headers,
            files={"file": ("synthetic-pulmonary.pdf", b"%PDF-1.7\n%%EOF", "application/pdf")},
            data={
                "synthetic_attestation": "true",
                "edc_subject_ref": "SUBJ011",
                "edc_event_ref": "WEEK_0",
            },
        )
        assert upload.status_code == 201
        assert upload.json()["edc_subject_provisioning"] == {
            "status": "deferred",
            "subject_ref": "SUBJ011",
            "event_ref": "WEEK_0",
            "subject_oid": None,
            "subject_created": False,
            "event_scheduled": False,
            "provisioned_at": None,
            "error_code": "libreclinica_unreachable",
        }

        extracted = local_client.post(
            f"/api/source-files/{upload.json()['id']}/pulmonary-function-extract",
            headers=headers,
            json={
                "edc_subject_ref": "SUBJ011",
                "edc_event_ref": "WEEK_0",
                "field_codes": ["PFT_FVC"],
            },
        )
        assert extracted.status_code == 201
        candidate = extracted.json()[0]
        reviewed = local_client.post(
            f"/api/candidates/{candidate['id']}/review",
            headers=headers,
            json={"decision": "accept"},
        )
        assert reviewed.status_code == 200

        exported = local_client.get(
            "/api/exports/reviewed-recognition-data.xlsx",
            headers=headers,
        )
        transfer = local_client.post(
            f"/api/candidates/{candidate['id']}/transfers",
            headers=headers,
        )
        assert transfer.status_code == 201
        submitted = local_client.post(
            f"/api/transfers/{transfer.json()['id']}/submit",
            headers=headers,
        )

    assert exported.status_code == 200
    assert exported.content == b"synthetic-xlsx"
    assert exporter.payloads[-1]["reviewed_value_count"] == 1
    assert exporter.payloads[-1]["events"]["WEEK_0"]["rows"][0]["authority_status"] == "not_submitted"
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"
    assert adapter.provision_calls == 2


def test_local_ocr_creates_candidates_from_an_attested_synthetic_image(tmp_path: Path) -> None:
    class SyntheticOcr:
        def extract(self, image_path: Path):
            assert image_path.exists()
            return type(
                "SyntheticOcrResult",
                (),
                {"text": "ALT: 31 U/L\nAST: 23 U/L", "engine_version": "synthetic-tesseract-5.5"},
            )()

    app = create_app(database_path=tmp_path / "companion.db", environment="test", ocr_client=SyntheticOcr())
    with TestClient(app) as local_client:
        entry_headers = auth_headers(local_client, "site-a-investigator@example.test")
        source_response = local_client.post(
            "/api/source-files/upload",
            headers=entry_headers,
            files={"file": ("synthetic.png", SYNTHETIC_PNG_BYTES, "image/png")},
            data={"synthetic_attestation": "true"},
        )
        assert source_response.status_code == 201

        ocr_response = local_client.post(
            f"/api/source-files/{source_response.json()['id']}/local-ocr-extract",
            headers=entry_headers,
            json={"edc_subject_ref": "SUBJ001", "edc_event_ref": "WEEK_0"},
        )
        assert ocr_response.status_code == 201
        candidates = ocr_response.json()
        assert [(candidate["field_code"], candidate["proposed_value"]) for candidate in candidates] == [
            ("ALT", "31"),
            ("AST", "23"),
        ]
        assert {candidate["ocr_engine_version"] for candidate in candidates} == {"synthetic-tesseract-5.5"}
        assert {candidate["kimi_model"] for candidate in candidates} == {"not_used_local_ocr"}

        audit_response = local_client.get(f"/api/candidates/{candidates[0]['id']}/audit", headers=entry_headers)
        assert audit_response.status_code == 200
        assert audit_response.json()[-1]["details"]["mode"] == "local_ocr"


def test_local_ocr_parses_table_rows_with_reference_ranges_and_units(tmp_path: Path) -> None:
    class SyntheticOcr:
        def extract(self, image_path: Path):
            assert image_path.exists()
            return type(
                "SyntheticOcrResult",
                (),
                {
                    "text": (
                        "WBC 4.50 3.5-9.5 10^9/L\n"
                        "K 3.9 3.5-5.3 mmol/L\n"
                        "CRP <0.5 0-8 mg/L"
                    ),
                    "engine_version": "synthetic-tesseract-5.5",
                },
            )()

    app = create_app(database_path=tmp_path / "companion.db", environment="test", ocr_client=SyntheticOcr())
    with TestClient(app) as local_client:
        entry_headers = auth_headers(local_client, "site-a-investigator@example.test")
        source_response = local_client.post(
            "/api/source-files/upload",
            headers=entry_headers,
            files={"file": ("synthetic-check-sheet.png", SYNTHETIC_PNG_BYTES, "image/png")},
            data={"synthetic_attestation": "true"},
        )
        assert source_response.status_code == 201

        ocr_response = local_client.post(
            f"/api/source-files/{source_response.json()['id']}/local-ocr-extract",
            headers=entry_headers,
            json={"edc_subject_ref": "SUBJ001", "edc_event_ref": "WEEK_0"},
        )

        assert ocr_response.status_code == 201
        assert [
            (candidate["field_code"], candidate["proposed_value"], candidate["unit"])
            for candidate in ocr_response.json()
        ] == [
            ("WBC", "4.50", "10^9/L"),
            ("K", "3.9", "mmol/L"),
            ("CRP", "<0.5", "mg/L"),
        ]


def test_local_ocr_saves_mapped_results_and_skips_unmapped_codes_without_their_values(tmp_path: Path) -> None:
    class SyntheticOcr:
        def extract(self, image_path: Path):
            assert image_path.exists()
            return type(
                "SyntheticOcrResult",
                (),
                {
                    "text": "ALT 31 9-50 U/L\nGLU 5.2 3.9-6.1 mmol/L",
                    "engine_version": "synthetic-tesseract-5.5",
                },
            )()

    app = create_app(database_path=tmp_path / "companion.db", environment="test", ocr_client=SyntheticOcr())
    with TestClient(app) as local_client:
        entry_headers = auth_headers(local_client, "site-a-investigator@example.test")
        source_response = local_client.post(
            "/api/source-files/upload",
            headers=entry_headers,
            files={"file": ("synthetic-check-sheet.png", SYNTHETIC_PNG_BYTES, "image/png")},
            data={"synthetic_attestation": "true"},
        )
        assert source_response.status_code == 201

        ocr_response = local_client.post(
            f"/api/source-files/{source_response.json()['id']}/local-ocr-extract",
            headers=entry_headers,
            json={"edc_subject_ref": "SUBJ001", "edc_event_ref": "WEEK_0"},
        )

        assert ocr_response.status_code == 201
        assert [
            (candidate["field_code"], candidate["proposed_value"], candidate["unit"])
            for candidate in ocr_response.json()
        ] == [("ALT", "31", "U/L")]
        audit_response = local_client.get(
            f"/api/candidates/{ocr_response.json()[0]['id']}/audit",
            headers=entry_headers,
        )
        assert audit_response.status_code == 200
        assert audit_response.json()[-1]["details"]["ignored_unmapped_field_codes"] == ["GLU"]
        assert "5.2" not in json.dumps(
            [event["details"] for event in audit_response.json()],
            ensure_ascii=False,
        )


def test_local_ocr_replays_saved_candidates_without_rerunning_or_duplicating(tmp_path: Path) -> None:
    class CountingSyntheticOcr:
        calls = 0

        def extract(self, image_path: Path):
            assert image_path.exists()
            self.calls += 1
            return type(
                "SyntheticOcrResult",
                (),
                {"text": "ALT 31 9-50 U/L", "engine_version": "synthetic-tesseract-5.5"},
            )()

    ocr_client = CountingSyntheticOcr()
    app = create_app(database_path=tmp_path / "companion.db", environment="test", ocr_client=ocr_client)
    with TestClient(app) as local_client:
        entry_headers = auth_headers(local_client, "site-a-investigator@example.test")
        source_response = local_client.post(
            "/api/source-files/upload",
            headers=entry_headers,
            files={"file": ("synthetic-check-sheet.png", SYNTHETIC_PNG_BYTES, "image/png")},
            data={"synthetic_attestation": "true"},
        )
        assert source_response.status_code == 201
        endpoint = f"/api/source-files/{source_response.json()['id']}/local-ocr-extract"
        payload = {"edc_subject_ref": "SUBJ001", "edc_event_ref": "WEEK_0"}

        first_response = local_client.post(endpoint, headers=entry_headers, json=payload)
        replay_response = local_client.post(endpoint, headers=entry_headers, json=payload)

        assert first_response.status_code == 201
        assert replay_response.status_code == 200
        assert replay_response.json() == first_response.json()
        assert ocr_client.calls == 1
        list_response = local_client.get("/api/candidates", headers=entry_headers)
        assert list_response.status_code == 200
        assert [candidate["id"] for candidate in list_response.json()] == [first_response.json()[0]["id"]]


def test_local_ocr_rejects_a_field_absent_from_the_versioned_crf_mapping(tmp_path: Path) -> None:
    class SyntheticOcr:
        def extract(self, image_path: Path):
            assert image_path.exists()
            return type(
                "SyntheticOcrResult",
                (),
                {"text": "BADLAB: 31 U/L", "engine_version": "synthetic-tesseract-5.5"},
            )()

    app = create_app(database_path=tmp_path / "companion.db", environment="test", ocr_client=SyntheticOcr())
    with TestClient(app) as local_client:
        entry_headers = auth_headers(local_client, "site-a-investigator@example.test")
        source_response = local_client.post(
            "/api/source-files/upload",
            headers=entry_headers,
            files={"file": ("synthetic.png", SYNTHETIC_PNG_BYTES, "image/png")},
            data={"synthetic_attestation": "true"},
        )
        assert source_response.status_code == 201

        ocr_response = local_client.post(
            f"/api/source-files/{source_response.json()['id']}/local-ocr-extract",
            headers=entry_headers,
            json={"edc_subject_ref": "SUBJ001", "edc_event_ref": "WEEK_0"},
        )
        assert ocr_response.status_code == 422
        assert ocr_response.json()["detail"] == "field_not_in_crf_mapping"


def test_local_ocr_distinguishes_an_event_absent_from_the_versioned_crf_mapping(tmp_path: Path) -> None:
    class SyntheticOcr:
        def extract(self, image_path: Path):
            assert image_path.exists()
            return type(
                "SyntheticOcrResult",
                (),
                {"text": "ALT: 31 U/L", "engine_version": "synthetic-tesseract-5.5"},
            )()

    app = create_app(database_path=tmp_path / "companion.db", environment="test", ocr_client=SyntheticOcr())
    with TestClient(app) as local_client:
        entry_headers = auth_headers(local_client, "site-a-investigator@example.test")
        source_response = local_client.post(
            "/api/source-files/upload",
            headers=entry_headers,
            files={"file": ("synthetic.png", SYNTHETIC_PNG_BYTES, "image/png")},
            data={"synthetic_attestation": "true"},
        )
        assert source_response.status_code == 201

        ocr_response = local_client.post(
            f"/api/source-files/{source_response.json()['id']}/local-ocr-extract",
            headers=entry_headers,
            json={"edc_subject_ref": "SUBJ001", "edc_event_ref": "WEEK_16"},
        )
        assert ocr_response.status_code == 422
        assert ocr_response.json()["detail"] == "event_not_in_crf_mapping"


def test_local_deidentification_draft_requires_human_confirmation_before_candidate_extraction(
    tmp_path: Path,
) -> None:
    class SyntheticDeidentifier:
        def redact(self, image_path: Path, output_path: Path):
            assert image_path.exists()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"redacted-synthetic-png")
            return type(
                "SyntheticRedactionResult",
                (),
                {
                    "detected_marker_codes": ("patient_name",),
                    "engine_version": "synthetic-tesseract-5.5;lang=chi_sim+eng",
                },
            )()

    class SyntheticOcr:
        calls = 0

        def extract(self, image_path: Path):
            self.calls += 1
            assert image_path.read_bytes() == b"redacted-synthetic-png"
            return type(
                "SyntheticOcrResult",
                (),
                {"text": "ALT: 31 U/L", "engine_version": "synthetic-tesseract-5.5"},
            )()

    ocr_client = SyntheticOcr()
    app = create_app(
        database_path=tmp_path / "companion.db",
        environment="test",
        ocr_client=ocr_client,
        deidentifier=SyntheticDeidentifier(),
    )
    with TestClient(app) as local_client:
        entry_headers = auth_headers(local_client, "site-a-investigator@example.test")
        other_centre_headers = auth_headers(local_client, "site-b-investigator@example.test")
        source_response = local_client.post(
            "/api/source-files/upload",
            headers=entry_headers,
            files={"file": ("synthetic-identified.png", SYNTHETIC_PNG_BYTES, "image/png")},
            data={"synthetic_attestation": "true"},
        )
        assert source_response.status_code == 201

        draft_response = local_client.post(
            f"/api/source-files/{source_response.json()['id']}/deidentification-drafts",
            headers=entry_headers,
        )
        assert draft_response.status_code == 201
        draft = draft_response.json()
        assert draft["status"] == "draft"
        assert draft["detected_marker_codes"] == ["patient_name"]
        assert draft["requires_human_review"] is True
        assert draft["original_source_file_id"] == source_response.json()["id"]
        assert "ocr_text" not in draft
        assert "identifier" not in str(draft).lower()

        preview_response = local_client.get(
            f"/api/deidentification-drafts/{draft['id']}/image",
            headers=entry_headers,
        )
        assert preview_response.status_code == 200
        assert preview_response.content == b"redacted-synthetic-png"
        assert preview_response.headers["cache-control"] == "no-store"
        isolated_preview = local_client.get(
            f"/api/deidentification-drafts/{draft['id']}/image",
            headers=other_centre_headers,
        )
        assert isolated_preview.status_code == 404

        derivative_source_id = draft["derivative_source_file"]["id"]
        blocked_extract = local_client.post(
            f"/api/source-files/{derivative_source_id}/local-ocr-extract",
            headers=entry_headers,
            json={"edc_subject_ref": "SUBJ001", "edc_event_ref": "WEEK_0"},
        )
        assert blocked_extract.status_code == 409
        assert blocked_extract.json()["detail"] == "deidentification_confirmation_required"
        assert ocr_client.calls == 0

        blocked_manual_candidate = local_client.post(
            "/api/candidates",
            headers=entry_headers,
            json={
                "source_file_id": derivative_source_id,
                "edc_subject_ref": "SUBJ001",
                "edc_event_ref": "WEEK_0",
                "field_code": "ALT",
                "proposed_value": "31",
                "unit": "U/L",
                "ocr_engine_version": "manual-test",
                "kimi_model": "not_used",
                "schema_version": "manual-test",
                "confidence": 0.5,
            },
        )
        assert blocked_manual_candidate.status_code == 409
        assert blocked_manual_candidate.json()["detail"] == "deidentification_confirmation_required"
        blocked_text_extract = local_client.post(
            f"/api/source-files/{derivative_source_id}/demo-extract",
            headers=entry_headers,
            json={
                "edc_subject_ref": "SUBJ001",
                "edc_event_ref": "WEEK_0",
                "deidentified_ocr_text": "ALT: 31 U/L",
            },
        )
        assert blocked_text_extract.status_code == 409
        assert blocked_text_extract.json()["detail"] == "deidentification_confirmation_required"

        missing_attestation = local_client.post(
            f"/api/deidentification-drafts/{draft['id']}/confirm",
            headers=entry_headers,
            json={"human_review_attestation": False},
        )
        assert missing_attestation.status_code == 422
        assert missing_attestation.json()["detail"] == "deidentification_review_attestation_required"
        confirmed_response = local_client.post(
            f"/api/deidentification-drafts/{draft['id']}/confirm",
            headers=entry_headers,
            json={"human_review_attestation": True},
        )
        assert confirmed_response.status_code == 200
        assert confirmed_response.json()["status"] == "confirmed"

        extracted = local_client.post(
            f"/api/source-files/{derivative_source_id}/local-ocr-extract",
            headers=entry_headers,
            json={"edc_subject_ref": "SUBJ001", "edc_event_ref": "WEEK_0"},
        )
        assert extracted.status_code == 201
        assert [(row["field_code"], row["proposed_value"]) for row in extracted.json()] == [("ALT", "31")]
        assert ocr_client.calls == 1


def test_two_image_batch_can_be_confirmed_extracted_reviewed_and_submitted(tmp_path: Path) -> None:
    class SyntheticDeidentifier:
        def redact(self, image_path: Path, output_path: Path):
            assert image_path.exists()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"redacted-synthetic-png")
            return type(
                "SyntheticRedactionResult",
                (),
                {
                    "detected_marker_codes": (),
                    "engine_version": "synthetic-redactor-v1",
                },
            )()

    class SequenceOcr:
        def __init__(self) -> None:
            self.calls = 0

        def extract(self, image_path: Path):
            assert image_path.read_bytes() == b"redacted-synthetic-png"
            field, value = (("ALT", "31"), ("AST", "23"))[self.calls]
            self.calls += 1
            return type(
                "SyntheticOcrResult",
                (),
                {"text": f"{field}: {value} U/L", "engine_version": "synthetic-tesseract-5.5"},
            )()

    class BatchAdapter:
        mode = "libreclinica_soap"
        target_kind = "libreclinica"

        def __init__(self) -> None:
            self.submitted_fields: list[str] = []

        def readiness(self) -> dict[str, object]:
            return {
                "authority_edc": "LibreClinica",
                "mode": self.mode,
                "write_path": "human_triggered",
                "status": "ready",
                "blockers": [],
            }

        def provision_subject(self, subject_ref: str, event_ref: str, *, enrollment_date) -> EdcProvisioningResult:
            return EdcProvisioningResult(
                subject_ref=subject_ref,
                subject_oid=f"SS_{subject_ref}",
                event_ref=event_ref,
                subject_created=False,
                event_scheduled=False,
            )

        def submit(self, transfer_package: dict, *, idempotency_key: str) -> EdcSubmissionResult:
            field_code = str(transfer_package["edc_record"]["field_code"])
            self.submitted_fields.append(field_code)
            return EdcSubmissionResult(
                external_reference=f"S_TEST/SS_SUBJ001/SE_WEEK0/F_TEST/I_{field_code}",
                response_sha256=hashlib.sha256(idempotency_key.encode()).hexdigest(),
            )

    ocr_client = SequenceOcr()
    adapter = BatchAdapter()
    app = create_app(
        database_path=tmp_path / "batch.db",
        environment="test",
        ocr_client=ocr_client,
        deidentifier=SyntheticDeidentifier(),
        edc_adapter=adapter,
    )
    with TestClient(app) as local_client:
        headers = auth_headers(local_client, "site-a-investigator@example.test")
        draft_ids: list[str] = []
        derivative_source_ids: list[str] = []
        for index in range(2):
            uploaded = local_client.post(
                "/api/source-files/upload",
                headers=headers,
                files={"file": (f"synthetic-{index}.png", SYNTHETIC_PNG_BYTES, "image/png")},
                data={
                    "synthetic_attestation": "true",
                    "edc_subject_ref": "SUBJ001",
                    "edc_event_ref": "WEEK_0",
                },
            )
            assert uploaded.status_code == 201
            draft = local_client.post(
                f"/api/source-files/{uploaded.json()['id']}/deidentification-drafts",
                headers=headers,
            )
            assert draft.status_code == 201
            draft_ids.append(draft.json()["id"])
            derivative_source_ids.append(draft.json()["derivative_source_file"]["id"])

        for draft_id, derivative_source_id in zip(draft_ids, derivative_source_ids, strict=True):
            confirmed = local_client.post(
                f"/api/deidentification-drafts/{draft_id}/confirm",
                headers=headers,
                json={"human_review_attestation": True},
            )
            assert confirmed.status_code == 200
            extracted = local_client.post(
                f"/api/source-files/{derivative_source_id}/local-ocr-extract",
                headers=headers,
                json={"edc_subject_ref": "SUBJ001", "edc_event_ref": "WEEK_0"},
            )
            assert extracted.status_code == 201

        candidates = local_client.get("/api/candidates", headers=headers).json()
        assert [candidate["field_code"] for candidate in candidates] == ["ALT", "AST"]
        for candidate in candidates:
            reviewed = local_client.post(
                f"/api/candidates/{candidate['id']}/review",
                headers=headers,
                json={"decision": "accept"},
            )
            assert reviewed.status_code == 200
            transfer = local_client.post(
                f"/api/candidates/{candidate['id']}/transfers",
                headers=headers,
            )
            assert transfer.status_code == 201
            submitted = local_client.post(
                f"/api/transfers/{transfer.json()['id']}/submit",
                headers=headers,
            )
            assert submitted.status_code == 200
            assert submitted.json()["status"] == "submitted"

        assert ocr_client.calls == 2
        assert adapter.submitted_fields == ["ALT", "AST"]
        assert {row["status"] for row in local_client.get("/api/transfers", headers=headers).json()} == {"submitted"}


def test_homepage_exposes_batch_deidentification_preview_and_confirmation_controls(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert 'id="deidentification-panel"' in response.text
    assert 'id="deidentification-previews"' in response.text
    assert 'id="deidentification-review-attestation"' in response.text
    assert 'id="confirm-deidentification-draft"' in response.text
    assert "不会修改或删除原图" in response.text


def test_homepage_queues_reports_per_subject_before_unified_recognition_and_review(
    client: TestClient,
) -> None:
    response = client.get("/")
    script = workbench_script(client)

    assert response.status_code == 200
    assert 'id="add-patient-reports"' in response.text
    assert 'id="patient-upload-queue"' in response.text
    assert 'id="patient-upload-queue-count"' in response.text
    assert "let pendingUploadQueue = []" in script
    assert "function addPatientReportsToQueue" in script
    assert "function removeQueuedPatientReport" in script
    assert 'form.append("edc_subject_ref", item.subjectRef)' in script
    assert 'form.append("edc_event_ref", item.eventRef)' in script
    assert "function renderCandidatesBySubject" in script
    assert 'class="candidate-subject-group"' in script
    assert "依次填写病人编号并加入检查报告" in response.text
    assert "finally {\n        renderPendingUploadQueue();\n      }" in script


def test_homepage_disables_browser_caching_for_ui_updates(client: TestClient) -> None:
    response = client.get("/")
    script = workbench_script(client)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["expires"] == "0"
    assert "确认并批量识别" in response.text
    assert "application/pdf" in response.text
    assert "/pulmonary-function-extract" in script
    assert 'source.edc_subject_provisioning.status === "deferred"' in script
    assert "不影响识别、审核与 Excel 导出" in script
    assert 'id="create-deidentification-draft"' not in response.text


def test_http_responses_include_baseline_browser_security_headers(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "script-src 'self';" in response.headers["content-security-policy"]


def test_homepage_serves_external_workbench_script_without_runtime_data(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert '<script src="/static/js/workbench.js?v=20260822-dreamina-assets-v1"></script>' in response.text
    assert 'id="workspace-context-art"' in response.text
    assert 'alt="" aria-hidden="true"' in response.text
    assert "<script>" not in response.text

    script = client.get("/static/js/workbench.js")
    assert script.status_code == 200
    assert script.headers["cache-control"] == "no-store, max-age=0"
    assert "function addPatientReportsToQueue" in script.text
    assert "api_key" not in script.text

    for asset_name in (
        "workbench-central-context.webp",
        "workbench-site-context.webp",
        "workbench-review-empty.webp",
    ):
        asset = client.get(f"/static/img/{asset_name}")
        assert asset.status_code == 200
        assert asset.headers["content-type"] == "image/webp"
        assert len(asset.content) > 1_000

    assert client.get("/static/img/unlisted.webp").status_code == 404


def test_homepage_keeps_diagnostics_in_an_accessible_compact_command_deck(
    client: TestClient,
) -> None:
    response = client.get("/")
    stylesheet = client.get("/static/css/app.css")

    assert response.status_code == 200
    assert '<details class="session-health lite-full-only">' in response.text
    assert '<summary><span>系统状态</span>' in response.text
    assert 'id="edc-status"' in response.text
    assert 'id="production-status"' in response.text
    assert (
        'href="/static/css/app.css?v=20260831-agpl-source-v1"'
        in response.text
    )
    assert stylesheet.status_code == 200
    assert ".session-health" in stylesheet.text
    assert ".session-actions { display: grid;" in stylesheet.text
    assert "scroll-snap-type: x proximity" in stylesheet.text
    assert "ClinData Relay 采用 AGPL-3.0-only 开源许可" in response.text
    assert 'href="https://github.com/KR0817/clin-data-relay"' in response.text
    assert ".site-footer" in stylesheet.text


def test_homepage_exposes_one_time_centre_credentials_and_authenticated_kimi_settings(
    client: TestClient,
) -> None:
    response = client.get("/")
    script = workbench_script(client)

    assert 'id="setup-credential-receipt"' in response.text
    assert 'id="copy-setup-credential"' in response.text
    assert 'id="download-setup-credential"' in response.text
    assert 'id="continue-after-setup"' in response.text
    assert 'id="kimi-settings-card"' in response.text
    assert 'id="kimi-key" type="password"' in response.text
    assert 'api("/api/settings/kimi"' in script
    assert "function downloadSetupCredential" in script
    assert "function saveKimiKey" in script
    assert "if (currentUser) return;" in script


def test_homepage_exposes_durable_recognition_job_panel(client: TestClient) -> None:
    response = client.get("/")
    script = workbench_script(client)

    assert response.status_code == 200
    assert 'id="recognition-job-panel"' in response.text
    assert 'id="recognition-job-items"' in response.text
    assert 'id="refresh-recognition-job"' in response.text
    assert 'id="run-recognition-job"' in response.text
    assert 'id="cancel-recognition-job"' in response.text
    assert 'id="retry-recognition-job"' in response.text
    assert "function refreshRecognitionJobs" in script
    assert "function selectNewestPendingRecognitionBatch" in script
    assert "recognitionJobs.find(function(job)" in script
    assert "selectNewestPendingRecognitionBatch(candidates);" in script
    assert "function createRecognitionJobFromBatch" in script
    assert "/api/recognition-jobs/" in script
    assert "item.candidate_ids || []" in script
    login_script = script.split("async function login()", 1)[1].split("function randomCharacter", 1)[0]
    assert login_script.index("await refreshRecognitionJobs()") < login_script.index("await refreshCandidates()")


def test_homepage_serves_external_stylesheet_without_exposing_runtime_data(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert (
        'href="/static/css/app.css?v=20260831-agpl-source-v1"'
        in response.text
    )
    assert "<style>" not in response.text
    assert "<script>" not in response.text

    stylesheet = client.get("/static/css/app.css")
    assert stylesheet.status_code == 200
    assert stylesheet.headers["cache-control"] == "no-store, max-age=0"
    assert "--primary: #2563eb" in stylesheet.text
    assert "api_key" not in stylesheet.text


def test_homepage_uses_inline_optional_review_controls_instead_of_modal_or_prompt(client: TestClient) -> None:
    response = client.get("/")
    script = workbench_script(client)

    assert response.status_code == 200
    assert 'data-action="accept-candidate"' in script
    assert 'data-action="open-review"' in script
    assert "审核说明 <span class=\"optional\">选填" in script
    assert 'id="review-action-panel"' not in script
    assert "prompt(" not in script


def test_homepage_uses_single_page_batch_ocr_and_submit_all_flow_and_removes_unused_controls_and_entry_accounts(
    client: TestClient,
) -> None:
    response = client.get("/")
    script = workbench_script(client)

    assert response.status_code == 200
    assert 'id="confirmed-records"' in response.text
    assert 'id="confirmed-records-status"' in response.text
    assert 'id="upload-and-recognize"' in response.text
    assert 'id="image-file"' in response.text
    assert 'accept="image/png,image/jpeg,application/pdf,.pdf"' in response.text
    assert 'multiple>' in response.text
    assert 'id="batch-progress"' in response.text
    assert 'id="submit-all-confirmed"' in response.text
    assert "冻结并提交全部已接受数据" in response.text
    assert 'id="ocr-text"' not in response.text
    assert "演示提取候选值" not in response.text
    assert 'id="kimi-extract"' not in response.text
    assert "/hybrid-extract" in script
    assert "Kimi 启用时，仅发送人工确认后的去标识化衍生图" in response.text
    assert "extraction_agreement" in script
    assert "site-a-entry@example.test" not in response.text
    assert "site-b-entry@example.test" not in response.text
    assert "site-b-investigator@example.test" in response.text


def test_homepage_exposes_compact_ai_toggle_bulk_accept_admin_dictionary_and_one_click_export(
    client: TestClient,
) -> None:
    response = client.get("/")
    script = workbench_script(client)

    assert response.status_code == 200
    assert 'id="kimi-toggle"' in response.text
    assert 'role="switch"' in response.text
    assert 'id="accept-recommended-batch"' in response.text
    assert 'id="accept-reviewable-batch"' in response.text
    assert 'id="accept-current-batch"' not in response.text
    assert "批量接受本地证据项" in response.text
    assert "查看需逐项审核项" in response.text
    assert 'data-bulk-accept-group="recommended"' in response.text
    assert 'data-bulk-accept-group="reviewable"' in response.text
    assert 'id="accept-recommended-batch" class="success" data-bulk-accept-group="recommended" type="button">' in response.text
    assert 'id="accept-reviewable-batch" class="secondary" data-bulk-accept-group="reviewable" type="button">' in response.text
    assert "recommendedButton.disabled = false;" in script
    assert "reviewableButton.disabled = false;" in script
    assert "groups.recommended.push(candidate);" in script
    assert "const hasActiveBatchContext = activeBatchCandidateIds.size > 0;" in script
    accept_script = script.split("async function acceptCurrentBatchGroup", 1)[1].split(
        "function transferActions", 1
    )[0]
    assert "function currentBatchCandidateIds" in script
    assert "let candidateIds = currentBatchCandidateIds(groupName);" in accept_script
    assert "await refreshRecognitionJobs();" in accept_script
    assert "await refreshCandidates();" in accept_script
    assert "candidateIds = currentBatchCandidateIds(groupName);" in accept_script
    assert "groups.reviewable.push(candidate);" in script
    assert "当前批次没有可批量接受的候选" in script
    assert '["conflict", "kimi_only"].includes(candidate.extraction_agreement)' in script
    assert "load-review-evidence" in script
    assert "evidence_acknowledged" in script
    assert "review-evidence-layout" in script
    assert 'candidate.extraction_agreement === "conflict"' in script
    assert '"待选择（本地 "' in script
    assert 'id="field-dictionary-section"' in response.text
    assert 'id="download-submitted-excel"' in response.text
    assert 'id="download-reviewed-package"' in response.text
    assert 'id="offline-package-file"' in response.text
    assert "/api/exports/reviewed-recognition-package.json" in script
    assert "/api/imports/reviewed-package" in script
    assert "/api/exports/reviewed-recognition-data.xlsx" in script
    assert 'id="recognition-field-scope"' in response.text
    assert 'id="recognition-field-search"' in response.text
    assert 'id="select-pulmonary-fields"' in response.text
    assert 'id="recognition-field-options"' in response.text
    assert 'rel="icon"' in response.text
    assert 'field_codes: item.selectedFieldCodes' in script
    assert 'cache: "no-store"' in script
    assert "currentCandidatesById.set(candidate.id, candidate)" in script
    assert 'id="operations-section"' in response.text
    assert 'class="workspace-nav"' in response.text
    assert 'class="session-tools"' in response.text
    assert '<details id="recognition-field-scope" class="recognition-scope">' in response.text
    assert 'target instanceof HTMLDetailsElement' in script
    assert 'id="structured-csv-file"' in response.text
    assert 'id="analysis-snapshots"' in response.text
    assert 'id="dictionary-release-select"' in response.text
    assert 'id="user-accounts"' in response.text
    stylesheet = client.get("/static/css/app.css")
    assert stylesheet.status_code == 200
    assert "color-scheme: light" in stylesheet.text
    assert ".workspace-nav" in stylesheet.text
    assert "prefers-reduced-motion: reduce" in stylesheet.text
    assert "font-size: 14px" in stylesheet.text


def test_homepage_contains_lite_profile_for_local_recognition_review_and_export(
    client: TestClient,
) -> None:
    response = client.get("/")
    script = workbench_script(client)

    assert response.status_code == 200
    assert "function applyProductMode" in script
    assert 'results[0].product_mode || "full"' in script
    assert 'id="setup-card"' in response.text
    assert 'id="generate-setup-password"' in response.text
    assert 'window.crypto.getRandomValues' in script
    assert 'api("/api/setup/status")' in script
    assert 'api("/api/setup/complete"' in script
    assert 'id="operations-section" class="card workflow-card lite-full-only"' in response.text
    assert 'id="step-freeze" class="lite-full-only"' in response.text
    assert 'id="step-submit" class="lite-full-only"' in response.text
    assert 'id="confirmed-title"' in response.text
    assert "本地已确认数据" in script
    assert "Clinical Report Extractor Lite" in script
    assert "body.lite-mode .lite-full-only" in client.get("/static/css/app.css").text


def test_homepage_uses_compact_confirmed_list_and_omits_redundant_intro_copy(client: TestClient) -> None:
    response = client.get("/")
    script = workbench_script(client)

    assert response.status_code == 200
    assert "上传、识别、人工确认与 LibreClinica 传输在同一页面完成" not in response.text
    assert "请勿上传真实患者资料。" not in response.text
    assert "Excel 导出按账号权限过滤；生产就绪状态" not in response.text
    assert "按当前账号权限汇总待审核、质量拦截、数据问题、传输与权威库回读状态" not in response.text
    assert 'id="confirmed-records" class="confirmed-list"' in response.text
    assert 'id="toggle-confirmed-records"' in response.text
    assert 'aria-controls="confirmed-records"' in response.text
    assert 'aria-expanded="false"' in response.text
    assert "展开其余" in script
    assert "收起，仅显示前 5 条" in script


def test_legacy_entry_accounts_are_inactive_and_each_site_has_an_investigator(client: TestClient) -> None:
    for username in ("site-a-entry@example.test", "site-b-entry@example.test"):
        response = client.post(
            "/api/auth/login",
            json={"username": username, "password": "demo-password"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "invalid_credentials"

    for username in (
        "site-a-investigator@example.test",
        "site-b-investigator@example.test",
        "central-data-manager@example.test",
    ):
        response = client.post(
            "/api/auth/login",
            json={"username": username, "password": "demo-password"},
        )
        assert response.status_code == 200
        assert response.json()["user"]["role"] in {"site_investigator", "central_data_manager"}


def test_first_sandbox_login_upgrades_legacy_demo_hash_and_chains_the_event(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"username": "site-a-investigator@example.test", "password": "demo-password"},
    )

    assert response.status_code == 200
    with client.app.state.database.connect() as connection:
        user = connection.execute(
            "SELECT password_hash, credential_kind FROM users WHERE username = ?",
            ("site-a-investigator@example.test",),
        ).fetchone()
        event = connection.execute(
            "SELECT event_hash FROM audit_events WHERE event_type = 'credential_hash_upgraded'"
        ).fetchone()
    assert user["password_hash"].startswith("scrypt$")
    assert user["credential_kind"] == "current"
    assert len(event["event_hash"]) == 64


def test_production_environment_rejects_seeded_legacy_demo_credentials(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "production.db", environment="production")
    with TestClient(app) as production_client:
        response = production_client.post(
            "/api/auth/login",
            json={"username": "central-data-manager@example.test", "password": "demo-password"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_credentials"


def test_generic_portable_synthetic_lite_upgrades_its_documented_demo_login(
    tmp_path: Path,
) -> None:
    app = create_app(
        database_path=tmp_path / "portable.db",
        environment="portable_synthetic",
        product_mode="lite",
    )
    with TestClient(app) as portable_client:
        response = portable_client.post(
            "/api/auth/login",
            json={
                "username": "site-a-investigator@example.test",
                "password": "demo-password",
            },
        )

    assert response.status_code == 200
    with app.state.database.connect() as connection:
        account = connection.execute(
            "SELECT password_hash, credential_kind FROM users WHERE username = ?",
            ("site-a-investigator@example.test",),
        ).fetchone()
    assert account["password_hash"].startswith("scrypt$")
    assert account["credential_kind"] == "current"


def test_local_ocr_uses_conservative_chinese_table_fallback_when_plain_text_has_no_mapped_codes(
    tmp_path: Path,
) -> None:
    class SyntheticOcr:
        def extract(self, image_path: Path):
            assert image_path.exists()
            return type(
                "SyntheticOcrResult",
                (),
                {"text": "脱敏后的中文检验表格", "engine_version": "synthetic-tesseract-5.5"},
            )()

    class SyntheticChineseLabExtractor:
        def extract(self, image_path: Path):
            assert image_path.exists()
            return type(
                "SyntheticStructuredResult",
                (),
                {
                    "candidates": (("WBC", "4.50", None), ("ALT", "31", "U/L")),
                    "ambiguous_field_codes": (),
                    "engine_version": "synthetic-tesseract-5.5;structured-chinese-v0.1",
                },
            )()

    app = create_app(
        database_path=tmp_path / "companion.db",
        environment="test",
        ocr_client=SyntheticOcr(),
        lab_extractor=SyntheticChineseLabExtractor(),
    )
    with TestClient(app) as local_client:
        entry_headers = auth_headers(local_client, "site-a-investigator@example.test")
        source_response = local_client.post(
            "/api/source-files/upload",
            headers=entry_headers,
            files={"file": ("synthetic-chinese-table.png", SYNTHETIC_PNG_BYTES, "image/png")},
            data={"synthetic_attestation": "true"},
        )
        assert source_response.status_code == 201
        extracted = local_client.post(
            f"/api/source-files/{source_response.json()['id']}/local-ocr-extract",
            headers=entry_headers,
            json={"edc_subject_ref": "SUBJ001", "edc_event_ref": "WEEK_0"},
        )

        assert extracted.status_code == 201
        assert [(row["field_code"], row["proposed_value"], row["unit"]) for row in extracted.json()] == [
            ("WBC", "4.50", None),
            ("ALT", "31", "U/L"),
        ]
        assert all("structured-chinese-v0.1" in row["ocr_engine_version"] for row in extracted.json())


def test_manual_candidate_creation_cannot_bypass_the_versioned_crf_mapping(client: TestClient) -> None:
    entry_headers = auth_headers(client, "site-a-investigator@example.test")
    source_response = client.post(
        "/api/source-files",
        headers=entry_headers,
        json={
            "source_filename": "synthetic_lab_report.png",
            "sha256": "c" * 64,
            "mime_type": "image/png",
            "storage_key": "synthetic/site-a/mapping-guard.png",
        },
    )
    assert source_response.status_code == 201

    response = client.post(
        "/api/candidates",
        headers=entry_headers,
        json={
            "source_file_id": source_response.json()["id"],
            "edc_subject_ref": "SUBJ001",
            "edc_event_ref": "WEEK_0",
            "field_code": "BADLAB",
            "proposed_value": "32",
            "unit": "U/L",
            "ocr_engine_version": "synthetic-manual-entry",
            "kimi_model": "not_used",
            "schema_version": "synthetic-test",
            "confidence": 0.87,
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "field_not_in_crf_mapping"


def test_kimi_extract_endpoint_requires_a_key_before_outbound_use(client: TestClient) -> None:
    entry_headers = auth_headers(client, "site-a-investigator@example.test")
    source_response = client.post(
        "/api/source-files",
        headers=entry_headers,
        json={
            "source_filename": "synthetic_lab_report.png",
            "sha256": "b" * 64,
            "mime_type": "image/png",
            "storage_key": "synthetic/site-a/kimi-synthetic-lab-report.png",
        },
    )
    assert source_response.status_code == 201

    response = client.post(
        f"/api/source-files/{source_response.json()['id']}/kimi-extract",
        headers=entry_headers,
        json={
            "edc_subject_ref": "SUBJ001",
            "edc_event_ref": "WEEK_0",
            "deidentified_ocr_text": "ALT: 31 U/L",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "confirmed_deidentified_source_required"


def test_hybrid_extraction_sends_only_confirmed_derivative_and_surfaces_ocr_kimi_conflict(
    tmp_path: Path,
) -> None:
    class SyntheticDeidentifier:
        def redact(self, image_path: Path, output_path: Path):
            assert image_path.read_bytes() == SYNTHETIC_PNG_BYTES
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"confirmed-deidentified-image")
            return type(
                "SyntheticRedactionResult",
                (),
                {"detected_marker_codes": ("patient_name",), "engine_version": "synthetic-redactor-1"},
            )()

    class SyntheticOcr:
        def extract(self, image_path: Path):
            assert image_path.read_bytes() == b"confirmed-deidentified-image"
            return type(
                "SyntheticOcrResult",
                (),
                {"text": "ALT: 3.1 U/L", "engine_version": "synthetic-tesseract-5.5"},
            )()

        def extract_tsv(self, image_path: Path):
            assert image_path.read_bytes() == b"confirmed-deidentified-image"
            return type(
                "SyntheticTsvResult",
                (),
                {"tsv": "text\tleft\ttop\nALT\t10\t20\n3.1\t40\t20", "engine_version": "synthetic-tesseract-5.5"},
            )()

    class SyntheticKimi:
        enabled = True
        settings = type("SyntheticSettings", (), {"model": "kimi-k3"})()

        def __init__(self) -> None:
            self.received: dict[str, object] | None = None

        def extract_candidates(self, deidentified_ocr_text: str, **kwargs):
            self.received = {"deidentified_ocr_text": deidentified_ocr_text, **kwargs}
            return [
                KimiCandidate(
                    field_code="ALT",
                    proposed_value="31",
                    unit="U/L",
                    confidence=0.8,
                    evidence_text="ALT 31 U/L",
                    status="read",
                )
            ]

    kimi = SyntheticKimi()
    app = create_app(
        database_path=tmp_path / "hybrid.db",
        environment="test",
        ocr_client=SyntheticOcr(),
        deidentifier=SyntheticDeidentifier(),
        kimi_client=kimi,
    )
    with TestClient(app) as local_client:
        admin_headers = auth_headers(local_client, "central-data-manager@example.test")
        header_update = local_client.put(
            "/api/admin/field-dictionary/WEEK_0/ALT",
            headers=admin_headers,
            json={"display_header": "丙氨酸氨基转移酶（管理员标签）"},
        )
        assert header_update.status_code == 200
        headers = auth_headers(local_client, "site-a-investigator@example.test")
        uploaded = local_client.post(
            "/api/source-files/upload",
            headers=headers,
            files={"file": ("identified.png", SYNTHETIC_PNG_BYTES, "image/png")},
            data={"synthetic_attestation": "true"},
        )
        assert uploaded.status_code == 201
        draft = local_client.post(
            f"/api/source-files/{uploaded.json()['id']}/deidentification-drafts",
            headers=headers,
        )
        assert draft.status_code == 201
        derivative_id = draft.json()["derivative_source_file"]["id"]
        confirmed = local_client.post(
            f"/api/deidentification-drafts/{draft.json()['id']}/confirm",
            headers=headers,
            json={"human_review_attestation": True},
        )
        assert confirmed.status_code == 200

        extracted = local_client.post(
            f"/api/source-files/{derivative_id}/hybrid-extract",
            headers=headers,
            json={"edc_subject_ref": "SUBJ001", "edc_event_ref": "WEEK_0"},
        )

        assert extracted.status_code == 201
        assert len(extracted.json()) == 1
        candidate = extracted.json()[0]
        assert candidate["field_code"] == "ALT"
        assert candidate["proposed_value"] == "31"
        assert candidate["local_ocr_value"] == "3.1"
        assert candidate["local_ocr_unit"] == "U/L"
        assert candidate["extraction_agreement"] == "conflict"
        assert candidate["evidence_text"] == "ALT 31 U/L"
        assert candidate["kimi_model"] == "kimi-k3"
        assert candidate["confidence"] == 0.4
        assert kimi.received is not None
        assert kimi.received["image_bytes"] == b"confirmed-deidentified-image"
        assert kimi.received["media_type"] == "image/png"
        assert kimi.received["ocr_evidence"] == "text\tleft\ttop\nALT\t10\t20\n3.1\t40\t20"
        assert kimi.received["event_ref"] == "WEEK_0"
        assert kimi.received["field_dictionary"]["ALT"] == "丙氨酸氨基转移酶（管理员标签）"

        audit_response = local_client.get(f"/api/candidates/{candidate['id']}/audit", headers=headers)
        assert audit_response.status_code == 200
        assert audit_response.json()[-1]["details"]["mode"] == "hybrid_ocr_kimi"
        assert audit_response.json()[-1]["details"]["extraction_agreement"] == "conflict"


def test_health_reports_when_kimi_is_ready_for_confirmed_deidentified_derivatives(tmp_path: Path) -> None:
    class ReadySyntheticKimi:
        enabled = True
        ready = True
        settings = type("SyntheticSettings", (), {"model": "kimi-k3"})()

    app = create_app(
        database_path=tmp_path / "kimi-ready.db",
        environment="test",
        kimi_client=ReadySyntheticKimi(),
    )

    with TestClient(app) as local_client:
        health = local_client.get("/api/health")

    assert health.status_code == 200
    assert health.json()["kimi_integration"] == "ready"
    assert health.json()["model_provider"] == "kimi"
    assert health.json()["kimi_model"] == "kimi-k3"
    assert health.json()["kimi_data_boundary"] == "confirmed_deidentified_derivative_only"


def test_health_reports_key_required_for_the_default_kimi_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODEL_ENABLED", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_API_KEY_FILE", raising=False)
    monkeypatch.delenv("KIMI_ENABLED", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.setenv("KIMI_API_KEY_FILE", str(tmp_path / "missing-kimi-key.txt"))

    local_client = TestClient(create_app(database_path=tmp_path / "kimi-key-required.db", environment="test"))

    health = local_client.get("/api/health")

    assert health.status_code == 200
    assert health.json()["kimi_integration"] == "key_required"
    assert health.json()["kimi_default_enabled"] is True


def test_site_can_export_reviewed_package_and_central_manager_can_import_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site_client = TestClient(create_app(database_path=tmp_path / "site.db", environment="test"))
    site_headers = auth_headers(site_client, "site-a-investigator@example.test")
    candidate = create_candidate(site_client, site_headers, field_code="ALT", proposed_value="31")
    review = site_client.post(
        f"/api/candidates/{candidate['id']}/review",
        headers=site_headers,
        json={"decision": "accept"},
    )
    assert review.status_code == 200

    package_response = site_client.post(
        "/api/exports/reviewed-recognition-package.json",
        headers=site_headers,
        data={"package_passphrase": "centre-passphrase-2026"},
    )
    assert package_response.status_code == 200
    assert package_response.headers["content-type"].startswith("application/json")
    assert package_response.headers["x-offline-package-sha256"]

    central_client = TestClient(create_app(database_path=tmp_path / "central.db", environment="test"))
    central_headers = auth_headers(central_client, "central-data-manager@example.test")
    imported = central_client.post(
        "/api/imports/reviewed-package",
        headers=central_headers,
        files={
            "file": (
                "reviewed-package.json",
                package_response.content,
                "application/json",
            )
        },
        data={"package_passphrase": "centre-passphrase-2026"},
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["created_count"] == 1
    assert imported.json()["authority_submission"] == "not_attempted"
    imported_candidates = central_client.get("/api/candidates", headers=central_headers)
    assert imported_candidates.status_code == 200
    imported_source_id = imported_candidates.json()[0]["source_file_id"]
    assert (tmp_path / "offline_packages" / "SITE_A" / f"{imported_source_id}.json").is_file()

    # Simulate both requests passing a stale pre-check. The final atomic claim
    # remains authoritative and must return the stable duplicate response.
    monkeypatch.setattr(
        central_client.app.state.package_import_repository,
        "find_receipt",
        lambda **_kwargs: None,
    )

    duplicate = central_client.post(
        "/api/imports/reviewed-package",
        headers=central_headers,
        files={"file": ("reviewed-package.json", package_response.content, "application/json")},
        data={"package_passphrase": "centre-passphrase-2026"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "offline_package_already_imported"


def test_central_manager_can_batch_import_multiple_encrypted_centre_packages_and_read_logs(tmp_path: Path) -> None:
    package_bytes: list[bytes] = []
    for centre, username in (("SITE_A", "site-a-investigator@example.test"), ("SITE_B", "site-b-investigator@example.test")):
        site_client = TestClient(create_app(database_path=tmp_path / f"{centre}.db", environment="test"))
        headers = auth_headers(site_client, username)
        candidate = create_candidate(site_client, headers, field_code="ALT", proposed_value="31")
        assert site_client.post(
            f"/api/candidates/{candidate['id']}/review", headers=headers, json={"decision": "accept"}
        ).status_code == 200
        exported = site_client.post(
            "/api/exports/reviewed-recognition-package.json",
            headers=headers,
            data={"package_passphrase": "centre-passphrase-2026"},
        )
        assert exported.status_code == 200
        package_bytes.append(exported.content)

    central_client = TestClient(create_app(database_path=tmp_path / "central-batch.db", environment="test"))
    central_headers = auth_headers(central_client, "central-data-manager@example.test")
    imported = central_client.post(
        "/api/imports/reviewed-packages",
        headers=central_headers,
        files=[
            ("files", ("site-a.enc.json", package_bytes[0], "application/json")),
            ("files", ("site-b.enc.json", package_bytes[1], "application/json")),
        ],
        data={"package_passphrase": "centre-passphrase-2026"},
    )

    assert imported.status_code == 201, imported.text
    assert imported.json()["imported_count"] == 2
    logs = central_client.get("/api/imports/reviewed-package-logs", headers=central_headers)
    assert logs.status_code == 200
    assert {item["result"] for item in logs.json()} == {"imported"}


def test_user_can_disable_kimi_for_a_hybrid_extraction_batch(tmp_path: Path) -> None:
    class SyntheticDeidentifier:
        def redact(self, _image_path: Path, output_path: Path):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"confirmed-deidentified-image")
            return type(
                "SyntheticRedactionResult",
                (),
                {"detected_marker_codes": (), "engine_version": "synthetic-redactor-1"},
            )()

    class SyntheticOcr:
        def extract(self, image_path: Path):
            assert image_path.read_bytes() == b"confirmed-deidentified-image"
            return type(
                "SyntheticOcrResult",
                (),
                {"text": "ALT: 31 U/L", "engine_version": "synthetic-tesseract-5.5"},
            )()

    class ForbiddenKimi:
        enabled = True
        ready = True
        settings = type("SyntheticSettings", (), {"model": "kimi-k3"})()

        def extract_candidates(self, _text: str, **_kwargs):
            raise AssertionError("Kimi must not be called when the user disables it")

    app = create_app(
        database_path=tmp_path / "hybrid-user-disabled.db",
        environment="test",
        ocr_client=SyntheticOcr(),
        deidentifier=SyntheticDeidentifier(),
        kimi_client=ForbiddenKimi(),
    )
    with TestClient(app) as local_client:
        headers = auth_headers(local_client, "site-a-investigator@example.test")
        uploaded = local_client.post(
            "/api/source-files/upload",
            headers=headers,
            files={"file": ("identified.png", SYNTHETIC_PNG_BYTES, "image/png")},
            data={"synthetic_attestation": "true"},
        )
        draft = local_client.post(
            f"/api/source-files/{uploaded.json()['id']}/deidentification-drafts",
            headers=headers,
        ).json()
        confirmed = local_client.post(
            f"/api/deidentification-drafts/{draft['id']}/confirm",
            headers=headers,
            json={"human_review_attestation": True},
        )
        assert confirmed.status_code == 200

        extracted = local_client.post(
            f"/api/source-files/{draft['derivative_source_file']['id']}/hybrid-extract",
            headers=headers,
            json={
                "edc_subject_ref": "SUBJ001",
                "edc_event_ref": "WEEK_0",
                "use_kimi": False,
            },
        )

        assert extracted.status_code == 201
        candidate = extracted.json()[0]
        assert candidate["proposed_value"] == "31"
        assert candidate["extraction_agreement"] == "local_only"
        assert candidate["kimi_model"] == "not_used_user_disabled"
        audit_response = local_client.get(f"/api/candidates/{candidate['id']}/audit", headers=headers)
        assert audit_response.json()[-1]["details"]["kimi_requested"] is False


def test_recognition_job_keeps_local_candidates_and_ids_when_kimi_fails(
    tmp_path: Path,
) -> None:
    class SyntheticDeidentifier:
        def redact(self, _image_path: Path, output_path: Path):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"confirmed-deidentified-image")
            return type(
                "SyntheticRedactionResult",
                (),
                {"detected_marker_codes": (), "engine_version": "synthetic-redactor-1"},
            )()

    class SyntheticOcr:
        def extract(self, image_path: Path):
            assert image_path.read_bytes() == b"confirmed-deidentified-image"
            return type(
                "SyntheticOcrResult",
                (),
                {"text": "ALT: 31 U/L", "engine_version": "synthetic-tesseract-5.5"},
            )()

    class FailingSyntheticKimi:
        enabled = True
        ready = True
        settings = type("SyntheticSettings", (), {"model": "kimi-k3"})()

        def extract_candidates(self, _text: str, **_kwargs):
            raise KimiServiceError("synthetic provider outage with no secret")

    app = create_app(
        database_path=tmp_path / "hybrid-fallback.db",
        environment="test",
        ocr_client=SyntheticOcr(),
        deidentifier=SyntheticDeidentifier(),
        kimi_client=FailingSyntheticKimi(),
    )
    with TestClient(app) as local_client:
        headers = auth_headers(local_client, "site-a-investigator@example.test")
        uploaded = local_client.post(
            "/api/source-files/upload",
            headers=headers,
            files={"file": ("identified.png", SYNTHETIC_PNG_BYTES, "image/png")},
            data={"synthetic_attestation": "true"},
        )
        draft = local_client.post(
            f"/api/source-files/{uploaded.json()['id']}/deidentification-drafts",
            headers=headers,
        ).json()
        local_client.post(
            f"/api/deidentification-drafts/{draft['id']}/confirm",
            headers=headers,
            json={"human_review_attestation": True},
        )

        recognition_job = local_client.post(
            "/api/recognition-jobs",
            headers=headers,
            json={
                "items": [
                    {
                        "source_file_id": uploaded.json()["id"],
                        "edc_subject_ref": "SUBJ001",
                        "edc_event_ref": "WEEK_0",
                        "field_codes": ["ALT"],
                        "use_kimi": True,
                    }
                ]
            },
        )
        assert recognition_job.status_code == 201
        completed_job = local_client.post(
            f"/api/recognition-jobs/{recognition_job.json()['id']}/run",
            headers=headers,
        )

        assert completed_job.status_code == 200
        assert completed_job.json()["status"] == "succeeded"
        candidate_ids = completed_job.json()["items"][0]["candidate_ids"]
        assert len(candidate_ids) == 1
        candidate = next(
            item
            for item in local_client.get("/api/candidates", headers=headers).json()
            if item["id"] == candidate_ids[0]
        )
        assert candidate["proposed_value"] == "31"
        assert candidate["extraction_agreement"] == "local_fallback"
        assert candidate["kimi_model"] == "kimi-k3"
        audit_response = local_client.get(f"/api/candidates/{candidate['id']}/audit", headers=headers)
        assert audit_response.json()[-1]["details"]["kimi_error"] == "KimiServiceError"
        assert "provider outage" not in json.dumps(audit_response.json())
        quality_response = local_client.get(f"/api/candidates/{candidate['id']}/quality", headers=headers)
        assert quality_response.status_code == 200
        assert quality_response.json()["status"] != "BLOCK"
        bulk_accept = local_client.post(
            "/api/candidate-reviews/bulk-accept",
            headers=headers,
            json={"candidate_ids": candidate_ids},
        )
        assert bulk_accept.status_code == 200
        assert bulk_accept.json()["accepted_count"] == 1


def test_extraction_evidence_is_returned_and_pdf_inspection_is_non_mutating(tmp_path: Path) -> None:
    class SyntheticPulmonaryParser:
        def extract(self, _pdf_path: Path):
            candidate = lambda code, value: type(
                "PulmonaryCandidate",
                (),
                {
                    "field_code": code,
                    "proposed_value": value,
                    "unit": "L",
                    "evidence_text": f"PDF row {code}; selected=measured",
                },
            )()
            return type(
                "PulmonaryExtraction",
                (),
                {
                    "candidates": (candidate("PFT_FEV1", "2.45"),),
                    "engine_version": "synthetic-pdf-parser-v1",
                },
            )()

    app = create_app(
        database_path=tmp_path / "evidence.db",
        environment="test",
        pulmonary_parser=SyntheticPulmonaryParser(),
    )
    with TestClient(app) as local_client:
        headers = auth_headers(local_client, "site-a-investigator@example.test")
        uploaded = local_client.post(
            "/api/source-files/upload",
            headers=headers,
            files={"file": ("synthetic.pdf", b"%PDF-1.7\n%%EOF", "application/pdf")},
            data={"synthetic_attestation": "true"},
        )
        assert uploaded.status_code == 201
        source_id = uploaded.json()["id"]
        inspection = local_client.get(f"/api/source-files/{source_id}/pdf-inspection", headers=headers)
        assert inspection.status_code == 200
        assert inspection.json()["classification"] == "pdf_invalid"
        extracted = local_client.post(
            f"/api/source-files/{source_id}/pulmonary-function-extract",
            headers=headers,
            json={"edc_subject_ref": "SUBJ001", "edc_event_ref": "WEEK_0"},
        )
        assert extracted.status_code == 201
        candidate = extracted.json()[0]
        assert candidate["extraction_run_id"]
        assert candidate["extraction_evidence"]["engine"] == "local_pdf_pulmonary"
        run = local_client.get(
            f"/api/extraction-runs/{candidate['extraction_run_id']}",
            headers=headers,
        )
        assert run.status_code == 200
        assert run.json()["evidence"]["contract_version"] == "extraction-evidence-v1"
        repeated = local_client.post(
            f"/api/source-files/{source_id}/pulmonary-function-extract",
            headers=headers,
            json={"edc_subject_ref": "SUBJ001", "edc_event_ref": "WEEK_0"},
        )
        assert repeated.status_code == 200
        assert repeated.json()[0]["id"] == candidate["id"]
