import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal, Mapping
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.kimi import KimiClient, KimiConfigurationError, KimiServiceError
from app.edc_adapter import (
    AuthorityEdcAdapter,
    DisabledEdcAdapter,
    EdcAdapterError,
    EdcReadbackResult,
    build_transfer_receipt,
    build_transfer_package,
    canonical_transfer_receipt_json,
    canonical_transfer_package_json,
    load_edc_adapter_from_environment,
    transfer_receipt_sha256,
    transfer_package_sha256,
)
from app.ocr import LocalOcrFailed, LocalOcrUnavailable, LocalTesseractOcr
from app.crf_mapping import CrfMappingError, SyntheticLabMapping
from app.spreadsheet_export import ArtifactToolSpreadsheetExporter, SpreadsheetExportError
from app.quality import assess_candidate, load_quality_rules
from app.structured_import import StructuredImportError, parse_structured_csv
from app.deidentification import (
    LocalDeidentificationFailed,
    LocalDeidentificationUnavailable,
    LocalImageDeidentifier,
)
from app.chinese_lab import (
    ChineseLabExtractionFailed,
    ChineseLabExtractionUnavailable,
    LocalChineseLabExtractor,
)
from app.pulmonary_function import (
    LocalPulmonaryFunctionPdfParser,
    PulmonaryFunctionExtractionFailed,
)
from app.extraction_contract import (
    EvidenceSpan,
    build_extraction_evidence,
    canonical_evidence_json,
    load_evidence,
)
from app.pdf_inspection import inspect_pdf
from app.disk_security import disk_encryption_status
from app.production_readiness import evaluate_production_readiness, load_evidence_manifest
from app.backup import backup_database
from app.audit_chain import make_anchor
from app.bulk_accept_policy import BulkAcceptPolicyError, evaluate_bulk_accept
from app.offline_package import (
    OfflinePackageError,
    build_encrypted_reviewed_package,
    parse_encrypted_reviewed_package,
)
from app.clock import utc_now
from app.centre_profile import CentreProfile, CentreProfileError, load_centre_profile
from app.persistence import Database
from app.runtime_config import RuntimeConfig
from app.upload_validation import ImageUploadError, validate_image_upload
from app.pdf_safety import PdfSafetyError, validate_pdf_structure
from app.security import (
    SETUP_REQUIRED_PASSWORD_HASH,
    password_hash,
    strong_password,
)
from app.api.authentication import (
    CENTRAL_ROLES,
    EXPORT_ROLES,
    GLOBAL_READ_ROLES,
    READ_ONLY_ROLES,
    REVIEWER_ROLES,
    UserContext,
    create_auth_module,
)
from app.api.static_delivery import create_static_delivery_router
from app.api.kimi_settings import create_kimi_settings_router, kimi_status_payload
from app.version import __version__
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
SUBJECT_REF_RE = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
EVENT_REF_RE = re.compile(r"^[A-Z][A-Z0-9_-]{1,63}$")
DICTIONARY_CANDIDATE_TARGETS = {"crf_item", "candidate_field"}
LAB_RESULT_LINE_RE = re.compile(
    r"^\s*(?P<field>[A-Za-z][A-Za-z0-9_-]{0,63})"
    r"(?:\s*[:：]\s*|\s+)"
    r"(?P<value>[<>≤≥]?\s*-?\d+(?:[.,]\d+)?)"
    r"(?:\s+(?:H|L|HIGH|LOW|↑|↓))?"
    r"(?:\s+[<>≤≥]?\s*-?\d+(?:[.,]\d+)?\s*[-~–—]\s*[<>≤≥]?\s*-?\d+(?:[.,]\d+)?)?"
    r"(?:\s+(?P<unit>\S.*?))?\s*$",
    re.IGNORECASE,
)


class SetupCompletePayload(BaseModel):
    password: str = Field(min_length=16, max_length=128)
    password_confirmation: str = Field(min_length=16, max_length=128)


class SourceFileCreate(BaseModel):
    source_filename: str = Field(min_length=1, max_length=200)
    sha256: str
    mime_type: str = Field(pattern=r"^(?:image/|application/pdf$)")
    storage_key: str = Field(min_length=1, max_length=500)
    centre_code: str | None = None

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        value = value.lower()
        if not SHA256_RE.fullmatch(value):
            raise ValueError("sha256 must be a 64-character lowercase hexadecimal digest")
        return value


class CandidateCreate(BaseModel):
    source_file_id: str
    edc_subject_ref: str = Field(pattern=r"^[A-Z][A-Z0-9_-]{2,63}$")
    edc_event_ref: str = Field(pattern=r"^[A-Z][A-Z0-9_-]{1,63}$")
    field_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    proposed_value: str = Field(min_length=1, max_length=200)
    unit: str | None = Field(default=None, max_length=50)
    ocr_engine_version: str = Field(min_length=1, max_length=100)
    kimi_model: str = Field(min_length=1, max_length=100)
    schema_version: str = Field(min_length=1, max_length=100)
    confidence: float = Field(ge=0, le=1)


class ReviewPayload(BaseModel):
    decision: Literal["accept", "edit", "reject"]
    edited_value: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=500)
    selected_source: Literal["local", "kimi", "manual"] | None = None
    evidence_acknowledged: bool = False
    evidence_source_file_id: str | None = Field(default=None, max_length=100)

    @field_validator("reason")
    @classmethod
    def normalise_optional_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class BulkAcceptPayload(BaseModel):
    candidate_ids: list[str] = Field(min_length=1, max_length=500)
    review_batch_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    override_sources: list[Literal["conflict", "kimi_only"]] = Field(
        default_factory=list,
        max_length=2,
    )
    override_reason: str | None = Field(default=None, max_length=500)
    conflict_value_source: Literal["local", "kimi"] | None = None
    evidence_acknowledged_candidate_ids: list[str] = Field(default_factory=list, max_length=500)

    @field_validator("candidate_ids")
    @classmethod
    def reject_duplicate_candidate_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("candidate_ids must be unique")
        return value

    @field_validator("override_sources")
    @classmethod
    def reject_duplicate_override_sources(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("override_sources must be unique")
        return value

    @field_validator("evidence_acknowledged_candidate_ids")
    @classmethod
    def reject_duplicate_evidence_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("evidence_acknowledged_candidate_ids must be unique")
        return value

    @field_validator("override_reason")
    @classmethod
    def normalise_override_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class TransferReconciliationPayload(BaseModel):
    note: str = Field(min_length=1, max_length=500)


class DemoExtractPayload(BaseModel):
    edc_subject_ref: str = Field(pattern=r"^[A-Z][A-Z0-9_-]{2,63}$")
    edc_event_ref: str = Field(pattern=r"^[A-Z][A-Z0-9_-]{1,63}$")
    deidentified_ocr_text: str = Field(min_length=3, max_length=20_000)


class LocalOcrExtractPayload(BaseModel):
    edc_subject_ref: str = Field(pattern=r"^[A-Z][A-Z0-9_-]{2,63}$")
    edc_event_ref: str = Field(pattern=r"^[A-Z][A-Z0-9_-]{1,63}$")
    field_codes: list[str] | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("field_codes")
    @classmethod
    def normalise_field_codes(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [field_code.strip().upper() for field_code in value]
        if (
            len(normalized) != len(set(normalized))
            or any(not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", field_code) for field_code in normalized)
        ):
            raise ValueError("field_codes must be unique stable uppercase field codes")
        return normalized


class HybridExtractPayload(LocalOcrExtractPayload):
    use_kimi: bool = True


class RecognitionJobItemPayload(BaseModel):
    source_file_id: str = Field(min_length=1, max_length=100)
    edc_subject_ref: str = Field(pattern=r"^[A-Z][A-Z0-9_-]{2,63}$")
    edc_event_ref: str = Field(pattern=r"^[A-Z][A-Z0-9_-]{1,63}$")
    field_codes: list[str] | None = Field(default=None, min_length=1, max_length=500)
    use_kimi: bool = True

    @field_validator("field_codes")
    @classmethod
    def normalise_job_field_codes(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [field_code.strip().upper() for field_code in value]
        if (
            len(normalized) != len(set(normalized))
            or any(not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", field_code) for field_code in normalized)
        ):
            raise ValueError("field_codes must be unique stable uppercase field codes")
        return normalized


class RecognitionJobCreatePayload(BaseModel):
    items: list[RecognitionJobItemPayload] = Field(min_length=1, max_length=100)


class DeidentificationConfirmPayload(BaseModel):
    human_review_attestation: bool


class FieldHeaderUpdatePayload(BaseModel):
    display_header: str = Field(min_length=1, max_length=200)

    @field_validator("display_header")
    @classmethod
    def normalise_display_header(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped or any(ord(character) < 32 for character in stripped):
            raise ValueError("display_header must be visible text")
        return stripped


class IssueMessagePayload(BaseModel):
    message: str = Field(min_length=1, max_length=1000)

    @field_validator("message")
    @classmethod
    def normalise_message(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped or any(ord(character) < 32 and character not in "\r\n\t" for character in stripped):
            raise ValueError("message must be visible text")
        return stripped


class OptionalIssueMessagePayload(BaseModel):
    message: str | None = Field(default=None, max_length=1000)

    @field_validator("message")
    @classmethod
    def normalise_optional_message(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class TransferHoldPayload(BaseModel):
    scope: Literal["dataset", "centre", "subject", "visit"]
    centre_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_-]{1,31}$")
    subject_ref: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_-]{2,63}$")
    event_ref: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_-]{1,63}$")
    action: Literal["held", "released"]
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalise_reason(cls, value: str) -> str:
        return value.strip()


class UserCreatePayload(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$")
    role: Literal["site_investigator", "monitor", "auditor"]
    centre_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_-]{1,31}$")


class CentreAccountRequest(BaseModel):
    centre_code: str = Field(pattern=r"^[A-Z][A-Z0-9_-]{1,31}$")
    username: str = Field(pattern=r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$")


class CentreAccountBatchPayload(BaseModel):
    accounts: list[CentreAccountRequest] = Field(min_length=1, max_length=100)

    @field_validator("accounts")
    @classmethod
    def unique_centres_and_usernames(cls, value: list[CentreAccountRequest]) -> list[CentreAccountRequest]:
        centres = [item.centre_code for item in value]
        usernames = [item.username.lower() for item in value]
        if len(centres) != len(set(centres)) or len(usernames) != len(set(usernames)):
            raise ValueError("centre_codes_and_usernames_must_be_unique")
        return value


class TaskCompletePayload(BaseModel):
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def normalise_optional_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


def row_to_dict(row: sqlite3.Row) -> dict[str, object]:
    return {key: row[key] for key in row.keys()}


def recognition_job_item_candidate_ids(
    connection: sqlite3.Connection,
    item: sqlite3.Row,
) -> list[str]:
    if item["candidate_ids_json"]:
        try:
            candidate_ids = json.loads(item["candidate_ids_json"])
        except (json.JSONDecodeError, TypeError):
            return []
        if isinstance(candidate_ids, list) and all(isinstance(value, str) for value in candidate_ids):
            if candidate_ids:
                return candidate_ids
            # Empty arrays were persisted by older builds before candidate
            # linkage was available; succeeded items can recover exact lineage.
        else:
            return []
    if item["status"] != "succeeded":
        return []

    selected_fields = set(json.loads(item["field_codes_json"])) if item["field_codes_json"] else None
    linked_candidates = connection.execute(
        """
        SELECT DISTINCT candidates.id, candidates.field_code, candidates.created_at
        FROM candidates
        LEFT JOIN deidentification_drafts
          ON deidentification_drafts.derivative_source_file_id = candidates.source_file_id
        WHERE candidates.centre_code = ?
          AND candidates.edc_subject_ref = ?
          AND candidates.edc_event_ref = ?
          AND (
            candidates.source_file_id = ?
            OR deidentification_drafts.original_source_file_id = ?
          )
        ORDER BY candidates.created_at, candidates.id
        """,
        (
            item["centre_code"],
            item["edc_subject_ref"],
            item["edc_event_ref"],
            item["source_file_id"],
            item["source_file_id"],
        ),
    ).fetchall()
    candidate_ids = [
        candidate["id"]
        for candidate in linked_candidates
        if selected_fields is None or candidate["field_code"] in selected_fields
    ]
    if candidate_ids:
        connection.execute(
            "UPDATE recognition_job_items SET candidate_ids_json = ? WHERE id = ?",
            (json.dumps(candidate_ids), item["id"]),
        )
    return candidate_ids


def recognition_job_payload(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, object]:
    items = connection.execute(
        """
        SELECT id, source_file_id, centre_code, edc_subject_ref, edc_event_ref,
               field_codes_json, candidate_ids_json, use_kimi, status, attempts, error_code, error_message,
               created_at, started_at, finished_at, last_retry_at
        FROM recognition_job_items
        WHERE job_id = ?
        ORDER BY created_at, id
        """,
        (row["id"],),
    ).fetchall()
    return {
        "id": row["id"],
        "centre_code": row["centre_code"],
        "status": row["status"],
        "item_count": row["item_count"],
        "completed_count": row["completed_count"],
        "failed_count": row["failed_count"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "cancelled_by": row["cancelled_by"],
        "cancelled_at": row["cancelled_at"],
        "items": [
            {
                "id": item["id"],
                "source_file_id": item["source_file_id"],
                "centre_code": item["centre_code"],
                "edc_subject_ref": item["edc_subject_ref"],
                "edc_event_ref": item["edc_event_ref"],
                "field_codes": json.loads(item["field_codes_json"])
                if item["field_codes_json"]
                else None,
                "candidate_ids": recognition_job_item_candidate_ids(connection, item),
                "use_kimi": bool(item["use_kimi"]),
                "status": item["status"],
                "attempts": item["attempts"],
                "error_code": item["error_code"],
                "error_message": item["error_message"],
                "created_at": item["created_at"],
                "started_at": item["started_at"],
                "finished_at": item["finished_at"],
                "last_retry_at": item["last_retry_at"],
            }
            for item in items
        ],
    }


def source_file_payload(row: sqlite3.Row) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": row["id"],
        "centre_code": row["centre_code"],
        "source_filename": row["source_filename"],
        "sha256": row["sha256"],
        "mime_type": row["mime_type"],
        "storage_key": row["storage_key"],
        "content_purged_at": row["content_purged_at"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
    }
    if row["edc_provisioning_status"] or row["edc_subject_oid"]:
        payload["edc_subject_provisioning"] = {
            "status": row["edc_provisioning_status"] or (
                "completed" if row["edc_subject_oid"] else "deferred"
            ),
            "subject_ref": row["edc_subject_ref"],
            "event_ref": row["edc_event_ref"],
            "subject_oid": row["edc_subject_oid"],
            "subject_created": bool(row["edc_subject_created"]),
            "event_scheduled": bool(row["edc_event_scheduled"]),
            "provisioned_at": row["edc_provisioned_at"],
            "error_code": row["edc_provisioning_error_code"],
        }
    else:
        payload["edc_subject_provisioning"] = None
    return payload


def deidentification_draft_payload(
    row: sqlite3.Row,
    derivative_source_file: sqlite3.Row,
) -> dict[str, object]:
    return {
        "id": row["id"],
        "original_source_file_id": row["original_source_file_id"],
        "derivative_source_file": source_file_payload(derivative_source_file),
        "status": row["status"],
        "detected_marker_codes": json.loads(row["detected_marker_codes_json"]),
        "ocr_engine_version": row["ocr_engine_version"],
        "requires_human_review": row["status"] != "confirmed",
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "confirmed_by": row["confirmed_by"],
        "confirmed_at": row["confirmed_at"],
    }


def candidate_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "centre_code": row["centre_code"],
        "source_file_id": row["source_file_id"],
        "edc_subject_ref": row["edc_subject_ref"],
        "edc_event_ref": row["edc_event_ref"],
        "field_code": row["field_code"],
        "proposed_value": row["proposed_value"],
        "final_value": row["final_value"],
        "unit": row["unit"],
        "status": row["status"],
        "ocr_engine_version": row["ocr_engine_version"],
        "kimi_model": row["kimi_model"],
        "schema_version": row["schema_version"],
        "confidence": row["confidence"],
        "local_ocr_value": row["local_ocr_value"],
        "local_ocr_unit": row["local_ocr_unit"],
        "extraction_agreement": row["extraction_agreement"],
        "evidence_text": row["evidence_text"],
        "origin_type": row["origin_type"],
        "import_batch_id": row["import_batch_id"],
        "source_sha256": row["source_sha256"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "reviewed_by": row["reviewed_by"],
        "reviewed_at": row["reviewed_at"],
        "review_reason": row["review_reason"],
        "extraction_run_id": row["extraction_run_id"],
        "extraction_evidence": load_evidence(row["extraction_evidence_json"]),
    }


def data_issue_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "candidate_id": row["candidate_id"],
        "centre_code": row["centre_code"],
        "status": row["status"],
        "opened_message": row["opened_message"],
        "opened_by": row["opened_by"],
        "opened_at": row["opened_at"],
        "answer_message": row["answer_message"],
        "answered_by": row["answered_by"],
        "answered_at": row["answered_at"],
        "resolution_message": row["resolution_message"],
        "resolved_by": row["resolved_by"],
        "resolved_at": row["resolved_at"],
        "reopened_by": row["reopened_by"],
        "reopened_at": row["reopened_at"],
        "authority_workflow": "formal_queries_remain_in_libreclinica",
    }


def task_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "centre_code": row["centre_code"],
        "task_type": row["task_type"],
        "status": row["status"],
        "assigned_role": row["assigned_role"],
        "candidate_id": row["candidate_id"],
        "transfer_id": row["transfer_id"],
        "data_issue_id": row["data_issue_id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "completed_by": row["completed_by"],
        "completed_at": row["completed_at"],
        "completion_note": row["completion_note"],
        "external_notification": "disabled_pending_approval",
    }


def analysis_snapshot_payload(row: sqlite3.Row) -> dict[str, object]:
    actual_sha256 = hashlib.sha256(row["canonical_json"].encode("utf-8")).hexdigest()
    return {
        "id": row["id"],
        "content_sha256": row["content_sha256"],
        "row_count": row["row_count"],
        "dictionary_release_id": row["dictionary_release_id"],
        "quality_rule_version": row["quality_rule_version"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "integrity": "verified" if actual_sha256 == row["content_sha256"] else "failed",
        "authority_boundary": "companion_snapshot_not_formal_authority_edc_lock",
    }


def candidate_select_sql() -> str:
    return """
        SELECT candidates.*, source_files.sha256 AS source_sha256,
               extraction_runs.evidence_json AS extraction_evidence_json
        FROM candidates
        JOIN source_files ON source_files.id = candidates.source_file_id
        LEFT JOIN extraction_runs ON extraction_runs.id = candidates.extraction_run_id
    """


def persist_extraction_run(
    connection: sqlite3.Connection,
    *,
    source_file: sqlite3.Row,
    subject_ref: str,
    event_ref: str,
    dictionary_id: str,
    dictionary_version: str,
    engine: str,
    engine_version: str,
    model_ids: list[str],
    duration_ms: int,
    evidence: dict[str, object],
    idempotency_key: str,
    created_by: str,
) -> sqlite3.Row:
    """Insert or reuse an immutable extraction run at the SQLite boundary."""
    existing = connection.execute(
        "SELECT * FROM extraction_runs WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    if existing is not None:
        return existing
    run_id = str(uuid4())
    try:
        connection.execute(
            """
            INSERT INTO extraction_runs (
                id, centre_code, source_file_id, edc_subject_ref, edc_event_ref,
                dictionary_id, dictionary_version, engine, engine_version,
                model_ids_json, source_sha256, derivative_sha256, preprocessing_version,
                idempotency_key, duration_ms, evidence_json, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                source_file["centre_code"],
                source_file["id"],
                subject_ref,
                event_ref,
                dictionary_id,
                dictionary_version,
                engine,
                engine_version,
                json.dumps(model_ids, ensure_ascii=False, separators=(",", ":")),
                source_file["sha256"],
                source_file["sha256"] if source_file["storage_key"].startswith("deidentified/") else None,
                evidence["preprocessing_version"],
                idempotency_key,
                max(0, int(duration_ms)),
                canonical_evidence_json(evidence),
                created_by,
                utc_now(),
            ),
        )
    except sqlite3.IntegrityError:
        existing = connection.execute(
            "SELECT * FROM extraction_runs WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing is None:
            raise
        return existing
    return connection.execute("SELECT * FROM extraction_runs WHERE id = ?", (run_id,)).fetchone()


def extraction_run_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "centre_code": row["centre_code"],
        "source_file_id": row["source_file_id"],
        "edc_subject_ref": row["edc_subject_ref"],
        "edc_event_ref": row["edc_event_ref"],
        "dictionary_id": row["dictionary_id"],
        "dictionary_version": row["dictionary_version"],
        "engine": row["engine"],
        "engine_version": row["engine_version"],
        "model_ids": json.loads(row["model_ids_json"]),
        "source_sha256": row["source_sha256"],
        "derivative_sha256": row["derivative_sha256"],
        "preprocessing_version": row["preprocessing_version"],
        "idempotency_key": row["idempotency_key"],
        "duration_ms": row["duration_ms"],
        "evidence": load_evidence(row["evidence_json"]),
        "created_by": row["created_by"],
        "created_at": row["created_at"],
    }


def visit_candidate_state_sha256(candidates: list[sqlite3.Row]) -> str:
    state = [
        {
            "id": row["id"],
            "status": row["status"],
            "final_value": row["final_value"],
            "unit": row["unit"],
            "created_at": row["created_at"],
            "reviewed_at": row["reviewed_at"],
        }
        for row in sorted(candidates, key=lambda candidate: candidate["id"])
    ]
    canonical = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def transfer_payload(row: sqlite3.Row) -> dict[str, object]:
    last_error = None
    if row["last_error_code"] is not None:
        last_error = {
            "code": row["last_error_code"],
            "message": row["last_error_message"],
        }
    reconciliation = None
    if row["reconciled_at"] is not None:
        reconciliation = {
            "reconciled_by": row["reconciled_by"],
            "reconciled_at": row["reconciled_at"],
            "note": row["reconciliation_note"],
        }
    return {
        "id": row["id"],
        "candidate_id": row["candidate_id"],
        "centre_code": row["centre_code"],
        "mode": row["mode"],
        "status": row["status"],
        "target": row["target_kind"],
        "package_sha256": row["package_sha256"],
        "idempotency_key": row["idempotency_key"],
        "attempt_count": row["attempt_count"],
        "retry_count": row["retry_count"],
        "last_error": last_error,
        "reconciliation": reconciliation,
        "external_reference": row["external_reference"],
        "authority_response_sha256": row["authority_response_sha256"],
        "submitted_at": row["submitted_at"],
        "readback_status": row["readback_status"],
        "readback_checked_at": row["readback_checked_at"],
        "readback_attempt_count": row["readback_attempt_count"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"] or row["created_at"],
    }


def assert_centre_access(user: UserContext, centre_code: str) -> None:
    if user.role in GLOBAL_READ_ROLES:
        return
    if user.centre_code != centre_code:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")


def parse_demo_lab_text(text: str) -> list[tuple[str, str, str | None]]:
    forbidden_markers = ("姓名", "住院号", "身份证", "手机", "电话", "patient name")
    lowered = text.lower()
    if any(marker.lower() in lowered for marker in forbidden_markers):
        raise HTTPException(status_code=422, detail="deidentified_text_required")

    parsed: list[tuple[str, str, str | None]] = []
    for line in text.splitlines():
        match = LAB_RESULT_LINE_RE.match(line)
        if match:
            unit = match.group("unit")
            parsed.append(
                (
                    match.group("field").upper(),
                    match.group("value").replace(" ", ""),
                    unit.strip() if unit else None,
                )
            )
    if not parsed:
        raise HTTPException(status_code=422, detail="no_demo_lab_values_found")
    return parsed


def normalise_candidate_comparison(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", "", value).casefold()


def create_app(
    database_path: Path | None = None,
    environment: str | None = None,
    kimi_client: KimiClient | None = None,
    ocr_client: object | None = None,
    deidentifier: object | None = None,
    lab_extractor: object | None = None,
    edc_adapter: AuthorityEdcAdapter | None = None,
    spreadsheet_exporter: object | None = None,
    quality_rules: Mapping[str, object] | None = None,
    pulmonary_parser: object | None = None,
    product_mode: str | None = None,
    centre_profile: CentreProfile | None = None,
) -> FastAPI:
    runtime_config = RuntimeConfig.from_environment(
        database_path=database_path,
        environment=environment,
        product_mode=product_mode,
    )
    resolved_environment = runtime_config.environment
    resolved_product_mode = runtime_config.product_mode
    resolved_database_path = runtime_config.database_path
    try:
        resolved_centre_profile = centre_profile or load_centre_profile()
    except CentreProfileError as error:
        raise RuntimeError(str(error)) from error
    database = Database(resolved_database_path, centre_profile=resolved_centre_profile)
    database_existed_before_initialise = resolved_database_path.is_file()
    database.initialise()
    if database_existed_before_initialise and os.getenv("COMPANION_AUTO_BACKUP", "false").lower() == "true":
        backup_directory = Path(
            os.getenv("COMPANION_BACKUP_DIRECTORY", str(resolved_database_path.parent / ".runtime" / "backups"))
        )
        try:
            backup_database(resolved_database_path, backup_directory)
        except (OSError, RuntimeError, sqlite3.Error) as error:
            raise RuntimeError("automatic_backup_restore_check_failed") from error
    resolved_kimi_client = kimi_client or KimiClient.from_environment()
    resolved_ocr_client = ocr_client or LocalTesseractOcr.from_environment()
    resolved_deidentifier = deidentifier or LocalImageDeidentifier(resolved_ocr_client)
    resolved_edc_adapter = (
        DisabledEdcAdapter()
        if resolved_product_mode == "lite"
        else edc_adapter or load_edc_adapter_from_environment()
    )
    resolved_spreadsheet_exporter = spreadsheet_exporter or ArtifactToolSpreadsheetExporter.from_environment()
    resolved_quality_rules = dict(quality_rules) if quality_rules is not None else load_quality_rules()
    resolved_pulmonary_parser = pulmonary_parser or LocalPulmonaryFunctionPdfParser()
    resolved_lab_extractor = lab_extractor
    if resolved_lab_extractor is None and isinstance(resolved_ocr_client, LocalTesseractOcr):
        resolved_lab_extractor = LocalChineseLabExtractor(resolved_ocr_client)
    try:
        resolved_crf_mapping = SyntheticLabMapping.from_default_file()
    except CrfMappingError as error:
        raise RuntimeError("synthetic_crf_mapping_required") from error
    try:
        configured_retention_days = int(os.getenv("COMPANION_ORIGINAL_RETENTION_DAYS", "30"))
    except ValueError:
        configured_retention_days = 30
    configured_retention_days = max(1, min(configured_retention_days, 3650))

    app = FastAPI(
        title="ClinData Relay",
        version=__version__,
        description="Synthetic-data-only OCR/Kimi candidate workbench. It is not an EDC.",
    )

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=()",
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'; "
            "img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; "
            "connect-src 'self'",
        )
        return response

    app.state.database = database
    app.state.environment = resolved_environment
    app.state.product_mode = resolved_product_mode
    app.state.runtime_config = runtime_config
    app.state.edc_adapter = resolved_edc_adapter
    app.state.spreadsheet_exporter = resolved_spreadsheet_exporter

    app.include_router(create_static_delivery_router(Path(__file__).parent / "static"))
    auth_module = create_auth_module(
        database,
        environment=resolved_environment,
        centre_profile=resolved_centre_profile,
    )
    app.include_router(auth_module.router)
    current_user = auth_module.current_user
    app.include_router(
        create_kimi_settings_router(
            database,
            kimi_client=resolved_kimi_client,
            product_mode=resolved_product_mode,
            centre_profile=resolved_centre_profile,
            current_user=current_user,
        )
    )

    def centre_setup_required() -> bool:
        if resolved_centre_profile is None:
            return False
        with database.connect() as connection:
            row = connection.execute(
                "SELECT password_hash FROM users WHERE username = ? AND centre_code = ?",
                (resolved_centre_profile.username, resolved_centre_profile.centre_code),
            ).fetchone()
        return row is not None and row["password_hash"] == SETUP_REQUIRED_PASSWORD_HASH

    def require_central_data_manager(user: UserContext) -> None:
        if user.role != "central_data_manager":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="central_data_manager_required")

    def require_workflow_write_role(user: UserContext) -> None:
        if user.role not in REVIEWER_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="read_only_role")

    def dictionary_release_payload(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, object]:
        active = connection.execute(
            "SELECT active_release_id FROM dictionary_release_state WHERE singleton_id = 1"
        ).fetchone()
        item_count = connection.execute(
            "SELECT COUNT(*) AS count FROM dictionary_release_items WHERE release_id = ?",
            (row["id"],),
        ).fetchone()["count"]
        return {
            "id": row["id"],
            "version": row["version"],
            "status": row["status"],
            "active": bool(active is not None and active["active_release_id"] == row["id"]),
            "base_release_id": row["base_release_id"],
            "rollback_of": row["rollback_of"],
            "item_count": item_count,
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "published_by": row["published_by"],
            "published_at": row["published_at"],
        }

    def ensure_dictionary_baseline(connection: sqlite3.Connection) -> sqlite3.Row:
        state = connection.execute(
            "SELECT active_release_id FROM dictionary_release_state WHERE singleton_id = 1"
        ).fetchone()
        if state is not None:
            active_release = connection.execute(
                "SELECT * FROM dictionary_releases WHERE id = ?",
                (state["active_release_id"],),
            ).fetchone()
            expected_columns = {
                (str(column["event_ref"]), str(column["field_code"]).upper()): column
                for column in resolved_crf_mapping.all_dictionary_columns()
                if column.get("target_kind") in DICTIONARY_CANDIDATE_TARGETS
                and column.get("uploadable") is True
            }
            active_items = {
                (row["event_ref"], row["field_code"]): row["display_header"]
                for row in connection.execute(
                    """
                    SELECT event_ref, field_code, display_header
                    FROM dictionary_release_items WHERE release_id = ?
                    """,
                    (active_release["id"],),
                ).fetchall()
            }
            if set(active_items) == set(expected_columns):
                return active_release
            release_id = str(uuid4())
            created_at = utc_now()
            connection.execute(
                """
                INSERT INTO dictionary_releases (
                    id, version, status, base_release_id, rollback_of, created_by,
                    created_at, published_by, published_at
                ) VALUES (?, ?, 'published', ?, NULL, 'system:mapping-sync', ?,
                          'system:mapping-sync', ?)
                """,
                (
                    release_id,
                    f"baseline-sync-{resolved_crf_mapping.mapping_version}",
                    active_release["id"],
                    created_at,
                    created_at,
                ),
            )
            overrides = {
                (row["event_ref"], row["field_code"]): row["display_header"]
                for row in connection.execute("SELECT * FROM field_header_overrides").fetchall()
            }
            for key, column in expected_columns.items():
                display_header = overrides.get(
                    key,
                    active_items.get(key, str(column["source_header"])),
                )
                connection.execute(
                    """
                    INSERT INTO dictionary_release_items (release_id, event_ref, field_code, display_header)
                    VALUES (?, ?, ?, ?)
                    """,
                    (release_id, key[0], key[1], display_header),
                )
            connection.execute(
                "UPDATE dictionary_release_state SET active_release_id = ? WHERE singleton_id = 1",
                (release_id,),
            )
            return connection.execute(
                "SELECT * FROM dictionary_releases WHERE id = ?",
                (release_id,),
            ).fetchone()
        release_id = str(uuid4())
        created_at = utc_now()
        version = f"baseline-{resolved_crf_mapping.mapping_version}"
        connection.execute(
            """
            INSERT INTO dictionary_releases (
                id, version, status, base_release_id, rollback_of, created_by,
                created_at, published_by, published_at
            ) VALUES (?, ?, 'published', NULL, NULL, 'system:mapping-import', ?,
                      'system:mapping-import', ?)
            """,
            (release_id, version, created_at, created_at),
        )
        overrides = {
            (row["event_ref"], row["field_code"]): row["display_header"]
            for row in connection.execute("SELECT * FROM field_header_overrides").fetchall()
        }
        for column in resolved_crf_mapping.all_dictionary_columns():
            if column.get("target_kind") not in DICTIONARY_CANDIDATE_TARGETS or column.get("uploadable") is not True:
                continue
            event_ref = str(column["event_ref"])
            field_code = str(column["field_code"]).upper()
            display_header = overrides.get((event_ref, field_code), str(column["source_header"]))
            connection.execute(
                """
                INSERT INTO dictionary_release_items (release_id, event_ref, field_code, display_header)
                VALUES (?, ?, ?, ?)
                """,
                (release_id, event_ref, field_code, display_header),
            )
        connection.execute(
            "INSERT INTO dictionary_release_state (singleton_id, active_release_id) VALUES (1, ?)",
            (release_id,),
        )
        return connection.execute("SELECT * FROM dictionary_releases WHERE id = ?", (release_id,)).fetchone()

    def active_dictionary_release(connection: sqlite3.Connection) -> sqlite3.Row:
        ensure_dictionary_baseline(connection)
        return connection.execute(
            """
            SELECT dictionary_releases.* FROM dictionary_release_state
            JOIN dictionary_releases
              ON dictionary_releases.id = dictionary_release_state.active_release_id
            WHERE dictionary_release_state.singleton_id = 1
            """
        ).fetchone()

    def effective_field_dictionary(event_ref: str) -> dict[str, str]:
        field_dictionary = resolved_crf_mapping.field_dictionary_for_event(event_ref)
        with database.connect() as connection:
            release = active_dictionary_release(connection)
            items = connection.execute(
                """
                SELECT field_code, display_header
                FROM dictionary_release_items
                WHERE release_id = ? AND event_ref = ?
                """,
                (release["id"], event_ref),
            ).fetchall()
        for item in items:
            if item["field_code"] in field_dictionary:
                field_dictionary[item["field_code"]] = item["display_header"]
        return field_dictionary

    def recognition_field_scope(
        event_ref: str,
        requested_field_codes: list[str] | None,
    ) -> frozenset[str]:
        allowed_fields = resolved_crf_mapping.allowed_fields_by_event.get(event_ref)
        if allowed_fields is None:
            raise HTTPException(status_code=422, detail="event_not_in_crf_mapping")
        if requested_field_codes is None:
            return frozenset(allowed_fields)
        requested = frozenset(requested_field_codes)
        if not requested.issubset(allowed_fields):
            raise HTTPException(status_code=422, detail="recognition_field_not_allowed")
        return requested

    def field_dictionary_payload(connection: sqlite3.Connection) -> dict[str, object]:
        release = active_dictionary_release(connection)
        release_items = {
            (row["event_ref"], row["field_code"]): row["display_header"]
            for row in connection.execute(
                "SELECT event_ref, field_code, display_header FROM dictionary_release_items WHERE release_id = ?",
                (release["id"],),
            ).fetchall()
        }
        override_rows = connection.execute("SELECT * FROM field_header_overrides").fetchall()
        overrides = {
            (row["event_ref"], row["field_code"]): row
            for row in override_rows
        }
        headers: list[dict[str, object]] = []
        for column in resolved_crf_mapping.all_dictionary_columns():
            event_ref = str(column.get("event_ref") or "") or None
            field_code = str(column.get("field_code") or "").upper() or None
            editable = bool(
                event_ref
                and field_code
                and column.get("target_kind") in DICTIONARY_CANDIDATE_TARGETS
                and column.get("uploadable") is True
            )
            override = overrides.get((event_ref, field_code)) if editable else None
            source_header = str(column.get("source_header") or "")
            release_header = release_items.get((event_ref, field_code)) if editable else None
            headers.append(
                {
                    "column": column.get("column"),
                    "source_group": column.get("source_group"),
                    "event_ref": event_ref,
                    "field_code": field_code,
                    "source_header": source_header,
                    "display_header": release_header or source_header,
                    "target_kind": column.get("target_kind"),
                    "uploadable": column.get("uploadable") is True,
                    "editable": editable,
                    "revision": override["revision"] if override is not None else 0,
                    "updated_by": override["updated_by"] if override is not None else None,
                    "updated_at": override["updated_at"] if override is not None else None,
                }
            )
        return {
            "dictionary_id": resolved_crf_mapping.mapping_id,
            "dictionary_version": resolved_crf_mapping.mapping_version,
            "data_boundary": "synthetic_only",
            "header_count": len(headers),
            "immutable_keys": ["event_ref", "field_code", "target_kind"],
            "active_release": dictionary_release_payload(connection, release),
            "headers": headers,
        }

    def create_dictionary_draft_record(
        connection: sqlite3.Connection,
        *,
        actor_username: str,
        rollback_of: str | None = None,
        source_release_id: str | None = None,
        version_prefix: str = "draft",
    ) -> sqlite3.Row:
        active = active_dictionary_release(connection)
        source_id = source_release_id or active["id"]
        release_id = str(uuid4())
        connection.execute(
            """
            INSERT INTO dictionary_releases (
                id, version, status, base_release_id, rollback_of, created_by, created_at
            ) VALUES (?, ?, 'draft', ?, ?, ?, ?)
            """,
            (
                release_id,
                f"{version_prefix}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{release_id[:8]}",
                active["id"],
                rollback_of,
                actor_username,
                utc_now(),
            ),
        )
        connection.execute(
            """
            INSERT INTO dictionary_release_items (release_id, event_ref, field_code, display_header)
            SELECT ?, event_ref, field_code, display_header
            FROM dictionary_release_items WHERE release_id = ?
            """,
            (release_id, source_id),
        )
        return connection.execute("SELECT * FROM dictionary_releases WHERE id = ?", (release_id,)).fetchone()

    def publish_dictionary_release_record(
        connection: sqlite3.Connection,
        *,
        release_id: str,
        actor_username: str,
    ) -> sqlite3.Row:
        release = connection.execute(
            "SELECT * FROM dictionary_releases WHERE id = ?",
            (release_id,),
        ).fetchone()
        if release is None:
            raise HTTPException(status_code=404, detail="not_found")
        if release["status"] != "draft":
            raise HTTPException(status_code=409, detail="dictionary_release_not_draft")
        expected_keys = {
            (str(column["event_ref"]), str(column["field_code"]).upper())
            for column in resolved_crf_mapping.all_dictionary_columns()
            if column.get("target_kind") in DICTIONARY_CANDIDATE_TARGETS and column.get("uploadable") is True
        }
        item_rows = connection.execute(
            "SELECT event_ref, field_code, display_header FROM dictionary_release_items WHERE release_id = ?",
            (release_id,),
        ).fetchall()
        item_keys = {(row["event_ref"], row["field_code"]) for row in item_rows}
        if item_keys != expected_keys or any(not str(row["display_header"]).strip() for row in item_rows):
            raise HTTPException(status_code=422, detail="dictionary_release_invalid")
        previous = active_dictionary_release(connection)
        previous_items = {
            (row["event_ref"], row["field_code"]): row["display_header"]
            for row in connection.execute(
                "SELECT event_ref, field_code, display_header FROM dictionary_release_items WHERE release_id = ?",
                (previous["id"],),
            ).fetchall()
        }
        published_at = utc_now()
        connection.execute(
            """
            UPDATE dictionary_releases
            SET status = 'published', published_by = ?, published_at = ?
            WHERE id = ? AND status = 'draft'
            """,
            (actor_username, published_at, release_id),
        )
        connection.execute(
            "UPDATE dictionary_release_state SET active_release_id = ? WHERE singleton_id = 1",
            (release_id,),
        )
        changed_items = [
            row for row in item_rows
            if previous_items.get((row["event_ref"], row["field_code"])) != row["display_header"]
        ]
        for item in changed_items:
            connection.execute(
                """
                INSERT INTO field_header_overrides (
                    event_ref, field_code, display_header, updated_by, updated_at, revision
                ) VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(event_ref, field_code) DO UPDATE SET
                    display_header = excluded.display_header,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at,
                    revision = field_header_overrides.revision + 1
                """,
                (item["event_ref"], item["field_code"], item["display_header"], actor_username, published_at),
            )
        audit(
            connection,
            candidate_id=None,
            centre_code="CENTRAL",
            event_type="dictionary_release_published",
            actor_username=actor_username,
            details={
                "release_id": release_id,
                "base_release_id": release["base_release_id"],
                "rollback_of": release["rollback_of"],
                "changed_item_count": len(changed_items),
            },
        )
        return connection.execute("SELECT * FROM dictionary_releases WHERE id = ?", (release_id,)).fetchone()

    def submitted_data_export_payload(user: UserContext) -> dict[str, object]:
        with database.connect() as connection:
            query = """
                SELECT candidates.centre_code, candidates.edc_subject_ref, candidates.edc_event_ref,
                       candidates.field_code, candidates.final_value, candidates.created_at,
                       transfer_requests.submitted_at, transfer_requests.external_reference
                FROM candidates
                JOIN transfer_requests ON transfer_requests.candidate_id = candidates.id
                WHERE candidates.status = 'human_confirmed'
                  AND transfer_requests.status = 'submitted'
                  AND transfer_requests.rowid = (
                      SELECT latest.rowid
                      FROM transfer_requests AS latest
                      WHERE latest.candidate_id = candidates.id AND latest.status = 'submitted'
                      ORDER BY latest.submitted_at DESC, latest.rowid DESC
                      LIMIT 1
                  )
            """
            parameters: tuple[object, ...] = ()
            if user.role not in CENTRAL_ROLES:
                query += " AND candidates.centre_code = ?"
                parameters = (user.centre_code,)
            query += " ORDER BY candidates.created_at, candidates.rowid"
            submitted_rows = connection.execute(query, parameters).fetchall()
            dictionary_snapshot = field_dictionary_payload(connection)

        editable_headers = [
            header for header in dictionary_snapshot["headers"] if header["editable"] is True
        ]
        event_columns: dict[str, list[dict[str, object]]] = {
            event_ref: [] for event_ref in resolved_crf_mapping.allowed_fields_by_event
        }
        for header in editable_headers:
            event_columns[str(header["event_ref"])].append(
                {
                    "field_code": header["field_code"],
                    "display_header": header["display_header"],
                    "source_header": header["source_header"],
                    "revision": header["revision"],
                }
            )

        grouped_rows: dict[str, dict[tuple[str, str], dict[str, object]]] = {
            event_ref: {} for event_ref in event_columns
        }
        for row in submitted_rows:
            event_ref = row["edc_event_ref"]
            if event_ref not in grouped_rows:
                continue
            key = (row["centre_code"], row["edc_subject_ref"])
            subject_row = grouped_rows[event_ref].setdefault(
                key,
                {
                    "centre_code": row["centre_code"],
                    "edc_subject_ref": row["edc_subject_ref"],
                    "values": {},
                },
            )
            subject_row["values"][row["field_code"]] = row["final_value"]

        events = {
            event_ref: {
                "columns": columns,
                "rows": [grouped_rows[event_ref][key] for key in sorted(grouped_rows[event_ref])],
            }
            for event_ref, columns in event_columns.items()
        }
        field_mapping = [
            {
                "event_ref": header["event_ref"],
                "field_code": header["field_code"],
                "display_header": header["display_header"],
                "source_header": header["source_header"],
                "revision": header["revision"],
            }
            for header in editable_headers
        ]
        return {
            "generated_at": utc_now(),
            "scope": "ALL_CENTRES" if user.role in CENTRAL_ROLES else user.centre_code,
            "dictionary_id": resolved_crf_mapping.mapping_id,
            "dictionary_version": resolved_crf_mapping.mapping_version,
            "export_kind": "submitted",
            "export_title": "已提交临床数据导出",
            "inclusion_rule": "仅纳入 LibreClinica 已确认 submitted 的记录",
            "authority_note": "LibreClinica；本工作簿为便捷导出副本",
            "submitted_value_count": len(submitted_rows),
            "value_count": len(submitted_rows),
            "include_authority_status": False,
            "events": events,
            "field_mapping": field_mapping,
        }

    def reviewed_recognition_export_payload(user: UserContext) -> dict[str, object]:
        with database.connect() as connection:
            query = """
                SELECT candidates.centre_code, candidates.edc_subject_ref,
                       candidates.edc_event_ref, candidates.field_code,
                       candidates.final_value, candidates.created_at,
                       CASE WHEN EXISTS (
                           SELECT 1 FROM transfer_requests AS authority_transfer
                           WHERE authority_transfer.candidate_id = candidates.id
                             AND authority_transfer.status IN ('submitted', 'reconciled')
                       ) THEN 1 ELSE 0 END AS authority_submitted
                FROM candidates
                WHERE candidates.status = 'human_confirmed'
            """
            parameters: tuple[object, ...] = ()
            if user.role not in CENTRAL_ROLES:
                query += " AND candidates.centre_code = ?"
                parameters = (user.centre_code,)
            query += " ORDER BY candidates.created_at, candidates.rowid"
            reviewed_rows = connection.execute(query, parameters).fetchall()
            dictionary_snapshot = field_dictionary_payload(connection)

        used_keys = {
            (str(row["edc_event_ref"]), str(row["field_code"]))
            for row in reviewed_rows
        }
        exported_headers = [
            header
            for header in dictionary_snapshot["headers"]
            if header["editable"] is True
            and (str(header["event_ref"]), str(header["field_code"])) in used_keys
        ]
        event_columns: dict[str, list[dict[str, object]]] = {}
        for header in exported_headers:
            event_columns.setdefault(str(header["event_ref"]), []).append(
                {
                    "field_code": header["field_code"],
                    "display_header": header["display_header"],
                    "source_header": header["source_header"],
                    "revision": header["revision"],
                }
            )

        grouped_rows: dict[str, dict[tuple[str, str], dict[str, object]]] = {
            event_ref: {} for event_ref in event_columns
        }
        for row in reviewed_rows:
            event_ref = str(row["edc_event_ref"])
            if event_ref not in grouped_rows:
                continue
            key = (str(row["centre_code"]), str(row["edc_subject_ref"]))
            subject_row = grouped_rows[event_ref].setdefault(
                key,
                {
                    "centre_code": row["centre_code"],
                    "edc_subject_ref": row["edc_subject_ref"],
                    "values": {},
                    "authority_by_field": {},
                },
            )
            subject_row["values"][row["field_code"]] = row["final_value"]
            subject_row["authority_by_field"][row["field_code"]] = bool(
                row["authority_submitted"]
            )

        events: dict[str, dict[str, object]] = {}
        for event_ref, columns in event_columns.items():
            rows: list[dict[str, object]] = []
            for key in sorted(grouped_rows[event_ref]):
                subject_row = grouped_rows[event_ref][key]
                authority_states = list(subject_row.pop("authority_by_field").values())
                if authority_states and all(authority_states):
                    subject_row["authority_status"] = "all_submitted"
                elif any(authority_states):
                    subject_row["authority_status"] = "partially_submitted"
                else:
                    subject_row["authority_status"] = "not_submitted"
                rows.append(subject_row)
            events[event_ref] = {"columns": columns, "rows": rows}

        field_mapping = [
            {
                "event_ref": header["event_ref"],
                "field_code": header["field_code"],
                "display_header": header["display_header"],
                "source_header": header["source_header"],
                "revision": header["revision"],
            }
            for header in exported_headers
        ]
        return {
            "generated_at": utc_now(),
            "scope": "ALL_CENTRES" if user.role in CENTRAL_ROLES else user.centre_code,
            "dictionary_id": resolved_crf_mapping.mapping_id,
            "dictionary_version": resolved_crf_mapping.mapping_version,
            "export_kind": "reviewed_recognition",
            "export_title": (
                "本地已确认识别数据导出"
                if resolved_product_mode == "lite"
                else "已确认识别数据导出"
            ),
            "inclusion_rule": "仅纳入已人工确认的识别候选；字段列按实际识别结果生成",
            "authority_note": (
                "Lite 本地导出；未连接或写入任何外部 EDC"
                if resolved_product_mode == "lite"
                else "伴随模块导出；未提交值不是 LibreClinica 权威记录"
            ),
            "reviewed_value_count": len(reviewed_rows),
            "value_count": len(reviewed_rows),
            "include_authority_status": True,
            "authority_status_header": (
                "外部EDC状态" if resolved_product_mode == "lite" else "LibreClinica状态"
            ),
            "events": events,
            "field_mapping": field_mapping,
        }

    def reviewed_recognition_package(
        user: UserContext,
        *,
        package_passphrase: str,
    ) -> tuple[bytes, str, str]:
        """Build a portable centre package from human-confirmed values only."""

        package_created_at = utc_now()
        with database.connect() as connection:
            query = """
                SELECT candidates.centre_code, candidates.edc_subject_ref,
                       candidates.edc_event_ref, candidates.field_code,
                       candidates.final_value, candidates.unit,
                       candidates.reviewed_by, candidates.reviewed_at,
                       source_files.sha256 AS source_sha256
                FROM candidates
                JOIN source_files ON source_files.id = candidates.source_file_id
                WHERE candidates.status = 'human_confirmed'
                  AND candidates.final_value IS NOT NULL
            """
            parameters: tuple[object, ...] = ()
            if user.role not in CENTRAL_ROLES:
                query += " AND candidates.centre_code = ?"
                parameters = (user.centre_code,)
            query += " ORDER BY candidates.centre_code, candidates.edc_subject_ref, candidates.edc_event_ref, candidates.field_code, candidates.id"
            rows = connection.execute(query, parameters).fetchall()
            release = active_dictionary_release(connection)
            audit_verification = database.verify_audit_chain(connection)
            if not audit_verification.ok:
                raise OfflinePackageError("offline_package_audit_chain_invalid")
            audit_anchor = make_anchor(
                audit_verification.head_hash,
                audit_verification.checked,
                package_created_at,
            )
        records = [
            {
                "centre_code": row["centre_code"],
                "edc_subject_ref": row["edc_subject_ref"],
                "edc_event_ref": row["edc_event_ref"],
                "field_code": row["field_code"],
                "final_value": row["final_value"],
                "unit": row["unit"],
                "source_sha256": row["source_sha256"],
                "reviewed_at": row["reviewed_at"] or "unknown",
            }
            for row in rows
        ]
        centres = {str(record["centre_code"]) for record in records}
        if user.role in CENTRAL_ROLES and len(centres) > 1:
            raise ValueError("offline_package_centre_scope_required")
        package_centre = user.centre_code if user.role not in CENTRAL_ROLES else (
            str(records[0]["centre_code"]) if records else "CENTRAL"
        )
        return build_encrypted_reviewed_package(
            passphrase=package_passphrase,
            centre_code=package_centre,
            dictionary_id=resolved_crf_mapping.mapping_id,
            dictionary_version=str(release["version"]),
            created_by=user.username,
            created_at=package_created_at,
            records=records,
            audit_anchor=audit_anchor,
        )

    def write_offline_package_log(
        *,
        user: UserContext,
        source_filename: str,
        result: str,
        package_sha256: str | None = None,
        package_id: str | None = None,
        centre_code: str | None = None,
        dictionary_id: str | None = None,
        dictionary_version: str | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
        record_count: int = 0,
        created_count: int = 0,
        duplicate_count: int = 0,
    ) -> None:
        with database.connect() as connection:
            connection.execute(
                """
                INSERT INTO offline_package_import_logs (
                    id, package_sha256, package_id, centre_code, source_filename,
                    dictionary_id, dictionary_version, result, error_code, error_detail,
                    record_count, created_count, duplicate_count, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()), package_sha256, package_id, centre_code,
                    Path(source_filename).name[:200], dictionary_id, dictionary_version,
                    result, error_code, (error_detail or "")[:500], record_count,
                    created_count, duplicate_count, user.username, utc_now(),
                ),
            )

    def audit(
        connection: sqlite3.Connection,
        *,
        candidate_id: str | None,
        centre_code: str,
        event_type: str,
        actor_username: str,
        details: dict[str, object],
    ) -> None:
        database.append_audit_event(
            connection,
            candidate_id=candidate_id,
            centre_code=centre_code,
            event_type=event_type,
            actor_username=actor_username,
            details=details,
        )

    def evaluate_and_store_quality(
        connection: sqlite3.Connection,
        candidate: Mapping[str, object],
        *,
        value: str,
        unit: str | None,
        actor_username: str,
    ) -> dict[str, object]:
        assessment = assess_candidate(
            resolved_quality_rules,
            event_ref=str(candidate["edc_event_ref"]),
            field_code=str(candidate["field_code"]),
            value=value,
            unit=unit,
        )
        evaluated_at = utc_now()
        assessment_id = str(uuid4())
        connection.execute(
            """
            INSERT INTO quality_findings (
                id, candidate_id, centre_code, rule_version, status, findings_json,
                evaluated_value, evaluated_unit, evaluated_by, evaluated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                assessment_id,
                candidate["id"],
                candidate["centre_code"],
                assessment["rule_version"],
                assessment["status"],
                json.dumps(assessment["findings"], ensure_ascii=False, sort_keys=True),
                value,
                unit,
                actor_username,
                evaluated_at,
            ),
        )
        audit(
            connection,
            candidate_id=str(candidate["id"]),
            centre_code=str(candidate["centre_code"]),
            event_type="candidate_quality_evaluated",
            actor_username=actor_username,
            details={
                "assessment_id": assessment_id,
                "status": assessment["status"],
                "rule_version": assessment["rule_version"],
                "finding_codes": [finding["code"] for finding in assessment["findings"]],
            },
        )
        return {
            "id": assessment_id,
            "candidate_id": candidate["id"],
            **assessment,
            "evaluated_value": value,
            "evaluated_unit": unit,
            "evaluated_by": actor_username,
            "evaluated_at": evaluated_at,
        }

    def latest_quality_assessment(
        connection: sqlite3.Connection,
        candidate: Mapping[str, object],
    ) -> dict[str, object]:
        row = connection.execute(
            """
            SELECT * FROM quality_findings
            WHERE candidate_id = ?
            ORDER BY evaluated_at DESC, rowid DESC
            LIMIT 1
            """,
            (candidate["id"],),
        ).fetchone()
        if row is None:
            return evaluate_and_store_quality(
                connection,
                candidate,
                value=str(candidate["final_value"] or candidate["proposed_value"]),
                unit=candidate["unit"],
                actor_username="system:quality-rules",
            )
        return {
            "id": row["id"],
            "candidate_id": row["candidate_id"],
            "status": row["status"],
            "rule_version": row["rule_version"],
            "event_ref": candidate["edc_event_ref"],
            "field_code": candidate["field_code"],
            "findings": json.loads(row["findings_json"]),
            "evaluated_value": row["evaluated_value"],
            "evaluated_unit": row["evaluated_unit"],
            "evaluated_by": row["evaluated_by"],
            "evaluated_at": row["evaluated_at"],
        }

    def get_data_issue(connection: sqlite3.Connection, issue_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM data_issues WHERE id = ?", (issue_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
        return row

    def create_or_reopen_task(
        connection: sqlite3.Connection,
        *,
        centre_code: str,
        task_type: str,
        assigned_role: str,
        title: str,
        dedupe_key: str,
        candidate_id: str | None = None,
        transfer_id: str | None = None,
        data_issue_id: str | None = None,
    ) -> sqlite3.Row:
        task_id = str(uuid4())
        created_at = utc_now()
        connection.execute(
            """
            INSERT INTO tasks (
                id, centre_code, task_type, status, assigned_role, candidate_id,
                transfer_id, data_issue_id, title, dedupe_key, created_at
            ) VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dedupe_key) DO UPDATE SET
                status = 'open', completed_by = NULL, completed_at = NULL,
                completion_note = NULL
            """,
            (
                task_id,
                centre_code,
                task_type,
                assigned_role,
                candidate_id,
                transfer_id,
                data_issue_id,
                title,
                dedupe_key,
                created_at,
            ),
        )
        return connection.execute("SELECT * FROM tasks WHERE dedupe_key = ?", (dedupe_key,)).fetchone()

    def complete_tasks_for_reference(
        connection: sqlite3.Connection,
        *,
        data_issue_id: str | None = None,
        transfer_id: str | None = None,
        actor_username: str,
        note: str,
    ) -> None:
        if data_issue_id is None and transfer_id is None:
            return
        clauses = ["status = 'open'"]
        parameters: list[object] = []
        if data_issue_id is not None:
            clauses.append("data_issue_id = ?")
            parameters.append(data_issue_id)
        if transfer_id is not None:
            clauses.append("transfer_id = ?")
            parameters.append(transfer_id)
        parameters.extend((actor_username, utc_now(), note))
        connection.execute(
            f"""
            UPDATE tasks SET completed_by = ?, completed_at = ?, completion_note = ?, status = 'completed'
            WHERE {' AND '.join(clauses)}
            """,
            (*parameters[-3:], *parameters[:-3]),
        )

    def transfer_hold_scope_key(
        scope: str,
        centre_code: str | None,
        subject_ref: str | None,
        event_ref: str | None,
    ) -> str:
        if scope == "dataset" and not any((centre_code, subject_ref, event_ref)):
            return "dataset"
        if scope == "centre" and centre_code and not any((subject_ref, event_ref)):
            return f"centre:{centre_code}"
        if scope == "subject" and centre_code and subject_ref and not event_ref:
            return f"subject:{centre_code}:{subject_ref}"
        if scope == "visit" and centre_code and subject_ref and event_ref:
            return f"visit:{centre_code}:{subject_ref}:{event_ref}"
        raise HTTPException(status_code=422, detail="invalid_transfer_hold_scope")

    def effective_transfer_holds(
        connection: sqlite3.Connection,
        *,
        centre_code: str,
        subject_ref: str,
        event_ref: str,
    ) -> list[dict[str, object]]:
        scope_keys = (
            "dataset",
            f"centre:{centre_code}",
            f"subject:{centre_code}:{subject_ref}",
            f"visit:{centre_code}:{subject_ref}:{event_ref}",
        )
        rows = connection.execute(
            """
            SELECT * FROM transfer_holds
            WHERE scope_key IN (?, ?, ?, ?)
            ORDER BY created_at, rowid
            """,
            scope_keys,
        ).fetchall()
        latest_by_scope = {row["scope_key"]: row for row in rows}
        return [
            {**row_to_dict(row), "effective": True, "authority_workflow": "formal_locks_remain_in_libreclinica"}
            for row in latest_by_scope.values()
            if row["action"] == "held"
        ]

    def assert_no_transfer_hold(connection: sqlite3.Connection, candidate: Mapping[str, object]) -> None:
        holds = effective_transfer_holds(
            connection,
            centre_code=str(candidate["centre_code"]),
            subject_ref=str(candidate["edc_subject_ref"]),
            event_ref=str(candidate["edc_event_ref"]),
        )
        if holds:
            raise HTTPException(status_code=409, detail="transfer_hold_active")

    def run_transfer_readback(transfer_id: str, actor_username: str) -> dict[str, object]:
        with database.connect() as connection:
            transfer = connection.execute(
                "SELECT * FROM transfer_requests WHERE id = ?",
                (transfer_id,),
            ).fetchone()
            if transfer is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
            if transfer["status"] != "submitted":
                raise HTTPException(status_code=409, detail="transfer_not_submitted")
            try:
                package = json.loads(transfer["package_json"])
                expected_value = str(package["value"]["final_value"])
            except (json.JSONDecodeError, KeyError, TypeError):
                raise HTTPException(status_code=409, detail="transfer_package_not_available")

        read_value = getattr(resolved_edc_adapter, "read_value", None)
        if callable(read_value):
            try:
                result = read_value(package)
            except EdcAdapterError:
                result = EdcReadbackResult(status="failed")
        else:
            result = EdcReadbackResult(status="unsupported")

        readback_status = {
            "matched": "verified",
            "mismatch": "mismatch",
            "unsupported": "unsupported",
            "failed": "failed",
        }.get(result.status, "failed")
        observed_value = None if result.observed_value is None else str(result.observed_value)[:200]
        response_sha256 = (
            result.response_sha256
            if result.response_sha256 is not None and SHA256_RE.fullmatch(result.response_sha256)
            else None
        )
        checked_at = utc_now()
        with database.connect() as connection:
            current = connection.execute(
                "SELECT * FROM transfer_requests WHERE id = ?",
                (transfer_id,),
            ).fetchone()
            if current is None or current["status"] != "submitted":
                raise HTTPException(status_code=409, detail="transfer_not_submitted")
            attempt_count = current["readback_attempt_count"] + 1
            connection.execute(
                """
                UPDATE transfer_requests
                SET readback_status = ?, readback_checked_at = ?, readback_attempt_count = ?,
                    readback_observed_value = ?, readback_response_sha256 = ?, updated_at = ?
                WHERE id = ? AND status = 'submitted'
                """,
                (
                    readback_status,
                    checked_at,
                    attempt_count,
                    observed_value,
                    response_sha256,
                    checked_at,
                    transfer_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO readback_checks (
                    id, transfer_id, candidate_id, centre_code, status, expected_value,
                    observed_value, response_sha256, checked_by, checked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    transfer_id,
                    current["candidate_id"],
                    current["centre_code"],
                    readback_status,
                    expected_value,
                    observed_value,
                    response_sha256,
                    actor_username,
                    checked_at,
                ),
            )
            audit(
                connection,
                candidate_id=current["candidate_id"],
                centre_code=current["centre_code"],
                event_type=f"authority_readback_{readback_status}",
                actor_username=actor_username,
                details={
                    "transfer_id": transfer_id,
                    "readback_status": readback_status,
                    "attempt_count": attempt_count,
                    "response_sha256": response_sha256,
                },
            )
            if readback_status == "mismatch":
                create_or_reopen_task(
                    connection,
                    centre_code=current["centre_code"],
                    task_type="readback_mismatch",
                    assigned_role="central_data_manager",
                    title="Reconcile Authority EDC read-back mismatch",
                    dedupe_key=f"readback-mismatch:{transfer_id}",
                    candidate_id=current["candidate_id"],
                    transfer_id=transfer_id,
                )
            elif readback_status == "verified":
                complete_tasks_for_reference(
                    connection,
                    transfer_id=transfer_id,
                    actor_username=actor_username,
                    note="Authority EDC read-back matched the frozen transfer value.",
                )
            updated = connection.execute(
                "SELECT * FROM transfer_requests WHERE id = ?",
                (transfer_id,),
            ).fetchone()
        return transfer_payload(updated)

    def get_candidate(connection: sqlite3.Connection, candidate_id: str) -> sqlite3.Row:
        row = connection.execute(f"{candidate_select_sql()} WHERE candidates.id = ?", (candidate_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
        return row

    def stored_source_path(source_file: sqlite3.Row) -> Path:
        if source_file["content_purged_at"]:
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="source_file_content_expired")
        suffix = Path(source_file["storage_key"]).suffix
        if source_file["storage_key"].startswith("synthetic/"):
            directory = "synthetic_uploads"
        elif source_file["storage_key"].startswith("deidentified/"):
            directory = "deidentified_uploads"
        elif source_file["storage_key"].startswith("offline-package/"):
            directory = "offline_packages"
        else:
            raise HTTPException(status_code=409, detail="local_source_file_required")
        return (
            database.database_path.parent
            / directory
            / source_file["centre_code"]
            / f"{source_file['id']}{suffix}"
        )

    def get_deidentification_draft(
        connection: sqlite3.Connection,
        draft_id: str,
    ) -> tuple[sqlite3.Row, sqlite3.Row]:
        draft = connection.execute(
            "SELECT * FROM deidentification_drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
        derivative = connection.execute(
            "SELECT * FROM source_files WHERE id = ?",
            (draft["derivative_source_file_id"],),
        ).fetchone()
        if derivative is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="deidentified_derivative_not_found")
        return draft, derivative

    def assert_source_ready_for_candidates(
        connection: sqlite3.Connection,
        source_file: sqlite3.Row,
    ) -> None:
        if not source_file["storage_key"].startswith("deidentified/"):
            return
        draft = connection.execute(
            "SELECT * FROM deidentification_drafts WHERE derivative_source_file_id = ?",
            (source_file["id"],),
        ).fetchone()
        if draft is None or draft["status"] != "confirmed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="deidentification_confirmation_required",
            )

    def production_readiness_payload() -> dict[str, object]:
        backup_directory = Path(
            os.getenv("COMPANION_BACKUP_DIRECTORY", str(database.database_path.parent / "backups"))
        )
        latest_backup_completed_at: str | None = None
        backup_restore_evidence = False
        try:
            evidence_paths = sorted(
                backup_directory.glob("companion-*.evidence.json"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if evidence_paths and evidence_paths[0].stat().st_size <= 64 * 1024:
                evidence = json.loads(evidence_paths[0].read_text(encoding="utf-8"))
                backup_path = backup_directory / str(evidence.get("backup_filename") or "")
                completed_at = datetime.fromisoformat(str(evidence.get("completed_at") or "").replace("Z", "+00:00"))
                max_age_hours = float(os.getenv("COMPANION_BACKUP_MAX_AGE_HOURS", "48"))
                backup_age_hours = (datetime.now(UTC) - completed_at.astimezone(UTC)).total_seconds() / 3600
                backup_restore_evidence = bool(
                    evidence.get("restore_integrity_check") == "ok"
                    and SHA256_RE.fullmatch(str(evidence.get("backup_sha256") or ""))
                    and backup_path.is_file()
                    and backup_age_hours <= max_age_hours
                )
                latest_backup_completed_at = str(evidence.get("completed_at") or "") or None
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            backup_restore_evidence = False
        disk_status = disk_encryption_status(database.database_path)
        manifest = load_evidence_manifest()
        readiness = evaluate_production_readiness(
            environment=resolved_environment,
            deployment_profile=runtime_config.deployment_profile,
            database_backend=runtime_config.database_backend,
            authority_target_kind=resolved_edc_adapter.target_kind,
            backup_restore_evidence=backup_restore_evidence,
            disk_encryption_enabled=disk_status.get("status") == "enabled",
            manifest=manifest,
        )
        with database.connect() as connection:
            audit_verification = database.verify_audit_chain(connection).as_dict()
        readiness["gates"]["audit_chain_integrity"] = audit_verification["ok"]
        if not audit_verification["ok"]:
            readiness["blocking_reasons"]["audit_chain_integrity"] = str(
                audit_verification["reason"] or "audit_chain_verification_failed"
            )
            readiness["status"] = "BLOCK"
        return {
            **readiness,
            "environment": resolved_environment,
            "disk_encryption": disk_status,
            "audit_chain": audit_verification,
            "latest_backup_completed_at": latest_backup_completed_at,
            "meaning": "localhost qualification does not establish production validation",
        }

    @app.get("/api/health")
    def health() -> dict[str, object]:
        with database.connect() as connection:
            release = active_dictionary_release(connection)
        kimi_configuration = kimi_status_payload(resolved_kimi_client)
        return {
            "status": "ok",
            "application_version": __version__,
            "environment": resolved_environment,
            "product_mode": resolved_product_mode,
            "deployment_profile": runtime_config.deployment_profile,
            "database_backend": runtime_config.database_backend,
            "database_schema_version": database.current_schema_version(),
            "centre_profile": (
                resolved_centre_profile.public_payload() if resolved_centre_profile is not None else None
            ),
            "setup_required": centre_setup_required(),
            "data_boundary": "synthetic_only",
            "edc_adapter": (
                "fail_closed_simulation_only"
                if resolved_edc_adapter.target_kind == "not_configured"
                else resolved_edc_adapter.mode
            ),
            "kimi_integration": kimi_configuration["status"],
            "kimi_default_enabled": resolved_kimi_client.enabled,
            "kimi_model": resolved_kimi_client.settings.model,
            "kimi_data_boundary": "confirmed_deidentified_derivative_only",
            "original_retention_days": configured_retention_days,
            "disk_encryption": disk_encryption_status(database.database_path),
            "local_ocr": "local_only",
            "local_deidentification": "draft_preview_human_confirmation_required",
            "chinese_lab_alias_mapping": (
                getattr(resolved_lab_extractor, "mapping_version", "explicit_test_double")
                if resolved_lab_extractor is not None
                else "disabled"
            ),
            "crf_mapping_id": resolved_crf_mapping.mapping_id,
            "crf_mapping_version": resolved_crf_mapping.mapping_version,
            "quality_rule_version": resolved_quality_rules["version"],
            "active_dictionary_release": {
                "id": release["id"],
                "version": release["version"],
            },
            "excel_export": "ready" if getattr(resolved_spreadsheet_exporter, "ready", False) else "unavailable",
            "production_readiness": production_readiness_payload(),
        }

    @app.get("/api/edc-adapter/readiness")
    def edc_adapter_readiness() -> dict[str, object]:
        return resolved_edc_adapter.readiness()

    @app.get("/api/security/disk-encryption")
    def security_disk_encryption(
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        return disk_encryption_status(database.database_path)

    @app.get("/api/security/retention")
    def security_retention(
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        with database.connect() as connection:
            purged_count = connection.execute(
                "SELECT count(*) AS count FROM source_files WHERE content_purged_at IS NOT NULL"
            ).fetchone()["count"]
        return {
            "original_retention_days": configured_retention_days,
            "purged_source_count": int(purged_count),
            "cleanup_command": "scripts/cleanup_expired_originals.py --execute",
            "policy": "hash_and_audit_retained_physical_source_removed_after_expiry",
        }

    @app.get("/api/audit-chain/verify")
    def audit_chain_verify(
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        if user.role not in GLOBAL_READ_ROLES:
            raise HTTPException(status_code=403, detail="global_read_role_required")
        with database.connect() as connection:
            return database.verify_audit_chain(connection).as_dict()

    @app.get("/api/audit-chain/anchor")
    def audit_chain_anchor(
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        if user.role not in CENTRAL_ROLES:
            raise HTTPException(status_code=403, detail="central_role_required")
        with database.connect() as connection:
            verification = database.verify_audit_chain(connection)
        if not verification.ok:
            raise HTTPException(status_code=409, detail="audit_chain_verification_failed")
        return make_anchor(verification.head_hash, verification.checked, utc_now())

    @app.get("/api/setup/status")
    def setup_status() -> dict[str, object]:
        return {
            "required": centre_setup_required(),
            "centre_profile": (
                resolved_centre_profile.public_payload() if resolved_centre_profile is not None else None
            ),
        }

    @app.post("/api/setup/complete")
    def complete_setup(payload: SetupCompletePayload) -> dict[str, object]:
        if resolved_centre_profile is None:
            raise HTTPException(status_code=409, detail="centre_profile_required")
        if payload.password != payload.password_confirmation:
            raise HTTPException(status_code=422, detail="password_confirmation_mismatch")
        if not strong_password(payload.password):
            raise HTTPException(status_code=422, detail="strong_password_required")
        with database.connect() as connection:
            updated = connection.execute(
                """
                UPDATE users SET password_hash = ?
                WHERE username = ? AND centre_code = ? AND role = 'site_investigator'
                  AND active = 1 AND password_hash = ?
                """,
                (
                    password_hash(payload.password),
                    resolved_centre_profile.username,
                    resolved_centre_profile.centre_code,
                    SETUP_REQUIRED_PASSWORD_HASH,
                ),
            )
            if updated.rowcount != 1:
                raise HTTPException(status_code=409, detail="setup_already_completed")
            audit(
                connection,
                candidate_id=None,
                centre_code=resolved_centre_profile.centre_code,
                event_type="centre_account_initialized",
                actor_username=resolved_centre_profile.username,
                details={"profile_version": 1},
            )
        return {
            "status": "completed",
            "username": resolved_centre_profile.username,
            "centre_code": resolved_centre_profile.centre_code,
        }

    @app.get("/api/admin/users")
    def list_users(
        user: Annotated[UserContext, Depends(current_user)],
    ) -> list[dict[str, object]]:
        require_central_data_manager(user)
        with database.connect() as connection:
            rows = connection.execute(
                "SELECT id, username, centre_code, role, active FROM users ORDER BY username"
            ).fetchall()
        return [
            {
                "id": row["id"],
                "username": row["username"],
                "centre_code": row["centre_code"],
                "role": row["role"],
                "active": bool(row["active"]),
            }
            for row in rows
        ]

    @app.post("/api/admin/users", status_code=status.HTTP_201_CREATED)
    def create_user_account(
        payload: UserCreatePayload,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_central_data_manager(user)
        if resolved_environment not in {"test", "development"}:
            raise HTTPException(status_code=409, detail="production_identity_provider_required")
        if payload.role == "site_investigator" and payload.centre_code is None:
            raise HTTPException(status_code=422, detail="centre_code_required")
        if payload.role in READ_ONLY_ROLES and payload.centre_code is not None:
            raise HTTPException(status_code=422, detail="read_only_role_is_global")
        bootstrap_password = secrets.token_urlsafe(16)
        account_id = str(uuid4())
        with database.connect() as connection:
            existing = connection.execute(
                "SELECT 1 FROM users WHERE username = ?",
                (payload.username,),
            ).fetchone()
            if existing is not None:
                raise HTTPException(status_code=409, detail="username_already_exists")
            connection.execute(
                """
                INSERT INTO users (id, username, password_hash, centre_code, role, active)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (
                    account_id,
                    payload.username,
                    password_hash(bootstrap_password),
                    payload.centre_code,
                    payload.role,
                ),
            )
            audit(
                connection,
                candidate_id=None,
                centre_code=payload.centre_code or "CENTRAL",
                event_type="user_account_created",
                actor_username=user.username,
                details={
                    "user_id": account_id,
                    "username": payload.username,
                    "role": payload.role,
                    "centre_code": payload.centre_code,
                },
            )
        return {
            "id": account_id,
            "username": payload.username,
            "centre_code": payload.centre_code,
            "role": payload.role,
            "active": True,
            "bootstrap_password": bootstrap_password,
            "bootstrap_password_visibility": "returned_once_synthetic_environment_only",
        }

    @app.post("/api/admin/centre-accounts", status_code=status.HTTP_201_CREATED)
    def create_centre_accounts(
        payload: CentreAccountBatchPayload,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_central_data_manager(user)
        if resolved_environment not in {"test", "development"}:
            raise HTTPException(status_code=409, detail="production_identity_provider_required")
        created: list[dict[str, object]] = []
        with database.connect() as connection:
            for item in payload.accounts:
                existing = connection.execute(
                    "SELECT 1 FROM users WHERE username = ? OR centre_code = ?",
                    (item.username, item.centre_code),
                ).fetchone()
                if existing is not None:
                    raise HTTPException(status_code=409, detail="centre_or_username_already_exists")
            for item in payload.accounts:
                account_id = str(uuid4())
                bootstrap_password = secrets.token_urlsafe(18)
                connection.execute(
                    """
                    INSERT INTO users (id, username, password_hash, centre_code, role, active)
                    VALUES (?, ?, ?, ?, 'site_investigator', 1)
                    """,
                    (
                        account_id,
                        item.username,
                        password_hash(bootstrap_password),
                        item.centre_code,
                    ),
                )
                audit(
                    connection,
                    candidate_id=None,
                    centre_code=item.centre_code,
                    event_type="centre_account_created",
                    actor_username=user.username,
                    details={"user_id": account_id, "username": item.username, "centre_code": item.centre_code},
                )
                created.append(
                    {
                        "id": account_id,
                        "username": item.username,
                        "centre_code": item.centre_code,
                        "role": "site_investigator",
                        "bootstrap_password": bootstrap_password,
                    }
                )
        return {"accounts": created, "password_visibility": "returned_once_synthetic_environment_only"}

    def set_user_account_active(
        account_id: str,
        active: bool,
        actor: UserContext,
    ) -> dict[str, object]:
        require_central_data_manager(actor)
        with database.connect() as connection:
            account = connection.execute(
                "SELECT id, username, centre_code, role, active FROM users WHERE id = ?",
                (account_id,),
            ).fetchone()
            if account is None:
                raise HTTPException(status_code=404, detail="not_found")
            if account["role"] in CENTRAL_ROLES:
                raise HTTPException(status_code=409, detail="central_account_lifecycle_protected")
            connection.execute("UPDATE users SET active = ? WHERE id = ?", (int(active), account_id))
            if not active:
                connection.execute("DELETE FROM sessions WHERE user_id = ?", (account_id,))
            audit(
                connection,
                candidate_id=None,
                centre_code=account["centre_code"] or "CENTRAL",
                event_type="user_account_reactivated" if active else "user_account_deactivated",
                actor_username=actor.username,
                details={
                    "user_id": account_id,
                    "username": account["username"],
                    "role": account["role"],
                },
            )
        return {
            "id": account["id"],
            "username": account["username"],
            "centre_code": account["centre_code"],
            "role": account["role"],
            "active": active,
        }

    @app.post("/api/admin/users/{account_id}/deactivate")
    def deactivate_user_account(
        account_id: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        return set_user_account_active(account_id, False, user)

    @app.post("/api/admin/users/{account_id}/reactivate")
    def reactivate_user_account(
        account_id: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        return set_user_account_active(account_id, True, user)

    @app.get("/api/admin/dictionary-releases")
    def list_dictionary_releases(
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_central_data_manager(user)
        with database.connect() as connection:
            active = active_dictionary_release(connection)
            releases = connection.execute(
                "SELECT * FROM dictionary_releases ORDER BY created_at, rowid"
            ).fetchall()
            return {
                "active_release_id": active["id"],
                "releases": [dictionary_release_payload(connection, row) for row in releases],
            }

    @app.post("/api/admin/dictionary-releases/draft", status_code=status.HTTP_201_CREATED)
    def create_dictionary_release_draft(
        response: Response,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_central_data_manager(user)
        with database.connect() as connection:
            ensure_dictionary_baseline(connection)
            existing = connection.execute(
                "SELECT * FROM dictionary_releases WHERE status = 'draft' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if existing is not None:
                response.status_code = status.HTTP_200_OK
                return dictionary_release_payload(connection, existing)
            draft = create_dictionary_draft_record(connection, actor_username=user.username)
            audit(
                connection,
                candidate_id=None,
                centre_code="CENTRAL",
                event_type="dictionary_release_draft_created",
                actor_username=user.username,
                details={"release_id": draft["id"], "base_release_id": draft["base_release_id"]},
            )
            return dictionary_release_payload(connection, draft)

    @app.put("/api/admin/dictionary-releases/{release_id}/items/{event_ref}/{field_code}")
    def update_dictionary_release_item(
        release_id: str,
        event_ref: str,
        field_code: str,
        payload: FieldHeaderUpdatePayload,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_central_data_manager(user)
        event_ref = event_ref.upper()
        field_code = field_code.upper()
        try:
            resolved_crf_mapping.assert_allowed(event_ref, (field_code,))
        except CrfMappingError as error:
            raise HTTPException(status_code=404, detail="field_header_not_found") from error
        with database.connect() as connection:
            release = connection.execute(
                "SELECT * FROM dictionary_releases WHERE id = ?",
                (release_id,),
            ).fetchone()
            if release is None:
                raise HTTPException(status_code=404, detail="not_found")
            if release["status"] != "draft":
                raise HTTPException(status_code=409, detail="dictionary_release_not_draft")
            updated = connection.execute(
                """
                UPDATE dictionary_release_items SET display_header = ?
                WHERE release_id = ? AND event_ref = ? AND field_code = ?
                """,
                (payload.display_header, release_id, event_ref, field_code),
            )
            if updated.rowcount != 1:
                raise HTTPException(status_code=404, detail="field_header_not_found")
            audit(
                connection,
                candidate_id=None,
                centre_code="CENTRAL",
                event_type="dictionary_release_item_updated",
                actor_username=user.username,
                details={
                    "release_id": release_id,
                    "event_ref": event_ref,
                    "field_code": field_code,
                    "display_header": payload.display_header,
                },
            )
        return {
            "release_id": release_id,
            "event_ref": event_ref,
            "field_code": field_code,
            "display_header": payload.display_header,
        }

    @app.post("/api/admin/dictionary-releases/{release_id}/publish")
    def publish_dictionary_release(
        release_id: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_central_data_manager(user)
        with database.connect() as connection:
            published = publish_dictionary_release_record(
                connection,
                release_id=release_id,
                actor_username=user.username,
            )
            return dictionary_release_payload(connection, published)

    @app.post(
        "/api/admin/dictionary-releases/{release_id}/rollback",
        status_code=status.HTTP_201_CREATED,
    )
    def rollback_dictionary_release(
        release_id: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_central_data_manager(user)
        with database.connect() as connection:
            source = connection.execute(
                "SELECT * FROM dictionary_releases WHERE id = ?",
                (release_id,),
            ).fetchone()
            if source is None:
                raise HTTPException(status_code=404, detail="not_found")
            if source["status"] != "published":
                raise HTTPException(status_code=409, detail="dictionary_release_not_published")
            rollback = create_dictionary_draft_record(
                connection,
                actor_username=user.username,
                rollback_of=release_id,
                source_release_id=release_id,
                version_prefix="rollback",
            )
            published = publish_dictionary_release_record(
                connection,
                release_id=rollback["id"],
                actor_username=user.username,
            )
            return dictionary_release_payload(connection, published)

    @app.get("/api/recognition-fields")
    def list_recognition_fields(
        event_ref: Annotated[str, Query(pattern=r"^[A-Z][A-Z0-9_-]{1,63}$")],
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_workflow_write_role(user)
        recognition_field_scope(event_ref, None)
        with database.connect() as connection:
            dictionary_snapshot = field_dictionary_payload(connection)
        fields = [
            {
                "field_code": header["field_code"],
                "display_header": header["display_header"],
                "source_header": header["source_header"],
                "category": (
                    "pulmonary_function"
                    if str(header["field_code"]).startswith("PFT_")
                    else "laboratory"
                ),
            }
            for header in dictionary_snapshot["headers"]
            if header["event_ref"] == event_ref and header["editable"] is True
        ]
        return {
            "event_ref": event_ref,
            "dictionary_id": dictionary_snapshot["dictionary_id"],
            "dictionary_version": dictionary_snapshot["dictionary_version"],
            "fields": fields,
        }

    def load_recognition_job(
        connection: sqlite3.Connection,
        job_id: str,
        user: UserContext,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM recognition_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="recognition_job_not_found")
        assert_centre_access(user, str(row["centre_code"]))
        return row

    def refresh_recognition_job_status(connection: sqlite3.Connection, job_id: str, now: str) -> sqlite3.Row:
        counts = connection.execute(
            """
            SELECT
              COUNT(*) AS item_count,
              SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) AS completed_count,
              SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
              SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_count,
              SUM(CASE WHEN status IN ('queued', 'running') THEN 1 ELSE 0 END) AS active_count
            FROM recognition_job_items
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()
        item_count = int(counts["item_count"] or 0)
        completed_count = int(counts["completed_count"] or 0)
        failed_count = int(counts["failed_count"] or 0)
        cancelled_count = int(counts["cancelled_count"] or 0)
        active_count = int(counts["active_count"] or 0)
        if cancelled_count == item_count and item_count:
            job_status = "cancelled"
        elif completed_count == item_count and item_count:
            job_status = "succeeded"
        elif active_count:
            job_status = "running" if completed_count or failed_count else "queued"
        elif failed_count:
            job_status = "failed"
        else:
            job_status = "queued"
        connection.execute(
            """
            UPDATE recognition_jobs
            SET status = ?, item_count = ?, completed_count = ?, failed_count = ?, updated_at = ?
            WHERE id = ?
            """,
            (job_status, item_count, completed_count, failed_count, now, job_id),
        )
        return connection.execute("SELECT * FROM recognition_jobs WHERE id = ?", (job_id,)).fetchone()

    @app.post("/api/recognition-jobs", status_code=status.HTTP_201_CREATED)
    def create_recognition_job(
        payload: RecognitionJobCreatePayload,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_workflow_write_role(user)
        source_ids = [item.source_file_id for item in payload.items]
        if len(source_ids) != len(set(source_ids)):
            raise HTTPException(status_code=422, detail="recognition_job_duplicate_source")
        now = utc_now()
        job_id = str(uuid4())
        with database.connect() as connection:
            source_rows: list[sqlite3.Row] = []
            for item in payload.items:
                source = connection.execute(
                    "SELECT * FROM source_files WHERE id = ?",
                    (item.source_file_id,),
                ).fetchone()
                if source is None:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="source_file_not_found")
                assert_centre_access(user, str(source["centre_code"]))
                recognition_field_scope(item.edc_event_ref, item.field_codes)
                source_rows.append(source)
            centres = {str(source["centre_code"]) for source in source_rows}
            if len(centres) != 1:
                raise HTTPException(status_code=422, detail="recognition_job_multiple_centres")
            centre_code = next(iter(centres))
            connection.execute(
                """
                INSERT INTO recognition_jobs (
                    id, centre_code, status, item_count, completed_count, failed_count,
                    created_by, created_at, updated_at
                ) VALUES (?, ?, 'queued', ?, 0, 0, ?, ?, ?)
                """,
                (job_id, centre_code, len(payload.items), user.username, now, now),
            )
            for item in payload.items:
                connection.execute(
                    """
                    INSERT INTO recognition_job_items (
                        id, job_id, source_file_id, centre_code, edc_subject_ref,
                        edc_event_ref, field_codes_json, use_kimi, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)
                    """,
                    (
                        str(uuid4()),
                        job_id,
                        item.source_file_id,
                        centre_code,
                        item.edc_subject_ref,
                        item.edc_event_ref,
                        json.dumps(item.field_codes, ensure_ascii=False) if item.field_codes else None,
                        int(item.use_kimi),
                        now,
                    ),
                )
            audit(
                connection,
                candidate_id=None,
                centre_code=centre_code,
                event_type="recognition_job_created",
                actor_username=user.username,
                details={"job_id": job_id, "item_count": len(payload.items)},
            )
            row = connection.execute("SELECT * FROM recognition_jobs WHERE id = ?", (job_id,)).fetchone()
            return recognition_job_payload(connection, row)

    @app.get("/api/recognition-jobs")
    def list_recognition_jobs(user: Annotated[UserContext, Depends(current_user)]) -> list[dict[str, object]]:
        with database.connect() as connection:
            if user.role in CENTRAL_ROLES | GLOBAL_READ_ROLES:
                rows = connection.execute(
                    "SELECT * FROM recognition_jobs ORDER BY created_at DESC, id DESC"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM recognition_jobs WHERE centre_code = ? ORDER BY created_at DESC, id DESC",
                    (user.centre_code,),
                ).fetchall()
            return [recognition_job_payload(connection, row) for row in rows]

    @app.get("/api/recognition-jobs/{job_id}")
    def get_recognition_job(
        job_id: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        with database.connect() as connection:
            row = load_recognition_job(connection, job_id, user)
            return recognition_job_payload(connection, row)

    @app.post("/api/recognition-jobs/{job_id}/cancel")
    def cancel_recognition_job(
        job_id: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_workflow_write_role(user)
        now = utc_now()
        with database.connect() as connection:
            row = load_recognition_job(connection, job_id, user)
            if row["status"] == "running":
                raise HTTPException(status_code=409, detail="recognition_job_running")
            if row["status"] in {"succeeded", "failed", "cancelled"}:
                raise HTTPException(status_code=409, detail="recognition_job_not_cancellable")
            claimed = connection.execute(
                """
                UPDATE recognition_jobs
                SET cancelled_by = ?, cancelled_at = ?, updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (user.username, now, now, job_id),
            )
            if claimed.rowcount != 1:
                latest = connection.execute(
                    "SELECT status FROM recognition_jobs WHERE id = ?",
                    (job_id,),
                ).fetchone()
                if latest is not None and latest["status"] == "running":
                    raise HTTPException(status_code=409, detail="recognition_job_running")
                raise HTTPException(status_code=409, detail="recognition_job_not_cancellable")
            connection.execute(
                "UPDATE recognition_job_items SET status = 'cancelled', finished_at = ? WHERE job_id = ? AND status = 'queued'",
                (now, job_id),
            )
            row = refresh_recognition_job_status(connection, job_id, now)
            audit(
                connection,
                candidate_id=None,
                centre_code=row["centre_code"],
                event_type="recognition_job_cancelled",
                actor_username=user.username,
                details={"job_id": job_id},
            )
            return recognition_job_payload(connection, row)

    @app.post("/api/recognition-jobs/{job_id}/retry")
    def retry_recognition_job(
        job_id: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_workflow_write_role(user)
        now = utc_now()
        with database.connect() as connection:
            row = load_recognition_job(connection, job_id, user)
            failed_count = connection.execute(
                "SELECT COUNT(*) AS count FROM recognition_job_items WHERE job_id = ? AND status = 'failed'",
                (job_id,),
            ).fetchone()["count"]
            if not failed_count:
                raise HTTPException(status_code=409, detail="recognition_job_no_failed_items")
            connection.execute(
                """
                UPDATE recognition_job_items
                SET status = 'queued', attempts = attempts + 1, last_retry_at = ?, finished_at = NULL
                WHERE job_id = ? AND status = 'failed'
                """,
                (now, job_id),
            )
            row = refresh_recognition_job_status(connection, job_id, now)
            audit(
                connection,
                candidate_id=None,
                centre_code=row["centre_code"],
                event_type="recognition_job_retried",
                actor_username=user.username,
                details={"job_id": job_id, "failed_count": failed_count},
            )
            return recognition_job_payload(connection, row)

    @app.get("/api/admin/field-dictionary")
    def get_field_dictionary(
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_central_data_manager(user)
        with database.connect() as connection:
            return field_dictionary_payload(connection)

    @app.put("/api/admin/field-dictionary/{event_ref}/{field_code}")
    def update_field_dictionary_header(
        event_ref: str,
        field_code: str,
        payload: FieldHeaderUpdatePayload,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_central_data_manager(user)
        event_ref = event_ref.upper()
        field_code = field_code.upper()
        try:
            base_dictionary = resolved_crf_mapping.field_dictionary_for_event(event_ref)
        except CrfMappingError as error:
            raise HTTPException(status_code=404, detail="field_header_not_found") from error
        source_header = base_dictionary.get(field_code)
        if source_header is None:
            raise HTTPException(status_code=404, detail="field_header_not_found")

        updated_at = utc_now()
        with database.connect() as connection:
            current_payload = field_dictionary_payload(connection)
            current_header = next(
                header
                for header in current_payload["headers"]
                if header["event_ref"] == event_ref and header["field_code"] == field_code
            )
            previous_header = current_header["display_header"]
            if previous_header != payload.display_header:
                release = create_dictionary_draft_record(
                    connection,
                    actor_username=user.username,
                    version_prefix="compatibility",
                )
                connection.execute(
                    """
                    UPDATE dictionary_release_items SET display_header = ?
                    WHERE release_id = ? AND event_ref = ? AND field_code = ?
                    """,
                    (payload.display_header, release["id"], event_ref, field_code),
                )
                publish_dictionary_release_record(
                    connection,
                    release_id=release["id"],
                    actor_username=user.username,
                )
                audit(
                    connection,
                    candidate_id=None,
                    centre_code="CENTRAL",
                    event_type="field_header_updated",
                    actor_username=user.username,
                    details={
                        "event_ref": event_ref,
                        "field_code": field_code,
                        "previous_header": previous_header,
                        "display_header": payload.display_header,
                        "mapping_version": resolved_crf_mapping.mapping_version,
                        "release_id": release["id"],
                        "compatibility_path": True,
                    },
                )
            dictionary_payload = field_dictionary_payload(connection)
        return next(
            header
            for header in dictionary_payload["headers"]
            if header["event_ref"] == event_ref and header["field_code"] == field_code
        )

    @app.get("/api/exports/submitted-data.xlsx")
    def export_submitted_data_excel(
        user: Annotated[UserContext, Depends(current_user)],
    ) -> Response:
        if user.role not in EXPORT_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="export_role_required")
        if not getattr(resolved_spreadsheet_exporter, "ready", False):
            raise HTTPException(status_code=503, detail="spreadsheet_export_unavailable")
        try:
            workbook_bytes = resolved_spreadsheet_exporter.export(submitted_data_export_payload(user))
        except SpreadsheetExportError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        filename = f"submitted-clinical-data-{datetime.now(UTC).strftime('%Y%m%d-%H%M%SZ')}.xlsx"
        return Response(
            content=workbook_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/exports/reviewed-recognition-data.xlsx")
    def export_reviewed_recognition_data_excel(
        user: Annotated[UserContext, Depends(current_user)],
    ) -> Response:
        if user.role not in EXPORT_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="export_role_required")
        if not getattr(resolved_spreadsheet_exporter, "ready", False):
            raise HTTPException(status_code=503, detail="spreadsheet_export_unavailable")
        try:
            workbook_bytes = resolved_spreadsheet_exporter.export(
                reviewed_recognition_export_payload(user)
            )
        except SpreadsheetExportError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        filename = (
            f"reviewed-recognition-data-{datetime.now(UTC).strftime('%Y%m%d-%H%M%SZ')}.xlsx"
        )
        return Response(
            content=workbook_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/api/exports/reviewed-recognition-package.json")
    def export_reviewed_recognition_package(
        package_passphrase: Annotated[str, Form()],
        user: Annotated[UserContext, Depends(current_user)],
    ) -> Response:
        if user.role != "site_investigator":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="export_role_required")
        try:
            package_bytes, package_id, package_sha256 = reviewed_recognition_package(
                user, package_passphrase=package_passphrase
            )
        except OfflinePackageError as error:
            raise HTTPException(status_code=422, detail=error.code) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail="offline_package_centre_scope_required") from error
        filename = f"reviewed-recognition-package-{package_id}.json"
        return Response(
            content=package_bytes,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Offline-Package-SHA256": package_sha256,
            },
        )

    @app.post("/api/imports/reviewed-package", status_code=status.HTTP_201_CREATED)
    def import_reviewed_package(
        file: Annotated[UploadFile, File()],
        package_passphrase: Annotated[str, Form()],
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_central_data_manager(user)
        content = file.file.read(5 * 1024 * 1024 + 1)
        original_filename = Path(file.filename or "reviewed-package.enc.json").name
        try:
            package, package_sha256 = parse_encrypted_reviewed_package(
                content, passphrase=package_passphrase
            )
        except OfflinePackageError as error:
            write_offline_package_log(
                user=user,
                source_filename=original_filename,
                result="failed",
                package_sha256=hashlib.sha256(content).hexdigest(),
                error_code=error.code,
                error_detail="Package could not be authenticated or decrypted.",
            )
            http_status = 413 if error.code == "offline_package_too_large" else 422
            raise HTTPException(status_code=http_status, detail=error.code) from error
        package_id = str(package["package_id"])
        centre_code = str(package["centre_code"])
        records = package["records"]
        if centre_code == "CENTRAL" or not records:
            write_offline_package_log(
                user=user,
                source_filename=original_filename,
                result="failed",
                package_sha256=package_sha256,
                package_id=package_id,
                centre_code=centre_code,
                error_code="offline_package_centre_or_records_required",
            )
            raise HTTPException(status_code=422, detail="offline_package_centre_or_records_required")
        with database.connect() as connection:
            active_release = active_dictionary_release(connection)
        if (
            package.get("dictionary_id") != resolved_crf_mapping.mapping_id
            or package.get("dictionary_version") != active_release["version"]
        ):
            write_offline_package_log(
                user=user,
                source_filename=original_filename,
                result="failed",
                package_sha256=package_sha256,
                package_id=package_id,
                centre_code=centre_code,
                dictionary_id=str(package.get("dictionary_id")),
                dictionary_version=str(package.get("dictionary_version")),
                error_code="offline_package_dictionary_version_mismatch",
            )
            raise HTTPException(status_code=409, detail="offline_package_dictionary_version_mismatch")
        for record in records:
            try:
                resolved_crf_mapping.assert_allowed(str(record["edc_event_ref"]), (str(record["field_code"]),))
            except CrfMappingError as error:
                write_offline_package_log(
                    user=user,
                    source_filename=original_filename,
                    result="failed",
                    package_sha256=package_sha256,
                    package_id=package_id,
                    centre_code=centre_code,
                    dictionary_id=str(package.get("dictionary_id")),
                    dictionary_version=str(package.get("dictionary_version")),
                    error_code="offline_package_field_not_allowed",
                    error_detail=str(error),
                    record_count=len(records),
                )
                raise HTTPException(status_code=422, detail=str(error)) from error
        original_filename = Path(file.filename or f"{package_id}.enc.json").name
        import_id = str(uuid4())
        created_at = utc_now()
        created_count = 0
        duplicate_count = 0
        with database.connect() as connection:
            already_imported = connection.execute(
                "SELECT 1 FROM offline_package_imports WHERE package_sha256 = ? OR package_id = ?",
                (package_sha256, package_id),
            ).fetchone() is not None
        if already_imported:
            write_offline_package_log(
                user=user,
                source_filename=original_filename,
                result="duplicate",
                package_sha256=package_sha256,
                package_id=package_id,
                centre_code=centre_code,
                dictionary_id=str(package.get("dictionary_id")),
                dictionary_version=str(package.get("dictionary_version")),
                error_code="offline_package_already_imported",
                record_count=len(records),
            )
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="offline_package_already_imported")
        held_record: Mapping[str, object] | None = None
        with database.connect() as connection:
            for record in records:
                if effective_transfer_holds(
                    connection,
                    centre_code=centre_code,
                    subject_ref=str(record["edc_subject_ref"]),
                    event_ref=str(record["edc_event_ref"]),
                ):
                    held_record = record
                    break
        if held_record is not None:
            write_offline_package_log(
                user=user,
                source_filename=original_filename,
                result="failed",
                package_sha256=package_sha256,
                package_id=package_id,
                centre_code=centre_code,
                dictionary_id=str(package.get("dictionary_id")),
                dictionary_version=str(package.get("dictionary_version")),
                error_code="transfer_hold_active",
                error_detail=(
                    f"Transfer hold active for {held_record['edc_subject_ref']}/"
                    f"{held_record['edc_event_ref']}."
                ),
                record_count=len(records),
            )
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="transfer_hold_active")
        with database.connect() as connection:
            source_file_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO source_files (
                    id, centre_code, source_filename, sha256, mime_type, storage_key,
                    created_by, created_at
                ) VALUES (?, ?, ?, ?, 'application/json', ?, ?, ?)
                """,
                (
                    source_file_id,
                    centre_code,
                    original_filename,
                    package_sha256,
                    f"offline-package/{package_sha256}.json",
                    user.username,
                    created_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO offline_package_imports (
                    id, package_id, package_sha256, centre_code, record_count, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (import_id, package_id, package_sha256, centre_code, len(records), user.username, created_at),
            )
            package_path = (
                database.database_path.parent
                / "offline_packages"
                / centre_code
                / f"{source_file_id}.json"
            )
            package_path.parent.mkdir(parents=True, exist_ok=True)
            package_path.write_bytes(content)
            for record in records:
                duplicate = connection.execute(
                    """
                    SELECT id FROM candidates
                    WHERE centre_code = ? AND edc_subject_ref = ? AND edc_event_ref = ?
                      AND field_code = ? AND proposed_value = ? AND unit IS ?
                      AND status != 'rejected'
                    LIMIT 1
                    """,
                    (
                        centre_code,
                        record["edc_subject_ref"],
                        record["edc_event_ref"],
                        record["field_code"],
                        record["final_value"],
                        record.get("unit"),
                    ),
                ).fetchone()
                if duplicate is not None:
                    duplicate_count += 1
                    continue
                candidate_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO candidates (
                        id, centre_code, source_file_id, edc_subject_ref, edc_event_ref,
                        field_code, proposed_value, unit, final_value, status,
                        ocr_engine_version, kimi_model, schema_version, confidence,
                        local_ocr_value, local_ocr_unit, extraction_agreement, evidence_text,
                        import_batch_id, origin_type, created_by, created_at,
                        reviewed_by, reviewed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'human_confirmed',
                              'offline-reviewed-package-v1', 'not_used_offline_package',
                              'offline-reviewed-package-v1', 1.0, ?, ?, 'offline_reviewed', ?,
                              ?, 'offline_package', ?, ?, ?, ?)
                    """,
                    (
                        candidate_id,
                        centre_code,
                        source_file_id,
                        record["edc_subject_ref"],
                        record["edc_event_ref"],
                        record["field_code"],
                        record["final_value"],
                        record.get("unit"),
                        record["final_value"],
                        record["final_value"],
                        record.get("unit"),
                        "Imported from a reviewed centre package; source evidence remains at the originating centre.",
                        import_id,
                        user.username,
                        created_at,
                        "originating-centre-reviewer",
                        record["reviewed_at"],
                    ),
                )
                audit(
                    connection,
                    candidate_id=candidate_id,
                    centre_code=centre_code,
                    event_type="offline_package_imported",
                    actor_username=user.username,
                    details={
                        "package_id": package_id,
                        "package_sha256": package_sha256,
                        "source_sha256": record["source_sha256"],
                        "field_code": record["field_code"],
                    },
                )
                candidate = get_candidate(connection, candidate_id)
                evaluate_and_store_quality(
                    connection,
                    candidate,
                    value=str(record["final_value"]),
                    unit=record.get("unit"),
                    actor_username=user.username,
                )
                created_count += 1
        write_offline_package_log(
            user=user,
            source_filename=original_filename,
            result="imported",
            package_sha256=package_sha256,
            package_id=package_id,
            centre_code=centre_code,
            dictionary_id=str(package.get("dictionary_id")),
            dictionary_version=str(package.get("dictionary_version")),
            record_count=len(records),
            created_count=created_count,
            duplicate_count=duplicate_count,
        )
        return {
            "import_id": import_id,
            "package_id": package_id,
            "package_sha256": package_sha256,
            "centre_code": centre_code,
            "record_count": len(records),
            "created_count": created_count,
            "duplicate_count": duplicate_count,
            "status": "imported_reviewed_values",
            "authority_submission": "not_attempted",
        }

    @app.post("/api/imports/reviewed-packages", status_code=status.HTTP_201_CREATED)
    def import_reviewed_packages(
        files: Annotated[list[UploadFile], File()],
        package_passphrase: Annotated[str, Form()],
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_central_data_manager(user)
        if not files or len(files) > 100:
            raise HTTPException(status_code=422, detail="offline_package_batch_size_invalid")
        results: list[dict[str, object]] = []
        for file in files:
            try:
                result = import_reviewed_package(
                    file=file,
                    package_passphrase=package_passphrase,
                    user=user,
                )
                results.append({"filename": Path(file.filename or "package").name, "result": "imported", **result})
            except HTTPException as error:
                results.append(
                    {
                        "filename": Path(file.filename or "package").name,
                        "result": "duplicate" if error.detail == "offline_package_already_imported" else "failed",
                        "error_code": str(error.detail),
                        "http_status": error.status_code,
                    }
                )
        return {
            "package_count": len(files),
            "imported_count": sum(item["result"] == "imported" for item in results),
            "duplicate_count": sum(item["result"] == "duplicate" for item in results),
            "failed_count": sum(item["result"] == "failed" for item in results),
            "results": results,
        }

    @app.get("/api/imports/reviewed-package-logs")
    def list_reviewed_package_logs(
        user: Annotated[UserContext, Depends(current_user)],
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, object]]:
        require_central_data_manager(user)
        with database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, package_sha256, package_id, centre_code, source_filename,
                       dictionary_id, dictionary_version, result, error_code, error_detail,
                       record_count, created_count, duplicate_count, created_by, created_at
                FROM offline_package_import_logs
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [row_to_dict(row) for row in rows]

    @app.post("/api/analysis-snapshots", status_code=status.HTTP_201_CREATED)
    def create_analysis_snapshot(
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_central_data_manager(user)
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with database.connect() as connection:
            release = active_dictionary_release(connection)
            submitted = connection.execute(
                """
                SELECT candidates.*, source_files.sha256 AS source_sha256,
                       transfer_requests.id AS transfer_id,
                       transfer_requests.package_sha256,
                       transfer_requests.external_reference,
                       transfer_requests.submitted_at,
                       transfer_requests.readback_status
                FROM candidates
                JOIN source_files ON source_files.id = candidates.source_file_id
                JOIN transfer_requests ON transfer_requests.candidate_id = candidates.id
                WHERE candidates.status = 'human_confirmed'
                  AND transfer_requests.status = 'submitted'
                  AND transfer_requests.rowid = (
                      SELECT latest.rowid FROM transfer_requests AS latest
                      WHERE latest.candidate_id = candidates.id AND latest.status = 'submitted'
                      ORDER BY latest.submitted_at DESC, latest.rowid DESC LIMIT 1
                  )
                ORDER BY candidates.centre_code, candidates.edc_subject_ref,
                         candidates.edc_event_ref, candidates.field_code, candidates.rowid
                """
            ).fetchall()
            snapshot_rows: list[dict[str, object]] = []
            for candidate in submitted:
                quality = latest_quality_assessment(connection, candidate)
                issues = connection.execute(
                    "SELECT id, status FROM data_issues WHERE candidate_id = ? ORDER BY opened_at, rowid",
                    (candidate["id"],),
                ).fetchall()
                holds = effective_transfer_holds(
                    connection,
                    centre_code=candidate["centre_code"],
                    subject_ref=candidate["edc_subject_ref"],
                    event_ref=candidate["edc_event_ref"],
                )
                snapshot_rows.append(
                    {
                        "candidate_id": candidate["id"],
                        "centre_code": candidate["centre_code"],
                        "subject_ref": candidate["edc_subject_ref"],
                        "event_ref": candidate["edc_event_ref"],
                        "field_code": candidate["field_code"],
                        "final_value": candidate["final_value"],
                        "unit": candidate["unit"],
                        "source_sha256": candidate["source_sha256"],
                        "reviewed_by": candidate["reviewed_by"],
                        "reviewed_at": candidate["reviewed_at"],
                        "quality": {
                            "status": quality["status"],
                            "rule_version": quality["rule_version"],
                            "finding_codes": [finding["code"] for finding in quality["findings"]],
                        },
                        "companion_data_issues": [
                            {"id": issue["id"], "status": issue["status"]} for issue in issues
                        ],
                        "effective_transfer_holds": [hold["scope_key"] for hold in holds],
                        "transfer": {
                            "id": candidate["transfer_id"],
                            "package_sha256": candidate["package_sha256"],
                            "external_reference": candidate["external_reference"],
                            "submitted_at": candidate["submitted_at"],
                            "readback_status": candidate["readback_status"],
                        },
                    }
                )
            snapshot = {
                "protocol": "clinical-edc-companion-analysis-snapshot-v1",
                "snapshot_id": snapshot_id,
                "created_at": created_at,
                "scope": "ALL_CENTRES",
                "authority_boundary": "companion_snapshot_not_formal_authority_edc_lock",
                "dictionary_release": {
                    "id": release["id"],
                    "version": release["version"],
                },
                "quality_rule_version": resolved_quality_rules["version"],
                "rows": snapshot_rows,
            }
            canonical_json = json.dumps(
                snapshot,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            content_sha256 = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
            connection.execute(
                """
                INSERT INTO analysis_snapshots (
                    id, content_sha256, canonical_json, row_count, dictionary_release_id,
                    quality_rule_version, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    content_sha256,
                    canonical_json,
                    len(snapshot_rows),
                    release["id"],
                    resolved_quality_rules["version"],
                    user.username,
                    created_at,
                ),
            )
            audit(
                connection,
                candidate_id=None,
                centre_code="CENTRAL",
                event_type="analysis_snapshot_created",
                actor_username=user.username,
                details={
                    "snapshot_id": snapshot_id,
                    "content_sha256": content_sha256,
                    "row_count": len(snapshot_rows),
                    "dictionary_release_id": release["id"],
                    "quality_rule_version": resolved_quality_rules["version"],
                },
            )
            row = connection.execute(
                "SELECT * FROM analysis_snapshots WHERE id = ?",
                (snapshot_id,),
            ).fetchone()
        return analysis_snapshot_payload(row)

    @app.get("/api/analysis-snapshots")
    def list_analysis_snapshots(
        user: Annotated[UserContext, Depends(current_user)],
    ) -> list[dict[str, object]]:
        require_central_data_manager(user)
        with database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM analysis_snapshots ORDER BY created_at, rowid"
            ).fetchall()
        return [analysis_snapshot_payload(row) for row in rows]

    @app.get("/api/analysis-snapshots/{snapshot_id}")
    def read_analysis_snapshot(
        snapshot_id: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_central_data_manager(user)
        with database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_snapshots WHERE id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="not_found")
        return analysis_snapshot_payload(row)

    @app.get("/api/analysis-snapshots/{snapshot_id}/download")
    def download_analysis_snapshot(
        snapshot_id: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> Response:
        require_central_data_manager(user)
        with database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_snapshots WHERE id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="not_found")
        payload = analysis_snapshot_payload(row)
        if payload["integrity"] != "verified":
            raise HTTPException(status_code=409, detail="analysis_snapshot_integrity_failed")
        return Response(
            content=row["canonical_json"].encode("utf-8"),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="analysis-snapshot-{snapshot_id}.json"',
                "X-Content-SHA256": row["content_sha256"],
            },
        )

    @app.post("/api/source-files", status_code=status.HTTP_201_CREATED)
    def create_source_file(payload: SourceFileCreate, user: Annotated[UserContext, Depends(current_user)]) -> dict[str, object]:
        require_workflow_write_role(user)
        centre_code = payload.centre_code or user.centre_code
        if not centre_code:
            raise HTTPException(status_code=422, detail="centre_code_required_for_central_user")
        assert_centre_access(user, centre_code)
        source_file_id = str(uuid4())
        with database.connect() as connection:
            connection.execute(
                """
                INSERT INTO source_files (id, centre_code, source_filename, sha256, mime_type, storage_key, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_file_id,
                    centre_code,
                    payload.source_filename,
                    payload.sha256,
                    payload.mime_type,
                    payload.storage_key,
                    user.username,
                    utc_now(),
                ),
            )
            row = connection.execute("SELECT * FROM source_files WHERE id = ?", (source_file_id,)).fetchone()
        return source_file_payload(row)

    @app.post("/api/source-files/upload", status_code=status.HTTP_201_CREATED)
    def upload_synthetic_source_file(
        file: Annotated[UploadFile, File()],
        synthetic_attestation: Annotated[bool, Form()],
        user: Annotated[UserContext, Depends(current_user)],
        centre_code: Annotated[str | None, Form()] = None,
        edc_subject_ref: Annotated[str | None, Form()] = None,
        edc_event_ref: Annotated[str | None, Form()] = None,
    ) -> dict[str, object]:
        require_workflow_write_role(user)
        if not synthetic_attestation:
            raise HTTPException(status_code=422, detail="synthetic_attestation_required")
        resolved_centre_code = centre_code or user.centre_code
        if not resolved_centre_code:
            raise HTTPException(status_code=422, detail="centre_code_required_for_central_user")
        assert_centre_access(user, resolved_centre_code)
        reported_mime_type = (file.content_type or "").lower()
        default_filename = (
            "synthetic-report.pdf"
            if reported_mime_type in {"application/pdf", "application/x-pdf"}
            else "synthetic-image"
        )
        filename = Path(file.filename or default_filename).name
        suffix = Path(filename).suffix.lower() or ".bin"
        is_pdf = suffix == ".pdf" and reported_mime_type in {
            "",
            "application/pdf",
            "application/x-pdf",
            "application/octet-stream",
        }
        is_image = reported_mime_type.startswith("image/")
        if not is_image and not is_pdf:
            raise HTTPException(status_code=422, detail="supported_report_upload_required")
        mime_type = "application/pdf" if is_pdf else reported_mime_type

        max_bytes = 20 * 1024 * 1024 if is_pdf else 8 * 1024 * 1024
        content = file.file.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail="pdf_too_large" if is_pdf else "image_too_large",
            )
        if not content:
            raise HTTPException(status_code=422, detail="empty_report_upload")
        if is_pdf:
            try:
                validate_pdf_structure(content)
            except PdfSafetyError as error:
                raise HTTPException(status_code=422, detail=error.code) from error
        if is_image:
            try:
                mime_type = validate_image_upload(content, reported_mime_type)
            except ImageUploadError as error:
                raise HTTPException(status_code=422, detail=error.code) from error
            suffix = ".jpg" if mime_type == "image/jpeg" else ".png"

        subject_ref = (edc_subject_ref or "").strip().upper()
        event_ref = (edc_event_ref or "").strip().upper()
        if bool(subject_ref) != bool(event_ref):
            raise HTTPException(status_code=422, detail="subject_and_event_required_together")
        if resolved_edc_adapter.target_kind == "libreclinica" and not subject_ref:
            raise HTTPException(status_code=422, detail="subject_and_event_required_for_live_edc")
        if subject_ref and not SUBJECT_REF_RE.fullmatch(subject_ref):
            raise HTTPException(status_code=422, detail="pseudonymous_subject_ref_required")
        if event_ref and not EVENT_REF_RE.fullmatch(event_ref):
            raise HTTPException(status_code=422, detail="invalid_event_ref")

        requires_edc_provisioning = bool(subject_ref) and resolved_edc_adapter.target_kind == "libreclinica"
        provisioning = None
        provisioning_error_code = None
        if requires_edc_provisioning:
            try:
                provisioning = resolved_edc_adapter.provision_subject(
                    subject_ref,
                    event_ref,
                    # The synthetic sandbox requires an enrollment date strictly
                    # before the server date. Production must supply the protocol-
                    # defined enrollment date instead of deriving it from upload.
                    enrollment_date=date.today() - timedelta(days=1),
                )
            except EdcAdapterError as error:
                provisioning_error_code = error.code

        source_file_id = str(uuid4())
        storage_key = f"synthetic/{resolved_centre_code}/{source_file_id}{suffix}"
        upload_path = database.database_path.parent / "synthetic_uploads" / resolved_centre_code / f"{source_file_id}{suffix}"
        upload_path.parent.mkdir(parents=True, exist_ok=True)
        upload_path.write_bytes(content)
        sha256 = hashlib.sha256(content).hexdigest()
        created_at = utc_now()
        with database.connect() as connection:
            connection.execute(
                """
                INSERT INTO source_files (
                    id, centre_code, source_filename, sha256, mime_type, storage_key,
                    edc_subject_ref, edc_event_ref, edc_subject_oid, edc_subject_created,
                    edc_event_scheduled, edc_provisioned_at, edc_provisioning_status,
                    edc_provisioning_error_code, created_by, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_file_id,
                    resolved_centre_code,
                    filename,
                    sha256,
                    mime_type,
                    storage_key,
                    provisioning.subject_ref if provisioning else subject_ref or None,
                    provisioning.event_ref if provisioning else event_ref or None,
                    provisioning.subject_oid if provisioning else None,
                    int(provisioning.subject_created) if provisioning else None,
                    int(provisioning.event_scheduled) if provisioning else None,
                    created_at if provisioning else None,
                    "completed" if provisioning else "deferred" if requires_edc_provisioning else None,
                    provisioning_error_code,
                    user.username,
                    created_at,
                ),
            )
            audit(
                connection,
                candidate_id=None,
                centre_code=resolved_centre_code,
                event_type="synthetic_source_file_uploaded",
                actor_username=user.username,
                details={
                    "source_file_id": source_file_id,
                    "sha256": sha256,
                    "storage_key": storage_key,
                    "edc_subject_ref": provisioning.subject_ref if provisioning else subject_ref or None,
                    "edc_event_ref": provisioning.event_ref if provisioning else event_ref or None,
                    "edc_subject_created": provisioning.subject_created if provisioning else None,
                    "edc_event_scheduled": provisioning.event_scheduled if provisioning else None,
                    "edc_provisioning_status": (
                        "completed" if provisioning else "deferred" if requires_edc_provisioning else None
                    ),
                    "edc_provisioning_error_code": provisioning_error_code,
                },
            )
            row = connection.execute("SELECT * FROM source_files WHERE id = ?", (source_file_id,)).fetchone()
        return source_file_payload(row)

    @app.get("/api/source-files/{source_file_id}/pdf-inspection")
    def inspect_source_pdf(
        source_file_id: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        with database.connect() as connection:
            source_file = connection.execute(
                "SELECT * FROM source_files WHERE id = ?", (source_file_id,)
            ).fetchone()
            if source_file is None:
                raise HTTPException(status_code=404, detail="source_file_not_found")
            assert_centre_access(user, source_file["centre_code"])
            if source_file["mime_type"] != "application/pdf":
                raise HTTPException(status_code=422, detail="pulmonary_pdf_required")
            pdf_path = stored_source_path(source_file)
        inspection = inspect_pdf(pdf_path)
        return {
            "source_file_id": source_file_id,
            "classification": inspection.classification,
            "page_count": len(inspection.pages),
            "pages": [
                {
                    "page_number": page.page_number,
                    "width": page.width,
                    "height": page.height,
                    "text_char_count": page.text_char_count,
                }
                for page in inspection.pages
            ],
            "warnings": list(inspection.warnings),
            "candidate_creation": "available" if inspection.classification == "pdf_text_layer" else "blocked",
        }

    @app.post("/api/imports/structured-csv", status_code=status.HTTP_201_CREATED)
    def import_structured_csv(
        file: Annotated[UploadFile, File()],
        synthetic_attestation: Annotated[bool, Form()],
        user: Annotated[UserContext, Depends(current_user)],
        centre_code: Annotated[str | None, Form()] = None,
    ) -> dict[str, object]:
        require_workflow_write_role(user)
        if not synthetic_attestation:
            raise HTTPException(status_code=422, detail="synthetic_attestation_required")
        resolved_centre_code = centre_code or user.centre_code
        if not resolved_centre_code:
            raise HTTPException(status_code=422, detail="centre_code_required_for_central_user")
        assert_centre_access(user, resolved_centre_code)
        filename = Path(file.filename or "structured-import.csv").name
        if Path(filename).suffix.lower() != ".csv":
            raise HTTPException(status_code=422, detail="structured_import_csv_required")
        content = file.file.read(5 * 1024 * 1024 + 1)
        try:
            parsed_import = parse_structured_csv(content)
        except StructuredImportError as error:
            http_status = 413 if error.code == "structured_import_file_too_large" else 422
            raise HTTPException(status_code=http_status, detail=error.code) from error
        rows = parsed_import.rows

        for row in rows:
            if not SUBJECT_REF_RE.fullmatch(row.subject_ref):
                raise HTTPException(status_code=422, detail="pseudonymous_subject_ref_required")
            if not EVENT_REF_RE.fullmatch(row.event_ref):
                raise HTTPException(status_code=422, detail="invalid_event_ref")
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", row.field_code):
                raise HTTPException(status_code=422, detail="invalid_field_code")
            try:
                resolved_crf_mapping.assert_allowed(row.event_ref, (row.field_code,))
            except CrfMappingError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error

        batch_id = str(uuid4())
        source_file_id = str(uuid4())
        source_sha256 = hashlib.sha256(content).hexdigest()
        created_at = utc_now()
        created_candidates: list[dict[str, object]] = []
        duplicate_count = 0
        blocked_count = 0
        with database.connect() as connection:
            for row in rows:
                if effective_transfer_holds(
                    connection,
                    centre_code=resolved_centre_code,
                    subject_ref=row.subject_ref,
                    event_ref=row.event_ref,
                ):
                    raise HTTPException(status_code=409, detail="transfer_hold_active")
            connection.execute(
                """
                INSERT INTO source_files (
                    id, centre_code, source_filename, sha256, mime_type, storage_key,
                    created_by, created_at
                ) VALUES (?, ?, ?, ?, 'text/csv', ?, ?, ?)
                """,
                (
                    source_file_id,
                    resolved_centre_code,
                    filename,
                    source_sha256,
                    f"structured/{resolved_centre_code}/{batch_id}",
                    user.username,
                    created_at,
                ),
            )
            for imported_row in rows:
                duplicate = connection.execute(
                    """
                    SELECT id FROM candidates
                    WHERE centre_code = ? AND edc_subject_ref = ? AND edc_event_ref = ?
                      AND field_code = ? AND proposed_value = ? AND unit IS ?
                      AND status != 'rejected'
                    LIMIT 1
                    """,
                    (
                        resolved_centre_code,
                        imported_row.subject_ref,
                        imported_row.event_ref,
                        imported_row.field_code,
                        imported_row.value,
                        imported_row.unit,
                    ),
                ).fetchone()
                if duplicate is not None:
                    duplicate_count += 1
                    continue
                candidate_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO candidates (
                        id, centre_code, source_file_id, edc_subject_ref, edc_event_ref,
                        field_code, proposed_value, unit, final_value, status,
                        ocr_engine_version, kimi_model, schema_version, confidence,
                        local_ocr_value, local_ocr_unit, extraction_agreement, evidence_text,
                        import_batch_id, origin_type, created_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'candidate', ?, ?, ?, 1.0,
                              ?, ?, 'structured_source', ?, ?, 'structured_csv', ?, ?)
                    """,
                    (
                        candidate_id,
                        resolved_centre_code,
                        source_file_id,
                        imported_row.subject_ref,
                        imported_row.event_ref,
                        imported_row.field_code,
                        imported_row.value,
                        imported_row.unit,
                        "structured-csv-v1",
                        "not_used_structured_import",
                        "structured-csv-v1",
                        imported_row.value,
                        imported_row.unit,
                        f"structured CSV row {imported_row.row_number}",
                        batch_id,
                        user.username,
                        created_at,
                    ),
                )
                audit(
                    connection,
                    candidate_id=candidate_id,
                    centre_code=resolved_centre_code,
                    event_type="candidate_created",
                    actor_username=user.username,
                    details={
                        "status": "candidate",
                        "field_code": imported_row.field_code,
                        "mode": "structured_csv",
                        "import_batch_id": batch_id,
                        "source_sha256": source_sha256,
                    },
                )
                candidate = get_candidate(connection, candidate_id)
                assessment = evaluate_and_store_quality(
                    connection,
                    candidate,
                    value=imported_row.value,
                    unit=imported_row.unit,
                    actor_username=user.username,
                )
                if assessment["status"] == "BLOCK":
                    blocked_count += 1
                created_candidates.append(candidate_payload(candidate))
            connection.execute(
                """
                INSERT INTO structured_import_batches (
                    id, centre_code, source_file_id, source_sha256, source_filename,
                    row_count, created_count, duplicate_count, blocked_count,
                    created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    resolved_centre_code,
                    source_file_id,
                    source_sha256,
                    filename,
                    len(rows),
                    len(created_candidates),
                    duplicate_count,
                    blocked_count,
                    user.username,
                    created_at,
                ),
            )
            audit(
                connection,
                candidate_id=None,
                centre_code=resolved_centre_code,
                event_type="structured_import_completed",
                actor_username=user.username,
                details={
                    "batch_id": batch_id,
                    "source_sha256": source_sha256,
                    "row_count": len(rows),
                    "created_count": len(created_candidates),
                    "duplicate_count": duplicate_count,
                    "blocked_count": blocked_count,
                    "raw_file_retained": False,
                },
            )
        return {
            "id": batch_id,
            "centre_code": resolved_centre_code,
            "source_sha256": source_sha256,
            "source_filename": filename,
            "row_count": len(rows),
            "created_count": len(created_candidates),
            "duplicate_count": duplicate_count,
            "blocked_count": blocked_count,
            "raw_file_retained": False,
            "ignored_headers": list(parsed_import.ignored_headers),
            "candidates": created_candidates,
            "created_by": user.username,
            "created_at": created_at,
        }

    @app.post(
        "/api/source-files/{source_file_id}/deidentification-drafts",
        status_code=status.HTTP_201_CREATED,
    )
    def create_deidentification_draft(
        source_file_id: str,
        response: Response,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_workflow_write_role(user)
        with database.connect() as connection:
            source_file = connection.execute(
                "SELECT * FROM source_files WHERE id = ?",
                (source_file_id,),
            ).fetchone()
            if source_file is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="source_file_not_found")
            assert_centre_access(user, source_file["centre_code"])
            if not source_file["storage_key"].startswith("synthetic/"):
                raise HTTPException(status_code=409, detail="original_synthetic_source_file_required")
            existing = connection.execute(
                "SELECT * FROM deidentification_drafts WHERE original_source_file_id = ?",
                (source_file_id,),
            ).fetchone()
            if existing is not None:
                derivative = connection.execute(
                    "SELECT * FROM source_files WHERE id = ?",
                    (existing["derivative_source_file_id"],),
                ).fetchone()
                response.status_code = status.HTTP_200_OK
                return deidentification_draft_payload(existing, derivative)
            original_path = stored_source_path(source_file)

        draft_id = str(uuid4())
        derivative_source_file_id = str(uuid4())
        derivative_path = (
            database.database_path.parent
            / "deidentified_uploads"
            / source_file["centre_code"]
            / f"{derivative_source_file_id}.png"
        )
        try:
            redaction = resolved_deidentifier.redact(original_path, derivative_path)
        except LocalDeidentificationUnavailable as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
        except LocalDeidentificationFailed as error:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
        if not derivative_path.is_file():
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="deidentified_derivative_not_created")

        derivative_content = derivative_path.read_bytes()
        derivative_sha256 = hashlib.sha256(derivative_content).hexdigest()
        created_at = utc_now()
        marker_codes = sorted(set(redaction.detected_marker_codes))
        derivative_filename = f"{Path(source_file['source_filename']).stem}.deidentified.png"[:200]
        derivative_storage_key = f"deidentified/{source_file['centre_code']}/{derivative_source_file_id}.png"
        with database.connect() as connection:
            current_source = connection.execute(
                "SELECT * FROM source_files WHERE id = ?",
                (source_file_id,),
            ).fetchone()
            if current_source is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="source_file_not_found")
            assert_centre_access(user, current_source["centre_code"])
            connection.execute(
                """
                INSERT INTO source_files (
                    id, centre_code, source_filename, sha256, mime_type, storage_key, created_by, created_at
                ) VALUES (?, ?, ?, ?, 'image/png', ?, ?, ?)
                """,
                (
                    derivative_source_file_id,
                    current_source["centre_code"],
                    derivative_filename,
                    derivative_sha256,
                    derivative_storage_key,
                    user.username,
                    created_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO deidentification_drafts (
                    id, original_source_file_id, derivative_source_file_id, centre_code, status,
                    detected_marker_codes_json, ocr_engine_version, created_by, created_at,
                    confirmed_by, confirmed_at
                ) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    draft_id,
                    source_file_id,
                    derivative_source_file_id,
                    current_source["centre_code"],
                    json.dumps(marker_codes),
                    redaction.engine_version,
                    user.username,
                    created_at,
                ),
            )
            audit(
                connection,
                candidate_id=None,
                centre_code=current_source["centre_code"],
                event_type="deidentification_draft_created",
                actor_username=user.username,
                details={
                    "draft_id": draft_id,
                    "original_source_file_id": source_file_id,
                    "derivative_source_file_id": derivative_source_file_id,
                    "detected_marker_codes": marker_codes,
                    "derivative_sha256": derivative_sha256,
                },
            )
            draft, derivative = get_deidentification_draft(connection, draft_id)
        return deidentification_draft_payload(draft, derivative)

    @app.get("/api/deidentification-drafts/{draft_id}/image")
    def get_deidentification_draft_image(
        draft_id: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> FileResponse:
        if user.role in READ_ONLY_ROLES:
            raise HTTPException(status_code=403, detail="source_image_access_forbidden")
        with database.connect() as connection:
            draft, derivative = get_deidentification_draft(connection, draft_id)
            assert_centre_access(user, draft["centre_code"])
            derivative_path = stored_source_path(derivative)
        if not derivative_path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="deidentified_derivative_not_found")
        return FileResponse(
            derivative_path,
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/deidentification-drafts/{draft_id}/confirm")
    def confirm_deidentification_draft(
        draft_id: str,
        payload: DeidentificationConfirmPayload,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_workflow_write_role(user)
        if not payload.human_review_attestation:
            raise HTTPException(status_code=422, detail="deidentification_review_attestation_required")
        with database.connect() as connection:
            draft, derivative = get_deidentification_draft(connection, draft_id)
            assert_centre_access(user, draft["centre_code"])
            if draft["status"] != "confirmed":
                confirmed_at = utc_now()
                connection.execute(
                    """
                    UPDATE deidentification_drafts
                    SET status = 'confirmed', confirmed_by = ?, confirmed_at = ?
                    WHERE id = ?
                    """,
                    (user.username, confirmed_at, draft_id),
                )
                audit(
                    connection,
                    candidate_id=None,
                    centre_code=draft["centre_code"],
                    event_type="deidentification_draft_confirmed",
                    actor_username=user.username,
                    details={
                        "draft_id": draft_id,
                        "derivative_source_file_id": draft["derivative_source_file_id"],
                        "human_review_attestation": True,
                    },
                )
                draft, derivative = get_deidentification_draft(connection, draft_id)
        return deidentification_draft_payload(draft, derivative)

    @app.post("/api/candidates", status_code=status.HTTP_201_CREATED)
    def create_candidate(payload: CandidateCreate, user: Annotated[UserContext, Depends(current_user)]) -> dict[str, object]:
        require_workflow_write_role(user)
        try:
            resolved_crf_mapping.assert_allowed(payload.edc_event_ref, (payload.field_code,))
        except CrfMappingError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        candidate_id = str(uuid4())
        with database.connect() as connection:
            source_file = connection.execute("SELECT * FROM source_files WHERE id = ?", (payload.source_file_id,)).fetchone()
            if source_file is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="source_file_not_found")
            assert_centre_access(user, source_file["centre_code"])
            assert_source_ready_for_candidates(connection, source_file)
            created_at = utc_now()
            connection.execute(
                """
                INSERT INTO candidates (
                    id, centre_code, source_file_id, edc_subject_ref, edc_event_ref, field_code, proposed_value,
                    unit, final_value, status, ocr_engine_version, kimi_model, schema_version, confidence,
                    created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'candidate', ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    source_file["centre_code"],
                    payload.source_file_id,
                    payload.edc_subject_ref,
                    payload.edc_event_ref,
                    payload.field_code,
                    payload.proposed_value,
                    payload.unit,
                    payload.ocr_engine_version,
                    payload.kimi_model,
                    payload.schema_version,
                    payload.confidence,
                    user.username,
                    created_at,
                ),
            )
            audit(
                connection,
                candidate_id=candidate_id,
                centre_code=source_file["centre_code"],
                event_type="candidate_created",
                actor_username=user.username,
                details={"status": "candidate", "field_code": payload.field_code},
            )
            row = get_candidate(connection, candidate_id)
            evaluate_and_store_quality(
                connection,
                row,
                value=payload.proposed_value,
                unit=payload.unit,
                actor_username=user.username,
            )
        return candidate_payload(row)

    @app.post("/api/source-files/{source_file_id}/demo-extract", status_code=status.HTTP_201_CREATED)
    def demo_extract(
        source_file_id: str,
        payload: DemoExtractPayload,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> list[dict[str, object]]:
        require_workflow_write_role(user)
        parsed_values = parse_demo_lab_text(payload.deidentified_ocr_text)
        with database.connect() as connection:
            source_file = connection.execute("SELECT * FROM source_files WHERE id = ?", (source_file_id,)).fetchone()
            if source_file is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="source_file_not_found")
            assert_centre_access(user, source_file["centre_code"])
            assert_source_ready_for_candidates(connection, source_file)
            created: list[dict[str, object]] = []
            for field_code, proposed_value, unit in parsed_values:
                candidate_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO candidates (
                        id, centre_code, source_file_id, edc_subject_ref, edc_event_ref, field_code, proposed_value,
                        unit, final_value, status, ocr_engine_version, kimi_model, schema_version, confidence,
                        created_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'candidate', 'demo-text-ocr-0.1', 'kimi-disabled-demo',
                              'lab-candidate-v1', 0.5, ?, ?)
                    """,
                    (
                        candidate_id,
                        source_file["centre_code"],
                        source_file_id,
                        payload.edc_subject_ref,
                        payload.edc_event_ref,
                        field_code,
                        proposed_value,
                        unit,
                        user.username,
                        utc_now(),
                    ),
                )
                audit(
                    connection,
                    candidate_id=candidate_id,
                    centre_code=source_file["centre_code"],
                    event_type="candidate_created",
                    actor_username=user.username,
                    details={"status": "candidate", "field_code": field_code, "mode": "demo_extract"},
                )
                created.append(candidate_payload(get_candidate(connection, candidate_id)))
        return created

    @app.post(
        "/api/source-files/{source_file_id}/pulmonary-function-extract",
        status_code=status.HTTP_201_CREATED,
    )
    def pulmonary_function_extract(
        source_file_id: str,
        payload: LocalOcrExtractPayload,
        response: Response,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> list[dict[str, object]]:
        require_workflow_write_role(user)
        selected_fields = recognition_field_scope(payload.edc_event_ref, payload.field_codes)
        with database.connect() as connection:
            source_file = connection.execute(
                "SELECT * FROM source_files WHERE id = ?", (source_file_id,)
            ).fetchone()
            if source_file is None:
                raise HTTPException(status_code=404, detail="source_file_not_found")
            assert_centre_access(user, source_file["centre_code"])
            if source_file["mime_type"] != "application/pdf":
                raise HTTPException(status_code=422, detail="pulmonary_pdf_required")
            if not source_file["storage_key"].startswith("synthetic/"):
                raise HTTPException(status_code=409, detail="synthetic_source_file_required")
            upload_path = stored_source_path(source_file)
            existing_candidates = connection.execute(
                f"""
                {candidate_select_sql()}
                WHERE candidates.source_file_id = ?
                  AND candidates.edc_event_ref = ?
                  AND candidates.schema_version LIKE 'local-pdf-pft-candidate-v1+%'
                ORDER BY candidates.created_at, candidates.id
                """,
                (source_file_id, payload.edc_event_ref),
            ).fetchall()
            if existing_candidates:
                if any(
                    candidate["edc_subject_ref"] != payload.edc_subject_ref
                    for candidate in existing_candidates
                ):
                    raise HTTPException(status_code=409, detail="source_event_subject_conflict")
            if existing_candidates and (payload.field_codes is None or set(selected_fields).issubset(
                {candidate["field_code"] for candidate in existing_candidates}
            )):
                response.status_code = status.HTTP_200_OK
                return [
                    candidate_payload(candidate)
                    for candidate in existing_candidates
                    if candidate["field_code"] in selected_fields
                ]

        try:
            extraction_started = time.perf_counter()
            extraction = resolved_pulmonary_parser.extract(upload_path)
        except PulmonaryFunctionExtractionFailed as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        parsed_candidates = [
            candidate
            for candidate in extraction.candidates
            if candidate.field_code in selected_fields
        ]
        if not parsed_candidates:
            raise HTTPException(status_code=422, detail="field_not_in_crf_mapping")

        created_at = utc_now()
        schema_version = (
            f"local-pdf-pft-candidate-v1+{resolved_crf_mapping.mapping_version}"
        )
        pulmonary_dictionary = getattr(resolved_pulmonary_parser, "dictionary", None)
        pulmonary_dictionary_id = getattr(
            pulmonary_dictionary, "dictionary_id", "pulmonary-function-field-dictionary"
        )
        pulmonary_dictionary_version = getattr(pulmonary_dictionary, "dictionary_version", "v1")
        inspection = inspect_pdf(upload_path)
        evidence_spans = tuple(
            EvidenceSpan(
                field_code=candidate.field_code,
                page_number=None,
                text=candidate.evidence_text,
            )
            for candidate in parsed_candidates
        )
        idempotency_key, evidence = build_extraction_evidence(
            source_file_id=source_file["id"],
            source_sha256=source_file["sha256"],
            derivative_sha256=source_file["sha256"] if source_file["storage_key"].startswith("deidentified/") else None,
            dictionary_id=pulmonary_dictionary_id,
            dictionary_version=pulmonary_dictionary_version,
            selected_fields=selected_fields,
            engine="local_pdf_pulmonary",
            engine_version=extraction.engine_version,
            duration_ms=round((time.perf_counter() - extraction_started) * 1000),
            page_dimensions=(
                {
                    "page_number": page.page_number,
                    "width": page.width,
                    "height": page.height,
                    "text_char_count": page.text_char_count,
                }
                for page in inspection.pages
            ),
            spans=evidence_spans,
            warnings=inspection.warnings,
        )
        with database.connect() as connection:
            current_source = connection.execute(
                "SELECT * FROM source_files WHERE id = ?", (source_file_id,)
            ).fetchone()
            if current_source is None:
                raise HTTPException(status_code=404, detail="source_file_not_found")
            assert_centre_access(user, current_source["centre_code"])
            extraction_run = persist_extraction_run(
                connection,
                source_file=current_source,
                subject_ref=payload.edc_subject_ref,
                event_ref=payload.edc_event_ref,
                dictionary_id=pulmonary_dictionary_id,
                dictionary_version=pulmonary_dictionary_version,
                engine="local_pdf_pulmonary",
                engine_version=extraction.engine_version,
                model_ids=[],
                duration_ms=int(evidence["duration_ms"]),
                evidence=evidence,
                idempotency_key=idempotency_key,
                created_by=user.username,
            )
            existing_run_candidates = connection.execute(
                f"{candidate_select_sql()} WHERE candidates.extraction_run_id = ? ORDER BY candidates.created_at, candidates.id",
                (extraction_run["id"],),
            ).fetchall()
            if existing_run_candidates:
                response.status_code = status.HTTP_200_OK
                return [
                    candidate_payload(candidate)
                    for candidate in existing_run_candidates
                    if candidate["field_code"] in selected_fields
                ]
            created: list[dict[str, object]] = []
            for candidate in parsed_candidates:
                candidate_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO candidates (
                        id, centre_code, source_file_id, edc_subject_ref, edc_event_ref,
                        field_code, proposed_value, unit, final_value, status,
                        ocr_engine_version, kimi_model, schema_version, confidence,
                        local_ocr_value, local_ocr_unit, extraction_agreement,
                        evidence_text, origin_type, extraction_run_id, created_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'candidate', ?,
                              'not_used_local_pdf', ?, 0.92, ?, ?, 'local_pdf_text',
                              ?, 'pdf_text', ?, ?, ?)
                    """,
                    (
                        candidate_id,
                        current_source["centre_code"],
                        source_file_id,
                        payload.edc_subject_ref,
                        payload.edc_event_ref,
                        candidate.field_code,
                        candidate.proposed_value,
                        candidate.unit,
                        extraction.engine_version,
                        schema_version,
                        candidate.proposed_value,
                        candidate.unit,
                        candidate.evidence_text,
                        extraction_run["id"],
                        user.username,
                        created_at,
                    ),
                )
                audit(
                    connection,
                    candidate_id=candidate_id,
                    centre_code=current_source["centre_code"],
                    event_type="candidate_created",
                    actor_username=user.username,
                    details={
                        "status": "candidate",
                        "field_code": candidate.field_code,
                        "mode": "local_pdf_pulmonary_function",
                        "crf_mapping_version": resolved_crf_mapping.mapping_version,
                        "remote_model_used": False,
                    },
                )
                created.append(candidate_payload(get_candidate(connection, candidate_id)))
        return created

    @app.post("/api/source-files/{source_file_id}/local-ocr-extract", status_code=status.HTTP_201_CREATED)
    def local_ocr_extract(
        source_file_id: str,
        payload: LocalOcrExtractPayload,
        response: Response,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> list[dict[str, object]]:
        require_workflow_write_role(user)
        selected_fields = recognition_field_scope(payload.edc_event_ref, payload.field_codes)
        with database.connect() as connection:
            source_file = connection.execute("SELECT * FROM source_files WHERE id = ?", (source_file_id,)).fetchone()
            if source_file is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="source_file_not_found")
            assert_centre_access(user, source_file["centre_code"])
            if source_file["storage_key"].startswith("deidentified/"):
                assert_source_ready_for_candidates(connection, source_file)
            elif not source_file["storage_key"].startswith("synthetic/"):
                raise HTTPException(status_code=409, detail="synthetic_source_file_required")
            upload_path = stored_source_path(source_file)
            existing_candidates = connection.execute(
                f"""
                {candidate_select_sql()}
                WHERE candidates.source_file_id = ?
                  AND candidates.edc_event_ref = ?
                  AND candidates.schema_version LIKE 'local-ocr-lab-candidate-v1+%'
                ORDER BY candidates.created_at, candidates.id
                """,
                (source_file_id, payload.edc_event_ref),
            ).fetchall()
            if existing_candidates:
                if any(
                    candidate["edc_subject_ref"] != payload.edc_subject_ref
                    for candidate in existing_candidates
                ):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="source_event_subject_conflict",
                    )
            if existing_candidates and (payload.field_codes is None or set(selected_fields).issubset(
                {candidate["field_code"] for candidate in existing_candidates}
            )):
                response.status_code = status.HTTP_200_OK
                return [
                    candidate_payload(candidate)
                    for candidate in existing_candidates
                    if candidate["field_code"] in selected_fields
                ]

        try:
            extraction_started = time.perf_counter()
            extraction = resolved_ocr_client.extract(upload_path)
        except LocalOcrUnavailable as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
        except LocalOcrFailed as error:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error

        allowed_fields = selected_fields
        try:
            parsed_values = parse_demo_lab_text(extraction.text)
        except HTTPException as error:
            if error.detail != "no_demo_lab_values_found":
                raise
            parsed_values = []
        extraction_engine_version = extraction.engine_version
        extraction_mode = "plain_ocr"
        ambiguous_field_codes: list[str] = []
        candidate_confidence = 0.6
        candidate_schema_version = f"local-ocr-lab-candidate-v1+{resolved_crf_mapping.mapping_version}"
        if (
            resolved_lab_extractor is not None
            and not any(field_code in allowed_fields for field_code, _, _ in parsed_values)
        ):
            try:
                structured_extraction = resolved_lab_extractor.extract(upload_path)
            except ChineseLabExtractionUnavailable as error:
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
            except ChineseLabExtractionFailed as error:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
            parsed_values = list(structured_extraction.candidates)
            extraction_engine_version = structured_extraction.engine_version
            extraction_mode = "structured_chinese_table"
            ambiguous_field_codes = sorted(set(structured_extraction.ambiguous_field_codes))
            candidate_confidence = 0.55
            alias_mapping_version = getattr(resolved_lab_extractor, "mapping_version", "structured-chinese")
            candidate_schema_version = (
                f"local-ocr-lab-candidate-v1+{resolved_crf_mapping.mapping_version}+{alias_mapping_version}"
            )
        ignored_unmapped_field_codes = sorted(
            {field_code for field_code, _, _ in parsed_values if field_code not in allowed_fields}
        )
        parsed_values = [
            parsed_value for parsed_value in parsed_values if parsed_value[0] in allowed_fields
        ]
        if not parsed_values:
            raise HTTPException(status_code=422, detail="field_not_in_crf_mapping")
        idempotency_key, evidence = build_extraction_evidence(
            source_file_id=source_file["id"],
            source_sha256=source_file["sha256"],
            derivative_sha256=source_file["sha256"] if source_file["storage_key"].startswith("deidentified/") else None,
            dictionary_id="clinical-crf",
            dictionary_version=resolved_crf_mapping.mapping_version,
            selected_fields=selected_fields,
            engine="local_ocr",
            engine_version=extraction_engine_version,
            duration_ms=round((time.perf_counter() - extraction_started) * 1000),
            spans=tuple(
                EvidenceSpan(field_code=field_code, page_number=None, text=f"local OCR field {field_code}")
                for field_code, _, _ in parsed_values
            ),
            warnings=ignored_unmapped_field_codes,
        )
        with database.connect() as connection:
            source_file = connection.execute("SELECT * FROM source_files WHERE id = ?", (source_file_id,)).fetchone()
            if source_file is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="source_file_not_found")
            assert_centre_access(user, source_file["centre_code"])
            extraction_run = persist_extraction_run(
                connection,
                source_file=source_file,
                subject_ref=payload.edc_subject_ref,
                event_ref=payload.edc_event_ref,
                dictionary_id="clinical-crf",
                dictionary_version=resolved_crf_mapping.mapping_version,
                engine="local_ocr",
                engine_version=extraction_engine_version,
                model_ids=[],
                duration_ms=int(evidence["duration_ms"]),
                evidence=evidence,
                idempotency_key=idempotency_key,
                created_by=user.username,
            )
            existing_run_candidates = connection.execute(
                f"{candidate_select_sql()} WHERE candidates.extraction_run_id = ? ORDER BY candidates.created_at, candidates.id",
                (extraction_run["id"],),
            ).fetchall()
            if existing_run_candidates:
                response.status_code = status.HTTP_200_OK
                return [
                    candidate_payload(candidate)
                    for candidate in existing_run_candidates
                    if candidate["field_code"] in selected_fields
                ]
            created: list[dict[str, object]] = []
            for field_code, proposed_value, unit in parsed_values:
                candidate_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO candidates (
                        id, centre_code, source_file_id, edc_subject_ref, edc_event_ref, field_code, proposed_value,
                        unit, final_value, status, ocr_engine_version, kimi_model, schema_version, confidence,
                        extraction_run_id, created_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'candidate', ?, 'not_used_local_ocr',
                              ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate_id,
                        source_file["centre_code"],
                        source_file_id,
                        payload.edc_subject_ref,
                        payload.edc_event_ref,
                        field_code,
                        proposed_value,
                        unit,
                        extraction_engine_version,
                        candidate_schema_version,
                        candidate_confidence,
                        extraction_run["id"],
                        user.username,
                        utc_now(),
                    ),
                )
                audit(
                    connection,
                    candidate_id=candidate_id,
                    centre_code=source_file["centre_code"],
                    event_type="candidate_created",
                    actor_username=user.username,
                    details={
                        "status": "candidate",
                        "field_code": field_code,
                        "mode": "local_ocr",
                        "extraction_mode": extraction_mode,
                        "crf_mapping_version": resolved_crf_mapping.mapping_version,
                        "chinese_alias_mapping_version": (
                            getattr(resolved_lab_extractor, "mapping_version", None)
                            if extraction_mode == "structured_chinese_table"
                            else None
                        ),
                        "ignored_unmapped_field_codes": ignored_unmapped_field_codes,
                        "ambiguous_field_codes": ambiguous_field_codes,
                    },
                )
                created.append(candidate_payload(get_candidate(connection, candidate_id)))
        return created

    @app.post("/api/source-files/{source_file_id}/hybrid-extract", status_code=status.HTTP_201_CREATED)
    def hybrid_extract(
        source_file_id: str,
        payload: HybridExtractPayload,
        response: Response,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> list[dict[str, object]]:
        require_workflow_write_role(user)
        selected_fields = recognition_field_scope(payload.edc_event_ref, payload.field_codes)
        with database.connect() as connection:
            source_file = connection.execute("SELECT * FROM source_files WHERE id = ?", (source_file_id,)).fetchone()
            if source_file is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="source_file_not_found")
            assert_centre_access(user, source_file["centre_code"])
            if not source_file["storage_key"].startswith("deidentified/"):
                raise HTTPException(status_code=409, detail="confirmed_deidentified_source_required")
            assert_source_ready_for_candidates(connection, source_file)
            upload_path = stored_source_path(source_file)
            existing_candidates = connection.execute(
                f"""
                {candidate_select_sql()}
                WHERE candidates.source_file_id = ?
                  AND candidates.edc_event_ref = ?
                  AND candidates.schema_version LIKE 'hybrid-lab-candidate-v1+%'
                ORDER BY candidates.created_at, candidates.id
                """,
                (source_file_id, payload.edc_event_ref),
            ).fetchall()
            if existing_candidates:
                if any(
                    candidate["edc_subject_ref"] != payload.edc_subject_ref
                    for candidate in existing_candidates
                ):
                    raise HTTPException(status_code=409, detail="source_event_subject_conflict")
            if existing_candidates and (payload.field_codes is None or set(selected_fields).issubset(
                {candidate["field_code"] for candidate in existing_candidates}
            )):
                response.status_code = status.HTTP_200_OK
                return [
                    candidate_payload(candidate)
                    for candidate in existing_candidates
                    if candidate["field_code"] in selected_fields
                ]

        try:
            extraction_started = time.perf_counter()
            extraction = resolved_ocr_client.extract(upload_path)
        except LocalOcrUnavailable as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
        except LocalOcrFailed as error:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error

        allowed_fields = selected_fields
        try:
            local_values = parse_demo_lab_text(extraction.text)
        except HTTPException as error:
            if error.detail != "no_demo_lab_values_found":
                raise
            local_values = []
        extraction_engine_version = extraction.engine_version
        extraction_mode = "plain_ocr"
        ambiguous_field_codes: list[str] = []
        if (
            resolved_lab_extractor is not None
            and not any(field_code in allowed_fields for field_code, _, _ in local_values)
        ):
            try:
                structured_extraction = resolved_lab_extractor.extract(upload_path)
            except (ChineseLabExtractionUnavailable, ChineseLabExtractionFailed):
                structured_extraction = None
            if structured_extraction is not None:
                local_values = list(structured_extraction.candidates)
                extraction_engine_version = structured_extraction.engine_version
                extraction_mode = "structured_chinese_table"
                ambiguous_field_codes = sorted(set(structured_extraction.ambiguous_field_codes))

        ignored_unmapped_field_codes = sorted(
            {field_code for field_code, _, _ in local_values if field_code not in allowed_fields}
        )
        local_values = [item for item in local_values if item[0] in allowed_fields]
        local_by_field = {field_code: (value, unit) for field_code, value, unit in local_values}

        ocr_evidence = ""
        if hasattr(resolved_ocr_client, "extract_tsv"):
            try:
                tsv_extraction = resolved_ocr_client.extract_tsv(upload_path)
                ocr_evidence = str(tsv_extraction.tsv)[:100_000]
            except (LocalOcrUnavailable, LocalOcrFailed):
                ocr_evidence = ""

        kimi_candidates = []
        kimi_error: str | None = None
        kimi_requested = payload.use_kimi
        kimi_attempted = kimi_requested and resolved_kimi_client.enabled
        if kimi_attempted:
            try:
                kimi_candidates = resolved_kimi_client.extract_candidates(
                    extraction.text,
                    image_bytes=upload_path.read_bytes(),
                    media_type=source_file["mime_type"],
                    ocr_evidence=ocr_evidence,
                    event_ref=payload.edc_event_ref,
                    field_dictionary={
                        field_code: display_header
                        for field_code, display_header in effective_field_dictionary(
                            payload.edc_event_ref
                        ).items()
                        if field_code in selected_fields
                    },
                )
                resolved_crf_mapping.assert_allowed(
                    payload.edc_event_ref,
                    (candidate.field_code for candidate in kimi_candidates),
                )
            except (KimiConfigurationError, KimiServiceError, CrfMappingError) as error:
                kimi_error = type(error).__name__
                kimi_candidates = []

        kimi_by_field = {
            candidate.field_code: candidate
            for candidate in kimi_candidates
            if candidate.status != "not_visible" and candidate.field_code in selected_fields
        }
        ordered_field_codes = list(local_by_field)
        ordered_field_codes.extend(code for code in kimi_by_field if code not in local_by_field)
        if not ordered_field_codes:
            if kimi_attempted and kimi_error is not None:
                raise HTTPException(status_code=502, detail="kimi_extraction_failed_no_local_fallback")
            raise HTTPException(status_code=422, detail="field_not_in_crf_mapping")

        created_at = utc_now()
        schema_version = f"hybrid-lab-candidate-v1+{resolved_crf_mapping.mapping_version}"
        evidence_spans = tuple(
            EvidenceSpan(
                field_code=field_code,
                page_number=None,
                text=(
                    kimi_by_field[field_code].evidence_text
                    if field_code in kimi_by_field
                    else f"local OCR field {field_code}"
                ),
            )
            for field_code in ordered_field_codes
        )
        model_ids = [resolved_kimi_client.settings.model] if kimi_attempted else []
        idempotency_key, evidence = build_extraction_evidence(
            source_file_id=source_file["id"],
            source_sha256=source_file["sha256"],
            derivative_sha256=source_file["sha256"],
            dictionary_id="clinical-crf",
            dictionary_version=resolved_crf_mapping.mapping_version,
            selected_fields=selected_fields,
            engine="hybrid_ocr_kimi" if kimi_attempted else "hybrid_local_ocr",
            engine_version=extraction_engine_version,
            model_ids=model_ids,
            duration_ms=round((time.perf_counter() - extraction_started) * 1000),
            spans=evidence_spans,
            warnings=ignored_unmapped_field_codes + ([kimi_error] if kimi_error else []),
        )
        with database.connect() as connection:
            current_source = connection.execute(
                "SELECT * FROM source_files WHERE id = ?", (source_file_id,)
            ).fetchone()
            if current_source is None:
                raise HTTPException(status_code=404, detail="source_file_not_found")
            assert_centre_access(user, current_source["centre_code"])
            assert_source_ready_for_candidates(connection, current_source)
            extraction_run = persist_extraction_run(
                connection,
                source_file=current_source,
                subject_ref=payload.edc_subject_ref,
                event_ref=payload.edc_event_ref,
                dictionary_id="clinical-crf",
                dictionary_version=resolved_crf_mapping.mapping_version,
                engine="hybrid_ocr_kimi" if kimi_attempted else "hybrid_local_ocr",
                engine_version=extraction_engine_version,
                model_ids=model_ids,
                duration_ms=int(evidence["duration_ms"]),
                evidence=evidence,
                idempotency_key=idempotency_key,
                created_by=user.username,
            )
            existing_run_candidates = connection.execute(
                f"{candidate_select_sql()} WHERE candidates.extraction_run_id = ? ORDER BY candidates.created_at, candidates.id",
                (extraction_run["id"],),
            ).fetchall()
            if existing_run_candidates:
                response.status_code = status.HTTP_200_OK
                return [
                    candidate_payload(candidate)
                    for candidate in existing_run_candidates
                    if candidate["field_code"] in selected_fields
                ]
            created: list[dict[str, object]] = []
            for field_code in ordered_field_codes:
                local_value, local_unit = local_by_field.get(field_code, (None, None))
                kimi_candidate = kimi_by_field.get(field_code)
                if kimi_candidate is not None and local_value is not None:
                    agrees = (
                        normalise_candidate_comparison(kimi_candidate.proposed_value)
                        == normalise_candidate_comparison(local_value)
                        and normalise_candidate_comparison(kimi_candidate.unit)
                        == normalise_candidate_comparison(local_unit)
                    )
                    agreement = "agreement" if agrees else "conflict"
                elif kimi_candidate is not None:
                    agreement = "kimi_only"
                elif kimi_attempted and kimi_error is not None:
                    agreement = "local_fallback"
                else:
                    agreement = "local_only"

                proposed_value = kimi_candidate.proposed_value if kimi_candidate is not None else local_value
                unit = kimi_candidate.unit if kimi_candidate is not None else local_unit
                if proposed_value is None:
                    continue
                confidence = {
                    "agreement": 0.9,
                    "conflict": 0.4,
                    "kimi_only": 0.45,
                    "local_fallback": 0.5,
                    "local_only": 0.55,
                }[agreement]
                candidate_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO candidates (
                        id, centre_code, source_file_id, edc_subject_ref, edc_event_ref, field_code,
                        proposed_value, unit, final_value, status, ocr_engine_version, kimi_model,
                        schema_version, confidence, local_ocr_value, local_ocr_unit,
                        extraction_agreement, evidence_text, extraction_run_id, created_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'candidate', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate_id,
                        current_source["centre_code"],
                        source_file_id,
                        payload.edc_subject_ref,
                        payload.edc_event_ref,
                        field_code,
                        proposed_value,
                        unit,
                        extraction_engine_version,
                        (
                            resolved_kimi_client.settings.model
                            if kimi_candidate is not None or (kimi_attempted and kimi_error is not None)
                            else "not_used_user_disabled"
                            if not kimi_requested
                            else "not_used_local_ocr"
                        ),
                        schema_version,
                        confidence,
                        local_value,
                        local_unit,
                        agreement,
                        kimi_candidate.evidence_text if kimi_candidate is not None else None,
                        extraction_run["id"],
                        user.username,
                        created_at,
                    ),
                )
                audit(
                    connection,
                    candidate_id=candidate_id,
                    centre_code=current_source["centre_code"],
                    event_type="candidate_created",
                    actor_username=user.username,
                    details={
                        "status": "candidate",
                        "field_code": field_code,
                        "mode": (
                            "hybrid_ocr_kimi"
                            if kimi_candidate is not None
                            else "hybrid_local_only"
                            if not kimi_requested or kimi_error is None
                            else "hybrid_local_fallback"
                        ),
                        "extraction_mode": extraction_mode,
                        "extraction_agreement": agreement,
                        "kimi_requested": kimi_requested,
                        "kimi_available": resolved_kimi_client.enabled,
                        "kimi_error": kimi_error,
                        "crf_mapping_version": resolved_crf_mapping.mapping_version,
                        "ignored_unmapped_field_codes": ignored_unmapped_field_codes,
                        "ambiguous_field_codes": ambiguous_field_codes,
                    },
                )
                created.append(candidate_payload(get_candidate(connection, candidate_id)))
        return created

    @app.post("/api/recognition-jobs/{job_id}/run")
    def run_recognition_job(
        job_id: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        """Run queued items through the existing local extraction seam.

        The endpoint is intentionally caller-triggered and bounded; it is a
        recovery bridge until a separately qualified background worker exists.
        """
        require_workflow_write_role(user)
        now = utc_now()
        with database.connect() as connection:
            job = load_recognition_job(connection, job_id, user)
            if job["status"] == "running":
                raise HTTPException(status_code=409, detail="recognition_job_already_running")
            if job["status"] in {"succeeded", "cancelled"}:
                raise HTTPException(status_code=409, detail="recognition_job_not_runnable")
            items = connection.execute(
                "SELECT * FROM recognition_job_items WHERE job_id = ? AND status IN ('queued', 'failed') ORDER BY created_at, id",
                (job_id,),
            ).fetchall()
            claimed = connection.execute(
                """
                UPDATE recognition_jobs
                SET status = 'running', updated_at = ?
                WHERE id = ? AND status IN ('queued', 'failed')
                """,
                (now, job_id),
            )
            if claimed.rowcount != 1:
                latest = connection.execute(
                    "SELECT status FROM recognition_jobs WHERE id = ?",
                    (job_id,),
                ).fetchone()
                if latest is not None and latest["status"] == "running":
                    raise HTTPException(status_code=409, detail="recognition_job_already_running")
                raise HTTPException(status_code=409, detail="recognition_job_not_runnable")

        allowed_error_codes = {
            "pulmonary_pdf_required",
            "confirmed_deidentified_source_required",
            "local_source_file_required",
            "synthetic_source_file_required",
            "pdf_encrypted",
            "pdf_text_layer_required",
            "pulmonary_report_values_not_found",
            "pulmonary_pdf_parse_failed",
            "pulmonary_pdf_page_limit",
            "field_not_in_crf_mapping",
            "kimi_extraction_failed_no_local_fallback",
            "source_event_subject_conflict",
        }
        for item in items:
            item_started = utc_now()
            with database.connect() as connection:
                connection.execute(
                    "UPDATE recognition_job_items SET status = 'running', attempts = attempts + 1, started_at = ? WHERE id = ?",
                    (item_started, item["id"]),
                )
            try:
                with database.connect() as connection:
                    source = connection.execute(
                        "SELECT * FROM source_files WHERE id = ?",
                        (item["source_file_id"],),
                    ).fetchone()
                    if source is None:
                        raise HTTPException(status_code=404, detail="source_file_not_found")
                    source_id = item["source_file_id"]
                    if source["mime_type"] != "application/pdf" and not str(source["storage_key"]).startswith("deidentified/"):
                        draft = connection.execute(
                            "SELECT derivative_source_file_id, status FROM deidentification_drafts WHERE original_source_file_id = ?",
                            (source_id,),
                        ).fetchone()
                        if draft is None or draft["status"] != "confirmed":
                            raise HTTPException(status_code=409, detail="confirmed_deidentified_source_required")
                        source_id = draft["derivative_source_file_id"]
                requested_fields = json.loads(item["field_codes_json"]) if item["field_codes_json"] else None
                if source["mime_type"] == "application/pdf":
                    result = pulmonary_function_extract(
                        source_id,
                        LocalOcrExtractPayload(
                            edc_subject_ref=item["edc_subject_ref"],
                            edc_event_ref=item["edc_event_ref"],
                            field_codes=requested_fields,
                        ),
                        Response(),
                        user,
                    )
                else:
                    result = hybrid_extract(
                        source_id,
                        HybridExtractPayload(
                            edc_subject_ref=item["edc_subject_ref"],
                            edc_event_ref=item["edc_event_ref"],
                            field_codes=requested_fields,
                            use_kimi=bool(item["use_kimi"]),
                        ),
                        Response(),
                        user,
                    )
                with database.connect() as connection:
                    candidate_ids = [str(candidate["id"]) for candidate in result]
                    connection.execute(
                        "UPDATE recognition_job_items SET status = 'succeeded', candidate_ids_json = ?, error_code = NULL, error_message = NULL, finished_at = ? WHERE id = ?",
                        (json.dumps(candidate_ids), utc_now(), item["id"]),
                    )
            except HTTPException as error:
                detail = str(error.detail)
                error_code = detail if detail in allowed_error_codes else "recognition_failed"
                with database.connect() as connection:
                    connection.execute(
                        "UPDATE recognition_job_items SET status = 'failed', error_code = ?, error_message = ?, finished_at = ? WHERE id = ?",
                        (error_code, error_code, utc_now(), item["id"]),
                    )
            except Exception:
                with database.connect() as connection:
                    connection.execute(
                        "UPDATE recognition_job_items SET status = 'failed', error_code = 'recognition_failed', error_message = 'recognition_failed', finished_at = ? WHERE id = ?",
                        (utc_now(), item["id"]),
                    )
        with database.connect() as connection:
            row = refresh_recognition_job_status(connection, job_id, utc_now())
            audit(
                connection,
                candidate_id=None,
                centre_code=row["centre_code"],
                event_type="recognition_job_run",
                actor_username=user.username,
                details={"job_id": job_id, "item_count": len(items)},
            )
            return recognition_job_payload(connection, row)

    @app.post("/api/source-files/{source_file_id}/kimi-extract", status_code=status.HTTP_201_CREATED)
    def kimi_extract(
        source_file_id: str,
        payload: DemoExtractPayload,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> list[dict[str, object]]:
        require_workflow_write_role(user)
        with database.connect() as connection:
            source_file = connection.execute("SELECT * FROM source_files WHERE id = ?", (source_file_id,)).fetchone()
            if source_file is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="source_file_not_found")
            assert_centre_access(user, source_file["centre_code"])
            assert_source_ready_for_candidates(connection, source_file)
            upload_path = stored_source_path(source_file)
        try:
            if not resolved_kimi_client.enabled:
                raise KimiConfigurationError("kimi_integration_disabled")
            if not source_file["storage_key"].startswith("deidentified/"):
                raise HTTPException(status_code=409, detail="confirmed_deidentified_source_required")
            extracted_candidates = resolved_kimi_client.extract_candidates(
                payload.deidentified_ocr_text,
                image_bytes=upload_path.read_bytes(),
                media_type=source_file["mime_type"],
                event_ref=payload.edc_event_ref,
                field_dictionary=effective_field_dictionary(payload.edc_event_ref),
            )
        except HTTPException:
            raise
        except KimiConfigurationError as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
        except KimiServiceError as error:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="kimi_extraction_failed") from error
        try:
            resolved_crf_mapping.assert_allowed(payload.edc_event_ref, (candidate.field_code for candidate in extracted_candidates))
        except CrfMappingError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        with database.connect() as connection:
            source_file = connection.execute("SELECT * FROM source_files WHERE id = ?", (source_file_id,)).fetchone()
            if source_file is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="source_file_not_found")
            assert_centre_access(user, source_file["centre_code"])
            assert_source_ready_for_candidates(connection, source_file)
            created: list[dict[str, object]] = []
            for extracted in extracted_candidates:
                if extracted.status == "not_visible" or extracted.proposed_value is None:
                    continue
                candidate_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO candidates (
                        id, centre_code, source_file_id, edc_subject_ref, edc_event_ref, field_code, proposed_value,
                        unit, final_value, status, ocr_engine_version, kimi_model, schema_version, confidence,
                        extraction_agreement, evidence_text, created_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'candidate', 'local-ocr-text-v1', ?,
                              ?, ?, 'kimi_only', ?, ?, ?)
                    """,
                    (
                        candidate_id,
                        source_file["centre_code"],
                        source_file_id,
                        payload.edc_subject_ref,
                        payload.edc_event_ref,
                        extracted.field_code,
                        extracted.proposed_value,
                        extracted.unit,
                        resolved_kimi_client.settings.model,
                        f"lab-candidate-v1+{resolved_crf_mapping.mapping_version}",
                        extracted.confidence,
                        extracted.evidence_text,
                        user.username,
                        utc_now(),
                    ),
                )
                audit(
                    connection,
                    candidate_id=candidate_id,
                    centre_code=source_file["centre_code"],
                    event_type="candidate_created",
                    actor_username=user.username,
                    details={
                        "status": "candidate",
                        "field_code": extracted.field_code,
                        "mode": "kimi_extract",
                        "crf_mapping_version": resolved_crf_mapping.mapping_version,
                    },
                )
                created.append(candidate_payload(get_candidate(connection, candidate_id)))
        return created

    @app.get("/api/candidates")
    def list_candidates(user: Annotated[UserContext, Depends(current_user)]) -> list[dict[str, object]]:
        with database.connect() as connection:
            if user.role in GLOBAL_READ_ROLES:
                rows = connection.execute(f"{candidate_select_sql()} ORDER BY candidates.created_at").fetchall()
            else:
                rows = connection.execute(
                    f"{candidate_select_sql()} WHERE candidates.centre_code = ? ORDER BY candidates.created_at",
                    (user.centre_code,),
                ).fetchall()
        return [candidate_payload(row) for row in rows]

    @app.get("/api/candidates/{candidate_id}")
    def read_candidate(candidate_id: str, user: Annotated[UserContext, Depends(current_user)]) -> dict[str, object]:
        with database.connect() as connection:
            row = get_candidate(connection, candidate_id)
            assert_centre_access(user, row["centre_code"])
        return candidate_payload(row)

    @app.get("/api/candidates/{candidate_id}/evidence-image")
    def candidate_evidence_image(
        candidate_id: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> FileResponse:
        if user.role not in REVIEWER_ROLES:
            raise HTTPException(status_code=403, detail="reviewer_role_required")
        with database.connect() as connection:
            candidate = get_candidate(connection, candidate_id)
            assert_centre_access(user, candidate["centre_code"])
            if bulk_policy_source(candidate) not in {"conflict", "kimi_only"}:
                raise HTTPException(status_code=409, detail="candidate_evidence_image_not_required")
            source_file = connection.execute(
                "SELECT * FROM source_files WHERE id = ?", (candidate["source_file_id"],)
            ).fetchone()
            if source_file is None or not str(source_file["storage_key"]).startswith("deidentified/"):
                raise HTTPException(status_code=409, detail="candidate_deidentified_evidence_required")
            assert_source_ready_for_candidates(connection, source_file)
            evidence_path = stored_source_path(source_file)
        if not evidence_path.is_file():
            raise HTTPException(status_code=404, detail="deidentified_derivative_not_found")
        return FileResponse(
            evidence_path,
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/extraction-runs/{run_id}")
    def read_extraction_run(
        run_id: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        with database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM extraction_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="extraction_run_not_found")
            assert_centre_access(user, row["centre_code"])
        return extraction_run_payload(row)

    @app.get("/api/quality/rules")
    def read_quality_rules(
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        del user
        fields = resolved_quality_rules.get("fields", {})
        return {
            "version": resolved_quality_rules["version"],
            "configured_field_count": len(fields) if isinstance(fields, Mapping) else 0,
            "statuses": ["PASS", "WARN", "BLOCK"],
            "clinical_interpretation": "not_provided",
        }

    @app.get("/api/candidates/{candidate_id}/quality")
    def read_candidate_quality(
        candidate_id: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        with database.connect() as connection:
            candidate = get_candidate(connection, candidate_id)
            assert_centre_access(user, candidate["centre_code"])
            return latest_quality_assessment(connection, candidate)

    @app.post("/api/candidates/{candidate_id}/quality/re-evaluate")
    def re_evaluate_candidate_quality(
        candidate_id: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        if user.role not in REVIEWER_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="reviewer_role_required")
        with database.connect() as connection:
            candidate = get_candidate(connection, candidate_id)
            assert_centre_access(user, candidate["centre_code"])
            return evaluate_and_store_quality(
                connection,
                candidate,
                value=str(candidate["final_value"] or candidate["proposed_value"]),
                unit=candidate["unit"],
                actor_username=user.username,
            )

    @app.get("/api/tasks")
    def list_tasks(
        user: Annotated[UserContext, Depends(current_user)],
        task_status: Annotated[Literal["open", "completed"] | None, Query(alias="status")] = None,
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        parameters: list[object] = []
        if user.role not in GLOBAL_READ_ROLES:
            clauses.extend(("centre_code = ?", "assigned_role = ?"))
            parameters.extend((user.centre_code, user.role))
        if task_status is not None:
            clauses.append("status = ?")
            parameters.append(task_status)
        query = "SELECT * FROM tasks"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, created_at, rowid"
        with database.connect() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return [task_payload(row) for row in rows]

    @app.post("/api/tasks/{task_id}/complete")
    def complete_task(
        task_id: str,
        payload: TaskCompletePayload,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_workflow_write_role(user)
        with database.connect() as connection:
            task = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if task is None:
                raise HTTPException(status_code=404, detail="not_found")
            assert_centre_access(user, task["centre_code"])
            if user.role != "central_data_manager" and task["assigned_role"] != user.role:
                raise HTTPException(status_code=403, detail="task_not_assigned_to_role")
            if task["status"] != "open":
                raise HTTPException(status_code=409, detail="task_not_open")
            completed_at = utc_now()
            connection.execute(
                """
                UPDATE tasks SET status = 'completed', completed_by = ?, completed_at = ?,
                                 completion_note = ?
                WHERE id = ? AND status = 'open'
                """,
                (user.username, completed_at, payload.note, task_id),
            )
            audit(
                connection,
                candidate_id=task["candidate_id"],
                centre_code=task["centre_code"],
                event_type="operations_task_completed",
                actor_username=user.username,
                details={"task_id": task_id, "task_type": task["task_type"], "note": payload.note},
            )
            updated = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return task_payload(updated)

    @app.get("/api/dashboard")
    def operations_dashboard(
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        with database.connect() as connection:
            if user.role in GLOBAL_READ_ROLES:
                centre_rows = connection.execute(
                    """
                    SELECT centre_code FROM candidates
                    UNION SELECT centre_code FROM users WHERE centre_code IS NOT NULL AND active = 1
                    ORDER BY centre_code
                    """
                ).fetchall()
                centre_codes = [str(row["centre_code"]) for row in centre_rows]
            else:
                centre_codes = [str(user.centre_code)]
            metrics: list[dict[str, object]] = []
            for centre_code in centre_codes:
                candidate_counts = connection.execute(
                    """
                    SELECT COUNT(DISTINCT edc_subject_ref) AS subjects,
                           COUNT(DISTINCT edc_subject_ref || ':' || edc_event_ref) AS visits,
                           SUM(CASE WHEN status = 'candidate' THEN 1 ELSE 0 END) AS pending_reviews
                    FROM candidates WHERE centre_code = ?
                    """,
                    (centre_code,),
                ).fetchone()
                open_issues = connection.execute(
                    "SELECT COUNT(*) AS count FROM data_issues WHERE centre_code = ? AND status IN ('open', 'answered')",
                    (centre_code,),
                ).fetchone()["count"]
                blocking_findings = connection.execute(
                    """
                    SELECT COUNT(*) AS count FROM quality_findings AS current
                    WHERE current.centre_code = ? AND current.status = 'BLOCK'
                      AND NOT EXISTS (
                          SELECT 1 FROM quality_findings AS later
                          WHERE later.candidate_id = current.candidate_id
                            AND (later.evaluated_at > current.evaluated_at OR
                                 (later.evaluated_at = current.evaluated_at AND later.rowid > current.rowid))
                      )
                    """,
                    (centre_code,),
                ).fetchone()["count"]
                transfer_rows = connection.execute(
                    "SELECT status, COUNT(*) AS count FROM transfer_requests WHERE centre_code = ? GROUP BY status",
                    (centre_code,),
                ).fetchall()
                readback_rows = connection.execute(
                    "SELECT readback_status, COUNT(*) AS count FROM transfer_requests WHERE centre_code = ? GROUP BY readback_status",
                    (centre_code,),
                ).fetchall()
                open_tasks = connection.execute(
                    "SELECT COUNT(*) AS count FROM tasks WHERE centre_code = ? AND status = 'open'",
                    (centre_code,),
                ).fetchone()["count"]
                attested_visits = connection.execute(
                    """
                    SELECT COUNT(DISTINCT subject_ref || ':' || event_ref) AS count
                    FROM visit_attestations WHERE centre_code = ?
                    """,
                    (centre_code,),
                ).fetchone()["count"]
                metrics.append(
                    {
                        "centre_code": centre_code,
                        "subjects": candidate_counts["subjects"] or 0,
                        "visits": candidate_counts["visits"] or 0,
                        "attested_visits": attested_visits,
                        "pending_reviews": candidate_counts["pending_reviews"] or 0,
                        "open_data_issues": open_issues,
                        "blocking_findings": blocking_findings,
                        "open_tasks": open_tasks,
                        "transfers": {row["status"]: row["count"] for row in transfer_rows},
                        "readback": {row["readback_status"]: row["count"] for row in readback_rows},
                    }
                )
        numeric_keys = (
            "subjects",
            "visits",
            "attested_visits",
            "pending_reviews",
            "open_data_issues",
            "blocking_findings",
            "open_tasks",
        )
        overall: dict[str, object] = {
            key: sum(int(row[key]) for row in metrics) for key in numeric_keys
        }
        overall["transfers"] = {
            state: sum(int(row["transfers"].get(state, 0)) for row in metrics)
            for state in {state for row in metrics for state in row["transfers"]}
        }
        overall["readback"] = {
            state: sum(int(row["readback"].get(state, 0)) for row in metrics)
            for state in {state for row in metrics for state in row["readback"]}
        }
        return {
            "scope": "ALL_CENTRES" if user.role in GLOBAL_READ_ROLES else user.centre_code,
            "generated_at": utc_now(),
            "quality_rule_version": resolved_quality_rules["version"],
            "authority_boundary": "formal_queries_signatures_freezes_and_locks_remain_in_libreclinica",
            "overall": overall,
            "centres": metrics,
        }

    @app.get("/api/data-issues")
    def list_data_issues(
        user: Annotated[UserContext, Depends(current_user)],
        issue_status: Annotated[str | None, Query(alias="status")] = None,
        centre_code: str | None = None,
        candidate_id: str | None = None,
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        parameters: list[object] = []
        if user.role not in GLOBAL_READ_ROLES:
            clauses.append("centre_code = ?")
            parameters.append(user.centre_code)
        elif centre_code:
            clauses.append("centre_code = ?")
            parameters.append(centre_code)
        if issue_status:
            clauses.append("status = ?")
            parameters.append(issue_status)
        if candidate_id:
            clauses.append("candidate_id = ?")
            parameters.append(candidate_id)
        query = "SELECT * FROM data_issues"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY opened_at, rowid"
        with database.connect() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return [data_issue_payload(row) for row in rows]

    @app.post("/api/candidates/{candidate_id}/data-issues", status_code=status.HTTP_201_CREATED)
    def open_data_issue(
        candidate_id: str,
        payload: IssueMessagePayload,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_central_data_manager(user)
        with database.connect() as connection:
            candidate = get_candidate(connection, candidate_id)
            issue_id = str(uuid4())
            opened_at = utc_now()
            connection.execute(
                """
                INSERT INTO data_issues (
                    id, candidate_id, centre_code, status, opened_message, opened_by, opened_at
                ) VALUES (?, ?, ?, 'open', ?, ?, ?)
                """,
                (
                    issue_id,
                    candidate_id,
                    candidate["centre_code"],
                    payload.message,
                    user.username,
                    opened_at,
                ),
            )
            audit(
                connection,
                candidate_id=candidate_id,
                centre_code=candidate["centre_code"],
                event_type="companion_data_issue_opened",
                actor_username=user.username,
                details={"issue_id": issue_id, "message": payload.message},
            )
            create_or_reopen_task(
                connection,
                centre_code=candidate["centre_code"],
                task_type="data_issue_response",
                assigned_role="site_investigator",
                title="Answer companion data issue",
                dedupe_key=f"data-issue-response:{issue_id}",
                candidate_id=candidate_id,
                data_issue_id=issue_id,
            )
            issue = get_data_issue(connection, issue_id)
        return data_issue_payload(issue)

    @app.post("/api/data-issues/{issue_id}/answer")
    def answer_data_issue(
        issue_id: str,
        payload: IssueMessagePayload,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        if user.role != "site_investigator":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="site_investigator_required")
        with database.connect() as connection:
            issue = get_data_issue(connection, issue_id)
            assert_centre_access(user, issue["centre_code"])
            if issue["status"] != "open":
                raise HTTPException(status_code=409, detail="query_transition_not_allowed")
            answered_at = utc_now()
            connection.execute(
                """
                UPDATE data_issues
                SET status = 'answered', answer_message = ?, answered_by = ?, answered_at = ?
                WHERE id = ?
                """,
                (payload.message, user.username, answered_at, issue_id),
            )
            audit(
                connection,
                candidate_id=issue["candidate_id"],
                centre_code=issue["centre_code"],
                event_type="companion_data_issue_answered",
                actor_username=user.username,
                details={"issue_id": issue_id, "message": payload.message},
            )
            complete_tasks_for_reference(
                connection,
                data_issue_id=issue_id,
                actor_username=user.username,
                note="Companion data issue answered.",
            )
            updated = get_data_issue(connection, issue_id)
        return data_issue_payload(updated)

    @app.post("/api/data-issues/{issue_id}/resolve")
    def resolve_data_issue(
        issue_id: str,
        payload: OptionalIssueMessagePayload,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_central_data_manager(user)
        with database.connect() as connection:
            issue = get_data_issue(connection, issue_id)
            if issue["status"] != "answered":
                raise HTTPException(status_code=409, detail="query_transition_not_allowed")
            resolved_at = utc_now()
            connection.execute(
                """
                UPDATE data_issues
                SET status = 'resolved', resolution_message = ?, resolved_by = ?, resolved_at = ?
                WHERE id = ?
                """,
                (payload.message, user.username, resolved_at, issue_id),
            )
            audit(
                connection,
                candidate_id=issue["candidate_id"],
                centre_code=issue["centre_code"],
                event_type="companion_data_issue_resolved",
                actor_username=user.username,
                details={"issue_id": issue_id, "message": payload.message},
            )
            updated = get_data_issue(connection, issue_id)
        return data_issue_payload(updated)

    @app.post("/api/data-issues/{issue_id}/reopen")
    def reopen_data_issue(
        issue_id: str,
        payload: IssueMessagePayload,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_central_data_manager(user)
        with database.connect() as connection:
            issue = get_data_issue(connection, issue_id)
            if issue["status"] != "resolved":
                raise HTTPException(status_code=409, detail="query_transition_not_allowed")
            reopened_at = utc_now()
            connection.execute(
                """
                UPDATE data_issues
                SET status = 'open', opened_message = ?, opened_by = ?, opened_at = ?,
                    answer_message = NULL, answered_by = NULL, answered_at = NULL,
                    resolution_message = NULL, resolved_by = NULL, resolved_at = NULL,
                    reopened_by = ?, reopened_at = ?
                WHERE id = ?
                """,
                (payload.message, user.username, reopened_at, user.username, reopened_at, issue_id),
            )
            audit(
                connection,
                candidate_id=issue["candidate_id"],
                centre_code=issue["centre_code"],
                event_type="companion_data_issue_reopened",
                actor_username=user.username,
                details={"issue_id": issue_id, "message": payload.message},
            )
            create_or_reopen_task(
                connection,
                centre_code=issue["centre_code"],
                task_type="data_issue_response",
                assigned_role="site_investigator",
                title="Answer reopened companion data issue",
                dedupe_key=f"data-issue-response:{issue_id}",
                candidate_id=issue["candidate_id"],
                data_issue_id=issue_id,
            )
            updated = get_data_issue(connection, issue_id)
        return data_issue_payload(updated)

    @app.get("/api/transfer-holds/effective")
    def read_effective_transfer_holds(
        centre_code: str,
        subject_ref: str,
        event_ref: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        assert_centre_access(user, centre_code)
        with database.connect() as connection:
            holds = effective_transfer_holds(
                connection,
                centre_code=centre_code,
                subject_ref=subject_ref,
                event_ref=event_ref,
            )
        return {"effective": bool(holds), "holds": holds}

    @app.post("/api/transfer-holds", status_code=status.HTTP_201_CREATED)
    def append_transfer_hold(
        payload: TransferHoldPayload,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_central_data_manager(user)
        scope_key = transfer_hold_scope_key(
            payload.scope,
            payload.centre_code,
            payload.subject_ref,
            payload.event_ref,
        )
        hold_id = str(uuid4())
        created_at = utc_now()
        with database.connect() as connection:
            connection.execute(
                """
                INSERT INTO transfer_holds (
                    id, scope_key, scope, centre_code, subject_ref, event_ref,
                    action, reason, actor_username, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    hold_id,
                    scope_key,
                    payload.scope,
                    payload.centre_code,
                    payload.subject_ref,
                    payload.event_ref,
                    payload.action,
                    payload.reason,
                    user.username,
                    created_at,
                ),
            )
            audit(
                connection,
                candidate_id=None,
                centre_code=payload.centre_code or "CENTRAL",
                event_type=f"companion_transfer_hold_{payload.action}",
                actor_username=user.username,
                details={
                    "hold_id": hold_id,
                    "scope_key": scope_key,
                    "reason": payload.reason,
                    "authority_workflow": "formal_locks_remain_in_libreclinica",
                },
            )
            if payload.centre_code and payload.subject_ref and payload.event_ref:
                effective = bool(
                    effective_transfer_holds(
                        connection,
                        centre_code=payload.centre_code,
                        subject_ref=payload.subject_ref,
                        event_ref=payload.event_ref,
                    )
                )
            else:
                effective = payload.action == "held"
        return {
            "id": hold_id,
            "scope_key": scope_key,
            "scope": payload.scope,
            "centre_code": payload.centre_code,
            "subject_ref": payload.subject_ref,
            "event_ref": payload.event_ref,
            "action": payload.action,
            "reason": payload.reason,
            "actor_username": user.username,
            "created_at": created_at,
            "effective": effective,
            "authority_workflow": "formal_locks_remain_in_libreclinica",
        }

    @app.post(
        "/api/visits/{centre_code}/{subject_ref}/{event_ref}/attest",
        status_code=status.HTTP_201_CREATED,
    )
    def attest_visit_pre_transfer(
        centre_code: str,
        subject_ref: str,
        event_ref: str,
        payload: IssueMessagePayload,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        if user.role != "site_investigator":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="site_investigator_required")
        assert_centre_access(user, centre_code)
        with database.connect() as connection:
            candidates = connection.execute(
                f"""
                {candidate_select_sql()}
                WHERE candidates.centre_code = ? AND candidates.edc_subject_ref = ?
                  AND candidates.edc_event_ref = ?
                ORDER BY candidates.created_at, candidates.rowid
                """,
                (centre_code, subject_ref, event_ref),
            ).fetchall()
            if not candidates:
                raise HTTPException(status_code=409, detail="visit_has_no_candidates")
            if any(candidate["status"] == "candidate" for candidate in candidates):
                raise HTTPException(status_code=409, detail="visit_review_incomplete")
            confirmed = [candidate for candidate in candidates if candidate["status"] == "human_confirmed"]
            if not confirmed:
                raise HTTPException(status_code=409, detail="visit_has_no_confirmed_candidates")
            assert_no_transfer_hold(connection, confirmed[0])
            for candidate in confirmed:
                if latest_quality_assessment(connection, candidate)["status"] == "BLOCK":
                    raise HTTPException(status_code=409, detail="quality_blocked")
                issue = connection.execute(
                    """
                    SELECT 1 FROM data_issues
                    WHERE candidate_id = ? AND status IN ('open', 'answered') LIMIT 1
                    """,
                    (candidate["id"],),
                ).fetchone()
                if issue is not None:
                    raise HTTPException(status_code=409, detail="open_data_issue_blocks_transfer")
            attestation_id = str(uuid4())
            attested_at = utc_now()
            candidate_state_sha256 = visit_candidate_state_sha256(candidates)
            connection.execute(
                """
                INSERT INTO visit_attestations (
                    id, centre_code, subject_ref, event_ref, message,
                    candidate_count, candidate_state_sha256, attested_by, attested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attestation_id,
                    centre_code,
                    subject_ref,
                    event_ref,
                    payload.message,
                    len(confirmed),
                    candidate_state_sha256,
                    user.username,
                    attested_at,
                ),
            )
            audit(
                connection,
                candidate_id=None,
                centre_code=centre_code,
                event_type="visit_pre_transfer_attested",
                actor_username=user.username,
                details={
                    "attestation_id": attestation_id,
                    "subject_ref": subject_ref,
                    "event_ref": event_ref,
                    "candidate_count": len(confirmed),
                    "attestation_kind": "pre_transfer_not_electronic_signature",
                },
            )
        return {
            "id": attestation_id,
            "centre_code": centre_code,
            "subject_ref": subject_ref,
            "event_ref": event_ref,
            "message": payload.message,
            "candidate_count": len(confirmed),
            "attested_by": user.username,
            "attested_at": attested_at,
            "attestation_kind": "pre_transfer_not_electronic_signature",
            "valid": True,
            "invalidation_reason": None,
        }

    @app.get("/api/visits/{centre_code}/{subject_ref}/{event_ref}/attestations")
    def list_visit_attestations(
        centre_code: str,
        subject_ref: str,
        event_ref: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> list[dict[str, object]]:
        assert_centre_access(user, centre_code)
        with database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM visit_attestations
                WHERE centre_code = ? AND subject_ref = ? AND event_ref = ?
                ORDER BY attested_at, rowid
                """,
                (centre_code, subject_ref, event_ref),
            ).fetchall()
            candidates = connection.execute(
                f"""
                {candidate_select_sql()}
                WHERE candidates.centre_code = ? AND candidates.edc_subject_ref = ?
                  AND candidates.edc_event_ref = ?
                ORDER BY candidates.created_at, candidates.rowid
                """,
                (centre_code, subject_ref, event_ref),
            ).fetchall()
        current_state_sha256 = visit_candidate_state_sha256(candidates)
        return [
            {
                **row_to_dict(row),
                "attestation_kind": "pre_transfer_not_electronic_signature",
                "valid": bool(
                    row["candidate_state_sha256"]
                    and secrets.compare_digest(row["candidate_state_sha256"], current_state_sha256)
                ),
                "invalidation_reason": (
                    None
                    if row["candidate_state_sha256"]
                    and secrets.compare_digest(row["candidate_state_sha256"], current_state_sha256)
                    else "candidate_state_changed"
                ),
            }
            for row in rows
        ]

    def bulk_policy_source(candidate: Mapping[str, object]) -> str:
        source = candidate["extraction_agreement"]
        if source in {"agreement", "conflict", "kimi_only", "local_only", "local_fallback"}:
            return str(source)
        if source in {None, "local_pdf_text", "structured_source"}:
            return "local_only"
        return str(source)

    def assert_risky_candidate_evidence(
        connection: sqlite3.Connection,
        candidate: Mapping[str, object],
        *,
        acknowledged: bool,
        source_file_id: str | None,
    ) -> None:
        if not acknowledged or source_file_id != candidate["source_file_id"]:
            raise HTTPException(status_code=422, detail="candidate_evidence_acknowledgement_required")
        source_file = connection.execute(
            "SELECT * FROM source_files WHERE id = ?", (source_file_id,)
        ).fetchone()
        if source_file is None or not str(source_file["storage_key"]).startswith("deidentified/"):
            raise HTTPException(status_code=409, detail="candidate_deidentified_evidence_required")
        assert_source_ready_for_candidates(connection, source_file)

    @app.post("/api/candidates/{candidate_id}/review")
    def review_candidate(
        candidate_id: str,
        payload: ReviewPayload,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        if user.role not in REVIEWER_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="reviewer_role_required")
        if payload.decision == "edit" and not payload.edited_value:
            raise HTTPException(status_code=422, detail="edited_value_required")
        with database.connect() as connection:
            row = get_candidate(connection, candidate_id)
            assert_centre_access(user, row["centre_code"])
            if row["status"] != "candidate":
                raise HTTPException(status_code=409, detail="candidate_already_decided")
            assert_no_transfer_hold(connection, row)
            source_status = bulk_policy_source(row)
            selected_source: str | None = None
            final_unit = row["unit"]
            if payload.decision == "edit":
                if source_status in {"conflict", "kimi_only"} and payload.selected_source != "manual":
                    raise HTTPException(status_code=422, detail="manual_source_selection_required")
                if source_status in {"conflict", "kimi_only"}:
                    assert_risky_candidate_evidence(
                        connection,
                        row,
                        acknowledged=payload.evidence_acknowledged,
                        source_file_id=payload.evidence_source_file_id,
                    )
                selected_source = "manual"
                final_value = payload.edited_value
            elif payload.decision == "accept" and source_status == "conflict":
                if payload.selected_source not in {"local", "kimi"}:
                    raise HTTPException(status_code=422, detail="conflict_source_selection_required")
                assert_risky_candidate_evidence(
                    connection,
                    row,
                    acknowledged=payload.evidence_acknowledged,
                    source_file_id=payload.evidence_source_file_id,
                )
                selected_source = payload.selected_source
                if selected_source == "local":
                    if row["local_ocr_value"] is None:
                        raise HTTPException(status_code=409, detail="local_candidate_value_unavailable")
                    final_value = row["local_ocr_value"]
                    final_unit = row["local_ocr_unit"]
                else:
                    final_value = row["proposed_value"]
            elif payload.decision == "accept" and source_status == "kimi_only":
                if payload.selected_source != "kimi":
                    raise HTTPException(status_code=422, detail="kimi_source_selection_required")
                assert_risky_candidate_evidence(
                    connection,
                    row,
                    acknowledged=payload.evidence_acknowledged,
                    source_file_id=payload.evidence_source_file_id,
                )
                selected_source = "kimi"
                final_value = row["proposed_value"]
            elif payload.decision == "accept":
                selected_source = "local" if source_status != "agreement" else "agreement"
                final_value = row["proposed_value"]
            else:
                final_value = None
            if payload.decision != "reject":
                quality = (
                    evaluate_and_store_quality(
                        connection,
                        row,
                        value=str(final_value),
                        unit=final_unit,
                        actor_username=user.username,
                    )
                    if final_value != row["proposed_value"] or final_unit != row["unit"]
                    else latest_quality_assessment(connection, row)
                )
                if quality["status"] == "BLOCK":
                    raise HTTPException(status_code=409, detail="quality_blocked")
            reviewed_at = utc_now()
            if payload.decision == "reject":
                next_status = "rejected"
                final_value = None
                event_type = "candidate_rejected"
            else:
                next_status = "human_confirmed"
                event_type = "candidate_human_confirmed"
            connection.execute(
                """
                UPDATE candidates
                SET final_value = ?, unit = ?, status = ?, reviewed_by = ?, reviewed_at = ?, review_reason = ?
                WHERE id = ?
                """,
                (
                    final_value,
                    final_unit,
                    next_status,
                    user.username,
                    reviewed_at,
                    payload.reason,
                    candidate_id,
                ),
            )
            audit(
                connection,
                candidate_id=candidate_id,
                centre_code=row["centre_code"],
                event_type=event_type,
                actor_username=user.username,
                details={
                    "decision": payload.decision,
                    "final_value": final_value,
                    "reason": payload.reason,
                    "review_mode": "single",
                    "selected_source": selected_source,
                    "evidence_source_file_id": (
                        payload.evidence_source_file_id if payload.evidence_acknowledged else None
                    ),
                },
            )
            updated = get_candidate(connection, candidate_id)
        return candidate_payload(updated)

    @app.post("/api/candidate-reviews/bulk-accept")
    def bulk_accept_candidates(
        payload: BulkAcceptPayload,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        if user.role not in REVIEWER_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="reviewer_role_required")
        if payload.override_sources and user.role != "central_data_manager":
            raise HTTPException(status_code=403, detail="bulk_override_forbidden")
        if "conflict" in payload.override_sources and payload.conflict_value_source is None:
            raise HTTPException(status_code=422, detail="bulk_conflict_source_required")
        accepted: list[dict[str, object]] = []
        reviewed_at = utc_now()
        review_request_id = str(uuid4())
        with database.connect() as connection:
            rows = [get_candidate(connection, candidate_id) for candidate_id in payload.candidate_ids]
            for row in rows:
                assert_centre_access(user, row["centre_code"])
            policy_candidates: list[dict[str, object]] = []
            for row in rows:
                source_status = bulk_policy_source(row)
                final_value = (
                    row["local_ocr_value"]
                    if source_status == "conflict" and payload.conflict_value_source == "local"
                    else row["proposed_value"]
                )
                final_unit = (
                    row["local_ocr_unit"]
                    if source_status == "conflict" and payload.conflict_value_source == "local"
                    else row["unit"]
                )
                if final_value != row["proposed_value"] or final_unit != row["unit"]:
                    quality = assess_candidate(
                        resolved_quality_rules,
                        event_ref=str(row["edc_event_ref"]),
                        field_code=str(row["field_code"]),
                        value=str(final_value),
                        unit=final_unit,
                    )
                else:
                    quality = latest_quality_assessment(connection, row)
                policy_candidates.append(
                    {
                        "id": row["id"],
                        "source_status": source_status,
                        "quality_status": quality["status"],
                        "candidate_status": row["status"],
                        "transfer_hold": bool(
                            effective_transfer_holds(
                                connection,
                                centre_code=row["centre_code"],
                                subject_ref=row["edc_subject_ref"],
                                event_ref=row["edc_event_ref"],
                            )
                        ),
                    }
                )
            try:
                decision = evaluate_bulk_accept(
                    policy_candidates,
                    override_sources=payload.override_sources,
                    override_reason=payload.override_reason,
                    override_allowed=user.role == "central_data_manager",
                )
            except BulkAcceptPolicyError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            accepted_id_set = set(decision.accepted_ids)
            risky_accepted = {
                row["id"]
                for row in rows
                if row["id"] in accepted_id_set
                and bulk_policy_source(row) in {"conflict", "kimi_only"}
            }
            if not risky_accepted <= set(payload.evidence_acknowledged_candidate_ids):
                raise HTTPException(status_code=422, detail="bulk_evidence_acknowledgement_required")
            for row in rows:
                if row["id"] in risky_accepted:
                    assert_risky_candidate_evidence(
                        connection,
                        row,
                        acknowledged=True,
                        source_file_id=row["source_file_id"],
                    )
            summary_json = json.dumps(
                decision.summary,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            summary_sha256 = hashlib.sha256(summary_json.encode("utf-8")).hexdigest()
            for row in rows:
                if row["id"] not in accepted_id_set:
                    continue
                source_status = bulk_policy_source(row)
                selected_source = (
                    payload.conflict_value_source
                    if source_status == "conflict"
                    else "kimi"
                    if source_status == "kimi_only"
                    else "agreement"
                    if source_status == "agreement"
                    else "local"
                )
                final_value = (
                    row["local_ocr_value"]
                    if source_status == "conflict" and selected_source == "local"
                    else row["proposed_value"]
                )
                final_unit = (
                    row["local_ocr_unit"]
                    if source_status == "conflict" and selected_source == "local"
                    else row["unit"]
                )
                if final_value is None:
                    raise HTTPException(status_code=409, detail="candidate_value_unavailable")
                if final_value != row["proposed_value"] or final_unit != row["unit"]:
                    quality = evaluate_and_store_quality(
                        connection,
                        row,
                        value=str(final_value),
                        unit=final_unit,
                        actor_username=user.username,
                    )
                    if quality["status"] == "BLOCK":
                        raise HTTPException(status_code=409, detail="quality_blocked")
                connection.execute(
                    """
                    UPDATE candidates
                    SET final_value = ?, unit = ?, status = 'human_confirmed',
                        reviewed_by = ?, reviewed_at = ?, review_reason = NULL
                    WHERE id = ?
                    """,
                    (final_value, final_unit, user.username, reviewed_at, row["id"]),
                )
                audit(
                    connection,
                    candidate_id=row["id"],
                    centre_code=row["centre_code"],
                    event_type="candidate_human_confirmed",
                    actor_username=user.username,
                    details={
                        "decision": "accept",
                        "final_value": final_value,
                        "reason": payload.override_reason if decision.summary["override"]["used"] else None,
                        "mode": "bulk_accept",
                        "review_mode": "bulk",
                        "review_request_id": review_request_id,
                        "review_batch_id": payload.review_batch_id,
                        "bulk_policy_summary_sha256": summary_sha256,
                        "selected_source": selected_source,
                        "evidence_source_file_id": (
                            row["source_file_id"] if row["id"] in risky_accepted else None
                        ),
                    },
                )
                accepted.append(candidate_payload(get_candidate(connection, row["id"])))
            audit(
                connection,
                candidate_id=None,
                centre_code=rows[0]["centre_code"] if len({row["centre_code"] for row in rows}) == 1 else "CENTRAL",
                event_type="bulk_review_completed",
                actor_username=user.username,
                details={
                    "review_mode": "bulk",
                    "review_request_id": review_request_id,
                    "review_batch_id": payload.review_batch_id,
                    "summary": decision.summary,
                    "summary_sha256": summary_sha256,
                    "skipped": [item.as_dict() for item in decision.skipped],
                },
            )
        return {
            "accepted_count": len(accepted),
            "skipped_count": len(decision.skipped),
            "candidates": accepted,
            "skipped": [item.as_dict() for item in decision.skipped],
            "summary": decision.summary,
            "review_request_id": review_request_id,
            "review_batch_id": payload.review_batch_id,
        }

    @app.post("/api/candidates/{candidate_id}/transfers", status_code=status.HTTP_201_CREATED)
    def create_transfer_request(
        candidate_id: str,
        response: Response,
        user: Annotated[UserContext, Depends(current_user)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, object]:
        require_workflow_write_role(user)
        if idempotency_key is not None and IDEMPOTENCY_KEY_RE.fullmatch(idempotency_key) is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_idempotency_key")
        with database.connect() as connection:
            candidate = get_candidate(connection, candidate_id)
            assert_centre_access(user, candidate["centre_code"])
            if candidate["status"] != "human_confirmed":
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="candidate_not_human_confirmed")
            assert_no_transfer_hold(connection, candidate)
            quality = latest_quality_assessment(connection, candidate)
            if quality["status"] == "BLOCK":
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="quality_blocked")
            unresolved_issue = connection.execute(
                """
                SELECT 1 FROM data_issues
                WHERE candidate_id = ? AND status IN ('open', 'answered')
                LIMIT 1
                """,
                (candidate_id,),
            ).fetchone()
            if unresolved_issue is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="open_data_issue_blocks_transfer",
                )
            transfer_package = build_transfer_package(dict(candidate))
            package_sha256 = transfer_package_sha256(transfer_package)
            package_json = canonical_transfer_package_json(transfer_package)
            transfer_mode = resolved_edc_adapter.mode
            target_kind = resolved_edc_adapter.target_kind
            request_idempotency_key = (
                idempotency_key
                or f"candidate:{candidate_id}:{package_sha256}:{target_kind}"
            )
            existing_transfer = connection.execute(
                """
                SELECT id, candidate_id, mode, status, target_kind, package_sha256, idempotency_key,
                       created_by, created_at
                FROM transfer_requests
                WHERE centre_code = ? AND idempotency_key = ?
                """,
                (candidate["centre_code"], request_idempotency_key),
            ).fetchone()
            if existing_transfer is not None:
                if (
                    existing_transfer["candidate_id"] != candidate_id
                    or existing_transfer["package_sha256"] != package_sha256
                ):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="idempotency_key_conflict",
                    )
                audit(
                    connection,
                    candidate_id=candidate_id,
                    centre_code=candidate["centre_code"],
                    event_type="transfer_request_replayed",
                    actor_username=user.username,
                    details={
                        "idempotency_key": request_idempotency_key,
                        "transfer_id": existing_transfer["id"],
                    },
                )
                response.status_code = status.HTTP_200_OK
                return {
                    "id": existing_transfer["id"],
                    "candidate_id": existing_transfer["candidate_id"],
                    "mode": existing_transfer["mode"],
                    "status": existing_transfer["status"],
                    "target": existing_transfer["target_kind"],
                    "package_sha256": existing_transfer["package_sha256"],
                    "idempotency_key": existing_transfer["idempotency_key"],
                    "replayed": True,
                    "created_by": existing_transfer["created_by"],
                    "created_at": existing_transfer["created_at"],
                }
            transfer_id = str(uuid4())
            created_at = utc_now()
            transfer_receipt = build_transfer_receipt(
                {
                    "id": transfer_id,
                    "candidate_id": candidate_id,
                    "mode": transfer_mode,
                    "status": "queued",
                    "target_kind": target_kind,
                    "package_sha256": package_sha256,
                    "idempotency_key": request_idempotency_key,
                    "created_by": user.username,
                    "created_at": created_at,
                }
            )
            receipt_json = canonical_transfer_receipt_json(transfer_receipt)
            receipt_sha256 = transfer_receipt_sha256(transfer_receipt)
            connection.execute(
                """
                INSERT INTO transfer_requests
                    (id, candidate_id, centre_code, mode, status, target_kind, package_sha256, package_json,
                     idempotency_key, receipt_json, receipt_sha256, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transfer_id,
                    candidate_id,
                    candidate["centre_code"],
                    transfer_mode,
                    target_kind,
                    package_sha256,
                    package_json,
                    request_idempotency_key,
                    receipt_json,
                    receipt_sha256,
                    user.username,
                    created_at,
                    created_at,
                ),
            )
            audit(
                connection,
                candidate_id=candidate_id,
                centre_code=candidate["centre_code"],
                event_type=("transfer_simulated" if transfer_mode == "simulation" else "transfer_created"),
                actor_username=user.username,
                details={
                    "transfer_id": transfer_id,
                    "mode": transfer_mode,
                    "status": "queued",
                    "target": target_kind,
                    "package_sha256": package_sha256,
                },
            )
        return {
            "id": transfer_id,
            "candidate_id": candidate_id,
            "mode": transfer_mode,
            "status": "queued",
            "target": target_kind,
            "package_sha256": package_sha256,
            "idempotency_key": request_idempotency_key,
            "replayed": False,
            "created_by": user.username,
            "created_at": created_at,
        }

    @app.get("/api/transfers")
    def list_transfer_reconciliation_ledger(
        user: Annotated[UserContext, Depends(current_user)],
    ) -> list[dict[str, object]]:
        with database.connect() as connection:
            if user.role in GLOBAL_READ_ROLES:
                rows = connection.execute(
                    "SELECT * FROM transfer_requests ORDER BY created_at, id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM transfer_requests WHERE centre_code = ? ORDER BY created_at, id",
                    (user.centre_code,),
                ).fetchall()
        return [transfer_payload(row) for row in rows]

    @app.get("/api/transfers/{transfer_id}/package")
    def read_transfer_package(
        transfer_id: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        with database.connect() as connection:
            transfer = connection.execute(
                """
                SELECT id, candidate_id, centre_code, package_sha256, package_json
                FROM transfer_requests WHERE id = ?
                """,
                (transfer_id,),
            ).fetchone()
            if transfer is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
            assert_centre_access(user, transfer["centre_code"])
            if transfer["package_json"] is None or transfer["package_sha256"] is None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="transfer_package_not_available")
        return {
            "transfer_id": transfer["id"],
            "candidate_id": transfer["candidate_id"],
            "package_sha256": transfer["package_sha256"],
            "package": json.loads(transfer["package_json"]),
        }

    @app.get("/api/transfers/{transfer_id}/receipt")
    def download_transfer_receipt(
        transfer_id: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> JSONResponse:
        with database.connect() as connection:
            transfer = connection.execute(
                """
                SELECT id, centre_code, receipt_json, receipt_sha256
                FROM transfer_requests WHERE id = ?
                """,
                (transfer_id,),
            ).fetchone()
            if transfer is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
            assert_centre_access(user, transfer["centre_code"])
            if transfer["receipt_json"] is None or transfer["receipt_sha256"] is None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="transfer_receipt_not_available")
        return JSONResponse(
            content={
                "receipt_sha256": transfer["receipt_sha256"],
                "receipt": json.loads(transfer["receipt_json"]),
            },
            headers={
                "Content-Disposition": f'attachment; filename="transfer-{transfer["id"]}-receipt.json"'
            },
        )

    @app.get("/api/transfers/{transfer_id}/integrity")
    def verify_transfer_package_integrity(
        transfer_id: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        with database.connect() as connection:
            transfer = connection.execute(
                """
                SELECT id, centre_code, package_sha256, package_json
                FROM transfer_requests WHERE id = ?
                """,
                (transfer_id,),
            ).fetchone()
            if transfer is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
            assert_centre_access(user, transfer["centre_code"])
            if transfer["package_json"] is None or transfer["package_sha256"] is None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="transfer_package_not_available")
        try:
            recomputed_sha256 = transfer_package_sha256(json.loads(transfer["package_json"]))
        except (json.JSONDecodeError, TypeError):
            recomputed_sha256 = None
        return {
            "transfer_id": transfer["id"],
            "integrity_valid": recomputed_sha256 == transfer["package_sha256"],
            "recorded_sha256": transfer["package_sha256"],
            "recomputed_sha256": recomputed_sha256,
        }

    @app.post("/api/transfers/{transfer_id}/submit")
    def submit_transfer_package(
        transfer_id: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_workflow_write_role(user)
        source_for_provisioning: dict[str, object] | None = None
        with database.connect() as connection:
            transfer = connection.execute(
                """
                SELECT *
                FROM transfer_requests WHERE id = ?
                """,
                (transfer_id,),
            ).fetchone()
            if transfer is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
            assert_centre_access(user, transfer["centre_code"])
            candidate_for_hold = get_candidate(connection, transfer["candidate_id"])
            assert_no_transfer_hold(connection, candidate_for_hold)
            if candidate_for_hold["source_file_id"]:
                source_row = connection.execute(
                    "SELECT * FROM source_files WHERE id = ?",
                    (candidate_for_hold["source_file_id"],),
                ).fetchone()
                if source_row is not None and source_row["edc_provisioning_status"] == "deferred":
                    source_for_provisioning = row_to_dict(source_row)
            if transfer["status"] != "queued":
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="transfer_not_queued")
            if (
                transfer["mode"] != resolved_edc_adapter.mode
                or transfer["target_kind"] != resolved_edc_adapter.target_kind
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="transfer_adapter_mismatch",
                )
            if transfer["package_json"] is None or transfer["package_sha256"] is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="transfer_package_not_available",
                )
            try:
                frozen_package = json.loads(transfer["package_json"])
                recomputed_sha256 = transfer_package_sha256(frozen_package)
            except (json.JSONDecodeError, TypeError):
                recomputed_sha256 = None
                frozen_package = {}
            if recomputed_sha256 != transfer["package_sha256"]:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="transfer_package_integrity_failed",
                )
            submitting_at = utc_now()
            connection.execute(
                """
                UPDATE transfer_requests
                SET status = 'submitting', attempt_count = attempt_count + 1, updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (submitting_at, transfer_id),
            )

        try:
            if source_for_provisioning is not None and transfer["target_kind"] == "libreclinica":
                provision_subject = getattr(resolved_edc_adapter, "provision_subject", None)
                if not callable(provision_subject):
                    raise EdcAdapterError(
                        "libreclinica_subject_provisioning_disabled",
                        "Authority subject provisioning is unavailable; no submission occurred.",
                        retryable=False,
                    )
                provisioning = provision_subject(
                    str(source_for_provisioning["edc_subject_ref"]),
                    str(source_for_provisioning["edc_event_ref"]),
                    enrollment_date=date.today() - timedelta(days=1),
                )
                provisioned_at = utc_now()
                with database.connect() as connection:
                    connection.execute(
                        """
                        UPDATE source_files
                        SET edc_subject_ref = ?, edc_event_ref = ?, edc_subject_oid = ?,
                            edc_subject_created = ?, edc_event_scheduled = ?, edc_provisioned_at = ?,
                            edc_provisioning_status = 'completed', edc_provisioning_error_code = NULL
                        WHERE id = ?
                        """,
                        (
                            provisioning.subject_ref,
                            provisioning.event_ref,
                            provisioning.subject_oid,
                            int(provisioning.subject_created),
                            int(provisioning.event_scheduled),
                            provisioned_at,
                            source_for_provisioning["id"],
                        ),
                    )
                    audit(
                        connection,
                        candidate_id=transfer["candidate_id"],
                        centre_code=transfer["centre_code"],
                        event_type="edc_subject_provisioning_completed",
                        actor_username=user.username,
                        details={
                            "source_file_id": source_for_provisioning["id"],
                            "edc_subject_ref": provisioning.subject_ref,
                            "edc_event_ref": provisioning.event_ref,
                            "edc_subject_created": provisioning.subject_created,
                            "edc_event_scheduled": provisioning.event_scheduled,
                            "deferred_retry": True,
                        },
                    )
            submission = resolved_edc_adapter.submit(
                frozen_package,
                idempotency_key=transfer["idempotency_key"],
            )
        except EdcAdapterError as error:
            failure_at = utc_now()
            with database.connect() as connection:
                if source_for_provisioning is not None:
                    connection.execute(
                        """
                        UPDATE source_files
                        SET edc_provisioning_status = 'deferred', edc_provisioning_error_code = ?
                        WHERE id = ?
                        """,
                        (error.code, source_for_provisioning["id"]),
                    )
                connection.execute(
                    """
                    UPDATE transfer_requests
                    SET status = 'failed', last_error_code = ?, last_error_message = ?, updated_at = ?
                    WHERE id = ? AND status = 'submitting'
                    """,
                    (error.code, error.safe_message, failure_at, transfer_id),
                )
                failure_details: dict[str, object] = {
                    "transfer_id": transfer["id"],
                    "reason": error.code,
                    "target": transfer["target_kind"],
                }
                if error.code != "edc_adapter_disabled":
                    failure_details["retryable"] = error.retryable
                audit(
                    connection,
                    candidate_id=transfer["candidate_id"],
                    centre_code=transfer["centre_code"],
                    event_type=(
                        "transfer_submission_blocked"
                        if error.code == "edc_adapter_disabled"
                        else "transfer_submission_failed"
                    ),
                    actor_username=user.username,
                    details=failure_details,
                )
                if error.code != "edc_adapter_disabled":
                    create_or_reopen_task(
                        connection,
                        centre_code=transfer["centre_code"],
                        task_type="transfer_failure",
                        assigned_role="central_data_manager",
                        title="Reconcile failed Authority EDC transfer",
                        dedupe_key=f"transfer-failure:{transfer_id}",
                        candidate_id=transfer["candidate_id"],
                        transfer_id=transfer_id,
                    )
            http_status = status.HTTP_503_SERVICE_UNAVAILABLE if error.retryable else status.HTTP_409_CONFLICT
            raise HTTPException(status_code=http_status, detail=error.code) from error

        submitted_at = utc_now()
        with database.connect() as connection:
            audit(
                connection,
                candidate_id=transfer["candidate_id"],
                centre_code=transfer["centre_code"],
                event_type="transfer_submitted",
                actor_username=user.username,
                details={
                    "transfer_id": transfer["id"],
                    "target": transfer["target_kind"],
                    "external_reference": submission.external_reference,
                    "authority_response_sha256": submission.response_sha256,
                },
            )
            connection.execute(
                """
                UPDATE transfer_requests
                SET status = 'submitted', external_reference = ?, authority_response_sha256 = ?,
                    submitted_at = ?, last_error_code = NULL, last_error_message = NULL, updated_at = ?
                WHERE id = ? AND status = 'submitting'
                """,
                (
                    submission.external_reference,
                    submission.response_sha256,
                    submitted_at,
                    submitted_at,
                    transfer_id,
                ),
            )
            complete_tasks_for_reference(
                connection,
                transfer_id=transfer_id,
                actor_username=user.username,
                note="Authority EDC transfer submitted successfully.",
            )
        return run_transfer_readback(transfer_id, user.username)

    @app.post("/api/transfers/{transfer_id}/readback")
    def readback_submitted_transfer(
        transfer_id: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        if user.role not in REVIEWER_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="reviewer_role_required")
        with database.connect() as connection:
            transfer = connection.execute(
                "SELECT * FROM transfer_requests WHERE id = ?",
                (transfer_id,),
            ).fetchone()
            if transfer is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
            assert_centre_access(user, transfer["centre_code"])
        return run_transfer_readback(transfer_id, user.username)

    @app.post("/api/transfers/{transfer_id}/retry")
    def retry_failed_transfer(
        transfer_id: str,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        require_workflow_write_role(user)
        with database.connect() as connection:
            transfer = connection.execute(
                "SELECT * FROM transfer_requests WHERE id = ?",
                (transfer_id,),
            ).fetchone()
            if transfer is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
            assert_centre_access(user, transfer["centre_code"])
            if transfer["status"] != "failed":
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="transfer_not_failed")
            retry_count = transfer["retry_count"] + 1
            retried_at = utc_now()
            connection.execute(
                """
                UPDATE transfer_requests
                SET status = 'queued', retry_count = ?, updated_at = ?
                WHERE id = ?
                """,
                (retry_count, retried_at, transfer_id),
            )
            audit(
                connection,
                candidate_id=transfer["candidate_id"],
                centre_code=transfer["centre_code"],
                event_type="transfer_retry_queued",
                actor_username=user.username,
                details={"retry_count": retry_count, "transfer_id": transfer_id},
            )
            updated = connection.execute(
                "SELECT * FROM transfer_requests WHERE id = ?",
                (transfer_id,),
            ).fetchone()
        return transfer_payload(updated)

    @app.post("/api/transfers/{transfer_id}/reconcile")
    def reconcile_failed_transfer(
        transfer_id: str,
        payload: TransferReconciliationPayload,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, object]:
        if user.role not in REVIEWER_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="reviewer_role_required")
        with database.connect() as connection:
            transfer = connection.execute(
                "SELECT * FROM transfer_requests WHERE id = ?",
                (transfer_id,),
            ).fetchone()
            if transfer is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
            assert_centre_access(user, transfer["centre_code"])
            if transfer["status"] != "failed":
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="transfer_not_failed")
            reconciled_at = utc_now()
            connection.execute(
                """
                UPDATE transfer_requests
                SET status = 'reconciled', reconciled_by = ?, reconciled_at = ?,
                    reconciliation_note = ?, updated_at = ?
                WHERE id = ?
                """,
                (user.username, reconciled_at, payload.note, reconciled_at, transfer_id),
            )
            audit(
                connection,
                candidate_id=transfer["candidate_id"],
                centre_code=transfer["centre_code"],
                event_type="transfer_reconciled",
                actor_username=user.username,
                details={"note": payload.note, "transfer_id": transfer_id},
            )
            updated = connection.execute(
                "SELECT * FROM transfer_requests WHERE id = ?",
                (transfer_id,),
            ).fetchone()
        return transfer_payload(updated)

    @app.get("/api/candidates/{candidate_id}/audit")
    def candidate_audit(candidate_id: str, user: Annotated[UserContext, Depends(current_user)]) -> list[dict[str, object]]:
        with database.connect() as connection:
            candidate = get_candidate(connection, candidate_id)
            assert_centre_access(user, candidate["centre_code"])
            rows = connection.execute(
                """
                SELECT event_type, actor_username, created_at, details_json, prev_hash, event_hash
                FROM audit_events WHERE candidate_id = ? ORDER BY created_at, rowid
                """,
                (candidate_id,),
            ).fetchall()
        return [
            {
                "event_type": row["event_type"],
                "actor_username": row["actor_username"],
                "created_at": row["created_at"],
                "details": json.loads(row["details_json"]),
                "prev_hash": row["prev_hash"],
                "event_hash": row["event_hash"],
            }
            for row in rows
        ]

    @app.get("/api/audit-events")
    def search_audit_events(
        user: Annotated[UserContext, Depends(current_user)],
        event_type: Annotated[str | None, Query(max_length=100)] = None,
        actor: Annotated[str | None, Query(max_length=200)] = None,
        review_mode: Annotated[Literal["single", "bulk"] | None, Query()] = None,
        review_batch_id: Annotated[str | None, Query(max_length=100)] = None,
        from_time: Annotated[str | None, Query(alias="from", max_length=50)] = None,
        to_time: Annotated[str | None, Query(alias="to", max_length=50)] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, object]:
        clauses: list[str] = []
        parameters: list[object] = []
        if user.role not in GLOBAL_READ_ROLES:
            clauses.append("centre_code = ?")
            parameters.append(user.centre_code)
        if event_type:
            clauses.append("event_type = ?")
            parameters.append(event_type)
        if actor:
            clauses.append("actor_username = ?")
            parameters.append(actor)
        if review_mode:
            clauses.append("json_extract(details_json, '$.review_mode') = ?")
            parameters.append(review_mode)
        if review_batch_id:
            clauses.append("json_extract(details_json, '$.review_batch_id') = ?")
            parameters.append(review_batch_id)
        if from_time:
            clauses.append("created_at >= ?")
            parameters.append(from_time)
        if to_time:
            clauses.append("created_at <= ?")
            parameters.append(to_time)
        where_clause = " WHERE " + " AND ".join(clauses) if clauses else ""
        with database.connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) AS total FROM audit_events{where_clause}",
                tuple(parameters),
            ).fetchone()["total"]
            rows = connection.execute(
                f"""
                SELECT id, candidate_id, centre_code, event_type, actor_username,
                       created_at, details_json, prev_hash, event_hash
                FROM audit_events{where_clause}
                ORDER BY created_at, rowid
                LIMIT ? OFFSET ?
                """,
                (*parameters, limit, offset),
            ).fetchall()
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "events": [
                {
                    "id": row["id"],
                    "candidate_id": row["candidate_id"],
                    "centre_code": row["centre_code"],
                    "event_type": row["event_type"],
                    "actor_username": row["actor_username"],
                    "created_at": row["created_at"],
                    "details": json.loads(row["details_json"]),
                    "prev_hash": row["prev_hash"],
                    "event_hash": row["event_hash"],
                }
                for row in rows
            ],
        }

    return app


app = create_app()
