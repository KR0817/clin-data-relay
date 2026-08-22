from pathlib import Path
import hashlib

from fastapi.testclient import TestClient

from app.edc_adapter import EdcReadbackResult, EdcSubmissionResult
from app.main import create_app


def auth_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": "demo-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_candidate(
    client: TestClient,
    headers: dict[str, str],
    *,
    field_code: str = "ALT",
    value: str = "32",
    unit: str | None = "U/L",
) -> dict[str, object]:
    source = client.post(
        "/api/source-files",
        headers=headers,
        json={
            "source_filename": "synthetic.png",
            "sha256": "a" * 64,
            "mime_type": "image/png",
            "storage_key": "synthetic/operations.png",
        },
    )
    assert source.status_code == 201
    response = client.post(
        "/api/candidates",
        headers=headers,
        json={
            "source_file_id": source.json()["id"],
            "edc_subject_ref": "SUBJ900",
            "edc_event_ref": "WEEK_0",
            "field_code": field_code,
            "proposed_value": value,
            "unit": unit,
            "ocr_engine_version": "synthetic-ocr",
            "kimi_model": "not-used",
            "schema_version": "synthetic-v1",
            "confidence": 0.9,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_blocking_quality_finding_prevents_candidate_acceptance(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "quality.db", environment="test")
    with TestClient(app) as client:
        headers = auth_headers(client, "site-a-investigator@example.test")
        candidate = create_candidate(
            client,
            headers,
            field_code="WBC",
            value="999",
            unit="10^9/L",
        )

        assessment = client.get(f"/api/candidates/{candidate['id']}/quality", headers=headers)
        accepted = client.post(
            f"/api/candidates/{candidate['id']}/review",
            headers=headers,
            json={"decision": "accept"},
        )

        assert assessment.status_code == 200
        assert assessment.json()["status"] == "BLOCK"
        assert assessment.json()["rule_version"] == "clinical-quality-v1"
        assert [finding["code"] for finding in assessment.json()["findings"]] == ["above_block_max"]
        assert accepted.status_code == 409
        assert accepted.json()["detail"] == "quality_blocked"


def test_companion_data_issue_must_be_resolved_before_transfer(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "issues.db", environment="test")
    with TestClient(app) as client:
        site_headers = auth_headers(client, "site-a-investigator@example.test")
        central_headers = auth_headers(client, "central-data-manager@example.test")
        site_b_headers = auth_headers(client, "site-b-investigator@example.test")
        candidate = create_candidate(client, site_headers)
        reviewed = client.post(
            f"/api/candidates/{candidate['id']}/review",
            headers=site_headers,
            json={"decision": "accept"},
        )
        assert reviewed.status_code == 200

        opened = client.post(
            f"/api/candidates/{candidate['id']}/data-issues",
            headers=central_headers,
            json={"message": "Please verify the source unit."},
        )
        assert opened.status_code == 201
        issue_id = opened.json()["id"]
        assert opened.json()["status"] == "open"
        assert client.get("/api/data-issues", headers=site_b_headers).json() == []

        blocked = client.post(f"/api/candidates/{candidate['id']}/transfers", headers=site_headers)
        assert blocked.status_code == 409
        assert blocked.json()["detail"] == "open_data_issue_blocks_transfer"

        answered = client.post(
            f"/api/data-issues/{issue_id}/answer",
            headers=site_headers,
            json={"message": "The source report confirms U/L."},
        )
        assert answered.status_code == 200
        assert answered.json()["status"] == "answered"
        still_blocked = client.post(f"/api/candidates/{candidate['id']}/transfers", headers=site_headers)
        assert still_blocked.status_code == 409

        resolved = client.post(
            f"/api/data-issues/{issue_id}/resolve",
            headers=central_headers,
            json={"message": "Source evidence accepted."},
        )
        assert resolved.status_code == 200
        assert resolved.json()["status"] == "resolved"
        transfer = client.post(f"/api/candidates/{candidate['id']}/transfers", headers=site_headers)
        assert transfer.status_code == 201


def test_successful_transfer_is_automatically_verified_by_authority_readback(tmp_path: Path) -> None:
    class MatchingAdapter:
        mode = "qualified_test"
        target_kind = "libreclinica"

        def readiness(self) -> dict[str, object]:
            return {"status": "ready", "readback": "ready"}

        def submit(self, transfer_package: dict[str, object], *, idempotency_key: str) -> EdcSubmissionResult:
            del transfer_package, idempotency_key
            return EdcSubmissionResult(external_reference="AUTH/1", response_sha256="b" * 64)

        def read_value(self, transfer_package: dict[str, object]) -> EdcReadbackResult:
            assert transfer_package["value"]["final_value"] == "32"
            return EdcReadbackResult(status="matched", observed_value="32", response_sha256="c" * 64)

    app = create_app(
        database_path=tmp_path / "readback.db",
        environment="test",
        edc_adapter=MatchingAdapter(),
    )
    with TestClient(app) as client:
        headers = auth_headers(client, "site-a-investigator@example.test")
        candidate = create_candidate(client, headers)
        assert client.post(
            f"/api/candidates/{candidate['id']}/review",
            headers=headers,
            json={"decision": "accept"},
        ).status_code == 200
        transfer = client.post(f"/api/candidates/{candidate['id']}/transfers", headers=headers).json()

        submitted = client.post(f"/api/transfers/{transfer['id']}/submit", headers=headers)

        assert submitted.status_code == 200
        assert submitted.json()["status"] == "submitted"
        assert submitted.json()["readback_status"] == "verified"
        assert submitted.json()["readback_attempt_count"] == 1
        assert submitted.json()["readback_checked_at"] is not None


def test_readback_mismatch_is_visible_without_rewriting_submitted_transfer(tmp_path: Path) -> None:
    class MismatchAdapter:
        mode = "qualified_test"
        target_kind = "libreclinica"

        def readiness(self) -> dict[str, object]:
            return {"status": "ready", "readback": "ready"}

        def submit(self, transfer_package: dict[str, object], *, idempotency_key: str) -> EdcSubmissionResult:
            del transfer_package, idempotency_key
            return EdcSubmissionResult(external_reference="AUTH/2", response_sha256="d" * 64)

        def read_value(self, transfer_package: dict[str, object]) -> EdcReadbackResult:
            del transfer_package
            return EdcReadbackResult(status="mismatch", observed_value="31", response_sha256="e" * 64)

    app = create_app(
        database_path=tmp_path / "mismatch.db",
        environment="test",
        edc_adapter=MismatchAdapter(),
    )
    with TestClient(app) as client:
        headers = auth_headers(client, "site-a-investigator@example.test")
        candidate = create_candidate(client, headers)
        client.post(
            f"/api/candidates/{candidate['id']}/review",
            headers=headers,
            json={"decision": "accept"},
        )
        transfer = client.post(f"/api/candidates/{candidate['id']}/transfers", headers=headers).json()

        submitted = client.post(f"/api/transfers/{transfer['id']}/submit", headers=headers)
        rerun = client.post(f"/api/transfers/{transfer['id']}/readback", headers=headers)

        assert submitted.status_code == 200
        assert submitted.json()["status"] == "submitted"
        assert submitted.json()["readback_status"] == "mismatch"
        assert rerun.status_code == 200
        assert rerun.json()["readback_status"] == "mismatch"
        assert rerun.json()["readback_attempt_count"] == 2


def test_companion_transfer_hold_blocks_review_until_released(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "holds.db", environment="test")
    with TestClient(app) as client:
        site_headers = auth_headers(client, "site-a-investigator@example.test")
        central_headers = auth_headers(client, "central-data-manager@example.test")
        candidate = create_candidate(client, site_headers)

        held = client.post(
            "/api/transfer-holds",
            headers=central_headers,
            json={
                "scope": "visit",
                "centre_code": "SITE_A",
                "subject_ref": "SUBJ900",
                "event_ref": "WEEK_0",
                "action": "held",
                "reason": "Synthetic data-management review.",
            },
        )
        blocked = client.post(
            f"/api/candidates/{candidate['id']}/review",
            headers=site_headers,
            json={"decision": "accept"},
        )

        assert held.status_code == 201
        assert held.json()["effective"] is True
        assert blocked.status_code == 409
        assert blocked.json()["detail"] == "transfer_hold_active"

        released = client.post(
            "/api/transfer-holds",
            headers=central_headers,
            json={
                "scope": "visit",
                "centre_code": "SITE_A",
                "subject_ref": "SUBJ900",
                "event_ref": "WEEK_0",
                "action": "released",
                "reason": "Synthetic review completed.",
            },
        )
        accepted = client.post(
            f"/api/candidates/{candidate['id']}/review",
            headers=site_headers,
            json={"decision": "accept"},
        )

        assert released.status_code == 201
        assert released.json()["effective"] is False
        assert accepted.status_code == 200


def test_site_investigator_can_record_non_signature_visit_attestation(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "attestation.db", environment="test")
    with TestClient(app) as client:
        site_headers = auth_headers(client, "site-a-investigator@example.test")
        site_b_headers = auth_headers(client, "site-b-investigator@example.test")
        candidate = create_candidate(client, site_headers)
        assert client.post(
            f"/api/candidates/{candidate['id']}/review",
            headers=site_headers,
            json={"decision": "accept"},
        ).status_code == 200

        attested = client.post(
            "/api/visits/SITE_A/SUBJ900/WEEK_0/attest",
            headers=site_headers,
            json={"message": "Synthetic source and candidate review completed."},
        )
        hidden = client.get(
            "/api/visits/SITE_A/SUBJ900/WEEK_0/attestations",
            headers=site_b_headers,
        )

        assert attested.status_code == 201
        assert attested.json()["attestation_kind"] == "pre_transfer_not_electronic_signature"
        assert attested.json()["candidate_count"] == 1
        assert attested.json()["valid"] is True
        assert hidden.status_code == 404

        second_candidate = create_candidate(client, site_headers, field_code="AST", value="28")
        assert client.post(
            f"/api/candidates/{second_candidate['id']}/review",
            headers=site_headers,
            json={"decision": "accept"},
        ).status_code == 200
        history = client.get(
            "/api/visits/SITE_A/SUBJ900/WEEK_0/attestations",
            headers=site_headers,
        )

        assert history.status_code == 200
        assert history.json()[0]["valid"] is False
        assert history.json()[0]["invalidation_reason"] == "candidate_state_changed"


def test_central_manager_controls_read_only_monitor_account_lifecycle(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "accounts.db", environment="test")
    with TestClient(app) as client:
        central_headers = auth_headers(client, "central-data-manager@example.test")
        site_headers = auth_headers(client, "site-a-investigator@example.test")
        candidate = create_candidate(client, site_headers)

        created = client.post(
            "/api/admin/users",
            headers=central_headers,
            json={"username": "monitor@example.test", "role": "monitor"},
        )
        assert created.status_code == 201
        bootstrap_password = created.json()["bootstrap_password"]
        login = client.post(
            "/api/auth/login",
            json={"username": "monitor@example.test", "password": bootstrap_password},
        )
        assert login.status_code == 200
        monitor_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        listed = client.get("/api/candidates", headers=monitor_headers)
        forbidden_review = client.post(
            f"/api/candidates/{candidate['id']}/review",
            headers=monitor_headers,
            json={"decision": "accept"},
        )
        forbidden_export = client.get("/api/exports/submitted-data.xlsx", headers=monitor_headers)
        forbidden_source_write = client.post(
            "/api/source-files",
            headers=monitor_headers,
            json={
                "source_filename": "must-not-write.png",
                "sha256": "b" * 64,
                "mime_type": "image/png",
                "storage_key": "synthetic/must-not-write.png",
                "centre_code": "SITE_A",
            },
        )

        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [candidate["id"]]
        assert forbidden_review.status_code == 403
        assert forbidden_export.status_code == 403
        assert forbidden_source_write.status_code == 403
        assert forbidden_source_write.json()["detail"] == "read_only_role"

        deactivated = client.post(
            f"/api/admin/users/{created.json()['id']}/deactivate",
            headers=central_headers,
        )
        assert deactivated.status_code == 200
        assert deactivated.json()["active"] is False
        assert client.get("/api/candidates", headers=monitor_headers).status_code == 401

        reactivated = client.post(
            f"/api/admin/users/{created.json()['id']}/reactivate",
            headers=central_headers,
        )
        assert reactivated.status_code == 200
        assert reactivated.json()["active"] is True
        assert client.post(
            "/api/auth/login",
            json={"username": "monitor@example.test", "password": bootstrap_password},
        ).status_code == 200


def test_central_manager_generates_unique_centre_accounts_and_principal_can_view_central_scope(tmp_path: Path) -> None:
    client = TestClient(create_app(database_path=tmp_path / "centre-accounts.db", environment="test"))
    central_headers = auth_headers(client, "central-data-manager@example.test")

    created = client.post(
        "/api/admin/centre-accounts",
        headers=central_headers,
        json={
            "accounts": [
                {"centre_code": "SITE_C", "username": "researcher-c@example.test"},
                {"centre_code": "SITE_D", "username": "researcher-d@example.test"},
            ]
        },
    )

    assert created.status_code == 201
    assert {item["centre_code"] for item in created.json()["accounts"]} == {"SITE_C", "SITE_D"}
    assert all(len(item["bootstrap_password"]) >= 20 for item in created.json()["accounts"])

    principal = auth_headers(client, "principal-investigator@example.test")
    assert client.get("/api/candidates", headers=principal).status_code == 200
def test_audit_search_is_filterable_and_site_scoped(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "audit-search.db", environment="test")
    with TestClient(app) as client:
        site_a_headers = auth_headers(client, "site-a-investigator@example.test")
        site_b_headers = auth_headers(client, "site-b-investigator@example.test")
        central_headers = auth_headers(client, "central-data-manager@example.test")
        create_candidate(client, site_a_headers)
        create_candidate(client, site_b_headers)

        site_results = client.get(
            "/api/audit-events?event_type=candidate_created",
            headers=site_a_headers,
        )
        central_results = client.get(
            "/api/audit-events?event_type=candidate_created&limit=10",
            headers=central_headers,
        )

        assert site_results.status_code == 200
        assert {event["centre_code"] for event in site_results.json()["events"]} == {"SITE_A"}
        assert central_results.status_code == 200
        assert {event["centre_code"] for event in central_results.json()["events"]} == {"SITE_A", "SITE_B"}
        assert central_results.json()["total"] == 2


def test_structured_csv_enters_candidate_review_with_quality_and_duplicate_controls(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "structured-import.db", environment="test")
    csv_bytes = (
        "subject_ref,event_ref,field_code,value,unit\n"
        "SUBJ910,WEEK_0,ALT,32,U/L\n"
        "SUBJ910,WEEK_0,WBC,999,10^9/L\n"
    ).encode("utf-8")
    with TestClient(app) as client:
        headers = auth_headers(client, "site-a-investigator@example.test")

        imported = client.post(
            "/api/imports/structured-csv",
            headers=headers,
            files={"file": ("synthetic-lis.csv", csv_bytes, "text/csv")},
            data={"synthetic_attestation": "true"},
        )
        replayed = client.post(
            "/api/imports/structured-csv",
            headers=headers,
            files={"file": ("synthetic-lis.csv", csv_bytes, "text/csv")},
            data={"synthetic_attestation": "true"},
        )

        assert imported.status_code == 201
        assert imported.json()["created_count"] == 2
        assert imported.json()["blocked_count"] == 1
        assert imported.json()["duplicate_count"] == 0
        assert {row["origin_type"] for row in imported.json()["candidates"]} == {"structured_csv"}
        blocked_candidate = next(
            row for row in imported.json()["candidates"] if row["field_code"] == "WBC"
        )
        quality = client.get(
            f"/api/candidates/{blocked_candidate['id']}/quality",
            headers=headers,
        )
        assert quality.json()["status"] == "BLOCK"

        assert replayed.status_code == 201
        assert replayed.json()["created_count"] == 0
        assert replayed.json()["duplicate_count"] == 2


def test_structured_csv_rejects_missing_required_headers_without_partial_import(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "invalid-structured-import.db", environment="test")
    with TestClient(app) as client:
        headers = auth_headers(client, "site-a-investigator@example.test")
        response = client.post(
            "/api/imports/structured-csv",
            headers=headers,
            files={"file": ("invalid.csv", b"field_code,value\nALT,32\n", "text/csv")},
            data={"synthetic_attestation": "true"},
        )

        assert response.status_code == 422
        assert response.json()["detail"] == "structured_import_invalid_schema"
        assert client.get("/api/candidates", headers=headers).json() == []


def test_structured_csv_reports_and_ignores_unknown_optional_columns(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "unknown-column.db", environment="test")
    with TestClient(app) as client:
        headers = auth_headers(client, "site-a-investigator@example.test")
        response = client.post(
            "/api/imports/structured-csv",
            headers=headers,
            files={
                "file": (
                    "extra.csv",
                    b"subject_ref,event_ref,field_code,value,unit,device_note\nSUBJ920,WEEK_0,K,4.1,mmol/L,synthetic\n",
                    "text/csv",
                )
            },
            data={"synthetic_attestation": "true"},
        )

        assert response.status_code == 201
        assert response.json()["created_count"] == 1
        assert response.json()["ignored_headers"] == ["device_note"]
        assert response.json()["candidates"][0]["field_code"] == "K"


def test_readback_mismatch_creates_one_actionable_task_and_can_be_completed(tmp_path: Path) -> None:
    class MismatchAdapter:
        mode = "qualified_test"
        target_kind = "libreclinica"

        def readiness(self) -> dict[str, object]:
            return {"status": "ready", "readback": "ready"}

        def submit(self, transfer_package: dict[str, object], *, idempotency_key: str) -> EdcSubmissionResult:
            del transfer_package, idempotency_key
            return EdcSubmissionResult(external_reference="AUTH/TASK", response_sha256="f" * 64)

        def read_value(self, transfer_package: dict[str, object]) -> EdcReadbackResult:
            del transfer_package
            return EdcReadbackResult(status="mismatch", observed_value="31", response_sha256="e" * 64)

    app = create_app(
        database_path=tmp_path / "tasks.db",
        environment="test",
        edc_adapter=MismatchAdapter(),
    )
    with TestClient(app) as client:
        site_headers = auth_headers(client, "site-a-investigator@example.test")
        central_headers = auth_headers(client, "central-data-manager@example.test")
        candidate = create_candidate(client, site_headers)
        client.post(
            f"/api/candidates/{candidate['id']}/review",
            headers=site_headers,
            json={"decision": "accept"},
        )
        transfer = client.post(f"/api/candidates/{candidate['id']}/transfers", headers=site_headers).json()
        client.post(f"/api/transfers/{transfer['id']}/submit", headers=site_headers)
        client.post(f"/api/transfers/{transfer['id']}/readback", headers=central_headers)

        tasks = client.get("/api/tasks?status=open", headers=central_headers)
        assert tasks.status_code == 200
        assert len(tasks.json()) == 1
        assert tasks.json()[0]["task_type"] == "readback_mismatch"
        assert tasks.json()[0]["assigned_role"] == "central_data_manager"

        completed = client.post(
            f"/api/tasks/{tasks.json()[0]['id']}/complete",
            headers=central_headers,
            json={"note": "Synthetic mismatch reconciled in Authority EDC."},
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "completed"
        assert client.get("/api/tasks?status=open", headers=central_headers).json() == []


def test_dashboard_metrics_are_centre_scoped(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "dashboard.db", environment="test")
    with TestClient(app) as client:
        site_a_headers = auth_headers(client, "site-a-investigator@example.test")
        site_b_headers = auth_headers(client, "site-b-investigator@example.test")
        central_headers = auth_headers(client, "central-data-manager@example.test")
        create_candidate(client, site_a_headers)
        create_candidate(client, site_b_headers)

        site_dashboard = client.get("/api/dashboard", headers=site_a_headers)
        central_dashboard = client.get("/api/dashboard", headers=central_headers)

        assert site_dashboard.status_code == 200
        assert site_dashboard.json()["scope"] == "SITE_A"
        assert site_dashboard.json()["overall"]["subjects"] == 1
        assert site_dashboard.json()["overall"]["pending_reviews"] == 1
        assert [row["centre_code"] for row in site_dashboard.json()["centres"]] == ["SITE_A"]

        assert central_dashboard.status_code == 200
        assert central_dashboard.json()["scope"] == "ALL_CENTRES"
        assert central_dashboard.json()["overall"]["subjects"] == 2
        assert {row["centre_code"] for row in central_dashboard.json()["centres"]} == {"SITE_A", "SITE_B"}


def test_dictionary_release_publishes_atomically_and_rollback_creates_new_release(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "dictionary-releases.db", environment="test")
    with TestClient(app) as client:
        headers = auth_headers(client, "central-data-manager@example.test")
        initial = client.get("/api/admin/field-dictionary", headers=headers).json()
        baseline_id = initial["active_release"]["id"]

        draft = client.post("/api/admin/dictionary-releases/draft", headers=headers)
        assert draft.status_code == 201
        edited = client.put(
            f"/api/admin/dictionary-releases/{draft.json()['id']}/items/WEEK_0/WBC",
            headers=headers,
            json={"display_header": "White blood cell count"},
        )
        before_publish = client.get("/api/admin/field-dictionary", headers=headers).json()

        assert edited.status_code == 200
        assert edited.json()["display_header"] == "White blood cell count"
        assert next(
            row for row in before_publish["headers"]
            if row["event_ref"] == "WEEK_0" and row["field_code"] == "WBC"
        )["display_header"] == "WBC"

        published = client.post(
            f"/api/admin/dictionary-releases/{draft.json()['id']}/publish",
            headers=headers,
        )
        active = client.get("/api/admin/field-dictionary", headers=headers).json()
        assert published.status_code == 200
        assert published.json()["status"] == "published"
        assert active["active_release"]["id"] == draft.json()["id"]
        assert next(
            row for row in active["headers"]
            if row["event_ref"] == "WEEK_0" and row["field_code"] == "WBC"
        )["display_header"] == "White blood cell count"

        rolled_back = client.post(
            f"/api/admin/dictionary-releases/{baseline_id}/rollback",
            headers=headers,
        )
        restored = client.get("/api/admin/field-dictionary", headers=headers).json()
        assert rolled_back.status_code == 201
        assert rolled_back.json()["id"] not in {baseline_id, draft.json()["id"]}
        assert rolled_back.json()["rollback_of"] == baseline_id
        assert restored["active_release"]["id"] == rolled_back.json()["id"]
        assert next(
            row for row in restored["headers"]
            if row["event_ref"] == "WEEK_0" and row["field_code"] == "WBC"
        )["display_header"] == "WBC"


def test_analysis_snapshot_is_immutable_hash_verified_and_downloadable(tmp_path: Path) -> None:
    class MatchingAdapter:
        mode = "qualified_test"
        target_kind = "libreclinica"

        def readiness(self) -> dict[str, object]:
            return {"status": "ready", "readback": "ready"}

        def submit(self, transfer_package: dict[str, object], *, idempotency_key: str) -> EdcSubmissionResult:
            del transfer_package, idempotency_key
            return EdcSubmissionResult(external_reference="AUTH/SNAPSHOT", response_sha256="f" * 64)

        def read_value(self, transfer_package: dict[str, object]) -> EdcReadbackResult:
            return EdcReadbackResult(
                status="matched",
                observed_value=str(transfer_package["value"]["final_value"]),
                response_sha256="e" * 64,
            )

    app = create_app(
        database_path=tmp_path / "snapshots.db",
        environment="test",
        edc_adapter=MatchingAdapter(),
    )
    with TestClient(app) as client:
        site_headers = auth_headers(client, "site-a-investigator@example.test")
        central_headers = auth_headers(client, "central-data-manager@example.test")
        candidate = create_candidate(client, site_headers)
        client.post(
            f"/api/candidates/{candidate['id']}/review",
            headers=site_headers,
            json={"decision": "accept"},
        )
        transfer = client.post(f"/api/candidates/{candidate['id']}/transfers", headers=site_headers).json()
        client.post(f"/api/transfers/{transfer['id']}/submit", headers=site_headers)

        created = client.post("/api/analysis-snapshots", headers=central_headers)
        assert created.status_code == 201
        assert created.json()["row_count"] == 1
        assert created.json()["integrity"] == "verified"

        listed = client.get("/api/analysis-snapshots", headers=central_headers)
        detail = client.get(
            f"/api/analysis-snapshots/{created.json()['id']}",
            headers=central_headers,
        )
        downloaded = client.get(
            f"/api/analysis-snapshots/{created.json()['id']}/download",
            headers=central_headers,
        )
        assert [row["id"] for row in listed.json()] == [created.json()["id"]]
        assert detail.json()["integrity"] == "verified"
        assert hashlib.sha256(downloaded.content).hexdigest() == created.json()["content_sha256"]
        assert downloaded.headers["content-disposition"].startswith("attachment;")
        assert client.delete(
            f"/api/analysis-snapshots/{created.json()['id']}",
            headers=central_headers,
        ).status_code == 405
