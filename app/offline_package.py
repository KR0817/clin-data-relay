"""Integrity-checked reviewed-data packages for centres without EDC access.

The package is deliberately small and engine-independent. It contains only
pseudonymous, human-confirmed values and provenance hashes; it is not an EDC
export and it does not contain images, OCR evidence or direct identifiers.
"""

from __future__ import annotations

import hashlib
import json
import base64
import os
import re
from typing import Any, Mapping, Sequence
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


PACKAGE_TYPE = "clinical-edc-reviewed-package"
PACKAGE_VERSION = 1
ENCRYPTED_PACKAGE_TYPE = "clinical-edc-reviewed-package-encrypted"
ENCRYPTED_PACKAGE_VERSION = 1
MAX_PACKAGE_BYTES = 5 * 1024 * 1024
MIN_PASSPHRASE_LENGTH = 12
SCRYPT_N = 2**17
SCRYPT_R = 8
SCRYPT_P = 1
_SUPPORTED_SCRYPT_PARAMETERS = {(2**15, 8, 1), (SCRYPT_N, SCRYPT_R, SCRYPT_P)}
_FIELD_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SUBJECT_RE = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_EVENT_RE = re.compile(r"^[A-Z][A-Z0-9_-]{1,63}$")
_DIRECT_IDENTIFIER_MARKERS = ("patient", "name", "phone", "hospital", "身份证", "姓名", "电话")
_PHONE_RE = re.compile(r"\b1[3-9]\d{9}\b")
_NATIONAL_ID_RE = re.compile(r"\b\d{17}[0-9Xx]\b")


class OfflinePackageError(ValueError):
    """Raised when a reviewed package is malformed or fails its hash."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _validate_passphrase(passphrase: str) -> None:
    if not isinstance(passphrase, str) or not (MIN_PASSPHRASE_LENGTH <= len(passphrase) <= 256):
        raise OfflinePackageError("offline_package_passphrase_invalid")


def _canonical(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _content_hash(package_without_hash: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(package_without_hash)).hexdigest()


def _actor_pseudonym(username: str) -> str:
    return hashlib.sha256(("clinical-edc-package-actor:" + username).encode("utf-8")).hexdigest()[:20]


def _normalized_audit_anchor(anchor: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"version", "head_hash", "event_count", "generated_at"}
    if set(anchor) != allowed:
        raise OfflinePackageError("offline_package_audit_anchor_invalid")
    head_hash = anchor.get("head_hash")
    event_count = anchor.get("event_count")
    if anchor.get("version") != "audit-chain-v1":
        raise OfflinePackageError("offline_package_audit_anchor_invalid")
    if not isinstance(head_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", head_hash):
        raise OfflinePackageError("offline_package_audit_anchor_invalid")
    if not isinstance(event_count, int) or isinstance(event_count, bool) or event_count < 0:
        raise OfflinePackageError("offline_package_audit_anchor_invalid")
    generated_at = anchor.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at or len(generated_at) > 100:
        raise OfflinePackageError("offline_package_audit_anchor_invalid")
    return {
        "version": "audit-chain-v1",
        "head_hash": head_hash,
        "event_count": event_count,
        "generated_at": generated_at,
    }


def _assert_no_direct_identifier(value: str) -> None:
    lowered = value.casefold()
    if any(marker in lowered for marker in _DIRECT_IDENTIFIER_MARKERS):
        raise OfflinePackageError("offline_package_direct_identifier_detected")
    if _PHONE_RE.search(value) or _NATIONAL_ID_RE.search(value):
        raise OfflinePackageError("offline_package_direct_identifier_detected")


def build_reviewed_package(
    *,
    centre_code: str,
    dictionary_id: str,
    dictionary_version: str,
    created_by: str,
    created_at: str,
    records: Sequence[Mapping[str, Any]],
    audit_anchor: Mapping[str, Any] | None = None,
) -> tuple[bytes, str, str]:
    """Build canonical JSON bytes and return ``(bytes, package_id, sha256)``."""

    records_by_key: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for record in records:
        normalized = {
            "centre_code": str(record["centre_code"]),
            "edc_subject_ref": str(record["edc_subject_ref"]),
            "edc_event_ref": str(record["edc_event_ref"]),
            "field_code": str(record["field_code"]),
            "final_value": str(record["final_value"]),
            "unit": record.get("unit"),
            "source_sha256": str(record["source_sha256"]),
            "reviewed_at": str(record["reviewed_at"]),
        }
        _assert_no_direct_identifier(normalized["final_value"])
        key = (
            normalized["centre_code"],
            normalized["edc_subject_ref"],
            normalized["edc_event_ref"],
            normalized["field_code"],
            normalized["source_sha256"],
        )
        existing = records_by_key.get(key)
        if existing is None:
            records_by_key[key] = normalized
            continue
        if (existing["final_value"], existing.get("unit")) != (
            normalized["final_value"],
            normalized.get("unit"),
        ):
            raise OfflinePackageError("offline_package_conflicting_record")
        if normalized["reviewed_at"] > existing["reviewed_at"]:
            records_by_key[key] = normalized

    normalized_records = list(records_by_key.values())
    normalized_records.sort(
        key=lambda item: (
            item["centre_code"],
            item["edc_subject_ref"],
            item["edc_event_ref"],
            item["field_code"],
            item["source_sha256"],
        )
    )
    package_id = str(uuid4())
    body: dict[str, Any] = {
        "package_type": PACKAGE_TYPE,
        "package_version": PACKAGE_VERSION,
        "package_id": package_id,
        "centre_code": centre_code,
        "dictionary_id": dictionary_id,
        "dictionary_version": dictionary_version,
        "created_by_pseudonym": _actor_pseudonym(created_by),
        "created_at": created_at,
        "record_count": len(normalized_records),
        "records": normalized_records,
    }
    if audit_anchor is not None:
        body["audit_anchor"] = _normalized_audit_anchor(audit_anchor)
    digest = _content_hash(body)
    body["content_sha256"] = digest
    return _canonical(body), package_id, digest


def parse_reviewed_package(content: bytes) -> dict[str, Any]:
    if len(content) > MAX_PACKAGE_BYTES:
        raise OfflinePackageError("offline_package_too_large")
    try:
        document = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OfflinePackageError("offline_package_invalid_json") from error
    if not isinstance(document, dict):
        raise OfflinePackageError("offline_package_invalid_schema")
    content_sha256 = document.pop("content_sha256", None)
    if not isinstance(content_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", content_sha256):
        raise OfflinePackageError("offline_package_hash_required")
    if _content_hash(document) != content_sha256:
        raise OfflinePackageError("offline_package_hash_mismatch")
    allowed_top_level = {
        "package_type",
        "package_version",
        "package_id",
        "centre_code",
        "dictionary_id",
        "dictionary_version",
        "created_by_pseudonym",
        "created_at",
        "record_count",
        "records",
        "audit_anchor",
    }
    if set(document) - allowed_top_level:
        raise OfflinePackageError("offline_package_invalid_schema")
    if document.get("package_type") != PACKAGE_TYPE or document.get("package_version") != PACKAGE_VERSION:
        raise OfflinePackageError("offline_package_version_unsupported")
    centre_code = document.get("centre_code")
    if not isinstance(centre_code, str) or not re.fullmatch(r"^[A-Z][A-Z0-9_-]{1,31}$", centre_code):
        raise OfflinePackageError("offline_package_centre_invalid")
    records = document.get("records")
    if not isinstance(records, list) or len(records) != document.get("record_count"):
        raise OfflinePackageError("offline_package_record_count_invalid")
    seen: set[tuple[str, str, str, str]] = set()
    for record in records:
        if not isinstance(record, dict):
            raise OfflinePackageError("offline_package_record_invalid")
        allowed_record_keys = {
            "centre_code",
            "edc_subject_ref",
            "edc_event_ref",
            "field_code",
            "final_value",
            "unit",
            "source_sha256",
            "reviewed_at",
        }
        if set(record) - allowed_record_keys:
            raise OfflinePackageError("offline_package_record_invalid")
        required = ("centre_code", "edc_subject_ref", "edc_event_ref", "field_code", "final_value", "source_sha256", "reviewed_at")
        if any(key not in record for key in required):
            raise OfflinePackageError("offline_package_record_required")
        if record["centre_code"] != centre_code:
            raise OfflinePackageError("offline_package_mixed_centres")
        if not isinstance(record["edc_subject_ref"], str) or not _SUBJECT_RE.fullmatch(record["edc_subject_ref"]):
            raise OfflinePackageError("offline_package_subject_invalid")
        if not isinstance(record["edc_event_ref"], str) or not _EVENT_RE.fullmatch(record["edc_event_ref"]):
            raise OfflinePackageError("offline_package_event_invalid")
        if not isinstance(record["field_code"], str) or not _FIELD_CODE_RE.fullmatch(record["field_code"]):
            raise OfflinePackageError("offline_package_field_invalid")
        if not isinstance(record["final_value"], str) or not record["final_value"].strip() or len(record["final_value"]) > 200:
            raise OfflinePackageError("offline_package_value_invalid")
        _assert_no_direct_identifier(record["final_value"])
        if record.get("unit") is not None and (not isinstance(record["unit"], str) or len(record["unit"]) > 50):
            raise OfflinePackageError("offline_package_unit_invalid")
        if not isinstance(record["source_sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", record["source_sha256"]):
            raise OfflinePackageError("offline_package_source_hash_invalid")
        key = (record["edc_subject_ref"], record["edc_event_ref"], record["field_code"], record["source_sha256"])
        if key in seen:
            raise OfflinePackageError("offline_package_duplicate_record")
        seen.add(key)
    if "audit_anchor" in document:
        if not isinstance(document["audit_anchor"], Mapping):
            raise OfflinePackageError("offline_package_audit_anchor_invalid")
        document["audit_anchor"] = _normalized_audit_anchor(document["audit_anchor"])
    document["content_sha256"] = content_sha256
    return document


def build_encrypted_reviewed_package(
    *,
    passphrase: str,
    centre_code: str,
    dictionary_id: str,
    dictionary_version: str,
    created_by: str,
    created_at: str,
    records: Sequence[Mapping[str, Any]],
    audit_anchor: Mapping[str, Any] | None = None,
) -> tuple[bytes, str, str]:
    """Encrypt a canonical reviewed package and return bytes, id and transport hash."""

    _validate_passphrase(passphrase)
    plaintext, package_id, _inner_hash = build_reviewed_package(
        centre_code=centre_code,
        dictionary_id=dictionary_id,
        dictionary_version=dictionary_version,
        created_by=created_by,
        created_at=created_at,
        records=records,
        audit_anchor=audit_anchor,
    )
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = Scrypt(
        salt=salt,
        length=32,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
    ).derive(passphrase.encode("utf-8"))
    metadata = {
        "package_type": ENCRYPTED_PACKAGE_TYPE,
        "package_version": ENCRYPTED_PACKAGE_VERSION,
        "package_id": package_id,
        "centre_code": centre_code,
        "dictionary_id": dictionary_id,
        "dictionary_version": dictionary_version,
        "encryption": {
            "algorithm": "AES-256-GCM",
            "kdf": "scrypt",
            "salt_b64": base64.b64encode(salt).decode("ascii"),
            "nonce_b64": base64.b64encode(nonce).decode("ascii"),
            "n": SCRYPT_N,
            "r": SCRYPT_R,
            "p": SCRYPT_P,
        },
    }
    if audit_anchor is not None:
        metadata["audit_anchor"] = _normalized_audit_anchor(audit_anchor)
    aad = _canonical(metadata)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
    envelope: dict[str, Any] = {
        **metadata,
        "ciphertext_b64": base64.b64encode(ciphertext).decode("ascii"),
    }
    package_sha256 = hashlib.sha256(_canonical(envelope)).hexdigest()
    envelope["package_sha256"] = package_sha256
    return _canonical(envelope), package_id, package_sha256


def parse_encrypted_reviewed_package(content: bytes, *, passphrase: str) -> tuple[dict[str, Any], str]:
    """Decrypt and validate an encrypted package, returning inner document and transport hash."""

    _validate_passphrase(passphrase)
    if len(content) > MAX_PACKAGE_BYTES:
        raise OfflinePackageError("offline_package_too_large")
    try:
        envelope = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OfflinePackageError("offline_package_invalid_json") from error
    if not isinstance(envelope, dict):
        raise OfflinePackageError("offline_package_invalid_schema")
    package_sha256 = envelope.pop("package_sha256", None)
    if not isinstance(package_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", package_sha256):
        raise OfflinePackageError("offline_package_hash_required")
    if hashlib.sha256(_canonical(envelope)).hexdigest() != package_sha256:
        raise OfflinePackageError("offline_package_hash_mismatch")
    if envelope.get("package_type") != ENCRYPTED_PACKAGE_TYPE or envelope.get("package_version") != ENCRYPTED_PACKAGE_VERSION:
        raise OfflinePackageError("offline_package_version_unsupported")
    encryption = envelope.get("encryption")
    ciphertext_b64 = envelope.get("ciphertext_b64")
    if not isinstance(encryption, dict) or not isinstance(ciphertext_b64, str):
        raise OfflinePackageError("offline_package_invalid_schema")
    if encryption.get("algorithm") != "AES-256-GCM" or encryption.get("kdf") != "scrypt":
        raise OfflinePackageError("offline_package_encryption_unsupported")
    try:
        salt = base64.b64decode(str(encryption["salt_b64"]), validate=True)
        nonce = base64.b64decode(str(encryption["nonce_b64"]), validate=True)
        ciphertext = base64.b64decode(ciphertext_b64, validate=True)
        if len(salt) != 16 or len(nonce) != 12:
            raise ValueError
        parameters = (
            int(encryption["n"]),
            int(encryption["r"]),
            int(encryption["p"]),
        )
        if parameters not in _SUPPORTED_SCRYPT_PARAMETERS:
            raise ValueError
        key = Scrypt(
            salt=salt,
            length=32,
            n=parameters[0],
            r=parameters[1],
            p=parameters[2],
        ).derive(passphrase.encode("utf-8"))
        aad_keys = [
            "package_type", "package_version", "package_id", "centre_code",
            "dictionary_id", "dictionary_version", "encryption",
        ]
        if "audit_anchor" in envelope:
            if not isinstance(envelope["audit_anchor"], Mapping):
                raise ValueError
            envelope["audit_anchor"] = _normalized_audit_anchor(envelope["audit_anchor"])
            aad_keys.append("audit_anchor")
        aad_metadata = {key: envelope[key] for key in aad_keys}
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, _canonical(aad_metadata))
    except (KeyError, ValueError, InvalidTag) as error:
        raise OfflinePackageError("offline_package_decryption_failed") from error
    inner = parse_reviewed_package(plaintext)
    if inner.get("package_id") != envelope.get("package_id") or inner.get("centre_code") != envelope.get("centre_code"):
        raise OfflinePackageError("offline_package_metadata_mismatch")
    if inner.get("audit_anchor") != envelope.get("audit_anchor"):
        raise OfflinePackageError("offline_package_metadata_mismatch")
    return inner, package_sha256
