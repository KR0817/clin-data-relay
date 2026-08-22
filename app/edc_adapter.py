"""Authority-EDC transfer boundary and LibreClinica SOAP/ODM adapter.

The companion freezes a reviewed transfer package before this module is called.
LibreClinica remains the authoritative clinical record.  The adapter never writes
LibreClinica's database directly. Subject/event provisioning is a separate,
explicitly enabled SOAP boundary and is never hidden inside clinical-value submit.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


TRANSFER_PROTOCOL = "clinical-edc-companion-transfer-v1"
RECEIPT_PROTOCOL = "clinical-edc-companion-receipt-v1"
SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"
WSSE_NS = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
PASSWORD_TEXT_TYPE = (
    "http://docs.oasis-open.org/wss/2004/01/"
    "oasis-200401-wss-username-token-profile-1.0#PasswordText"
)
STUDY_SUBJECT_NS = "http://openclinica.org/ws/studySubject/v1"
EVENT_NS = "http://openclinica.org/ws/event/v1"
DATA_NS = "http://openclinica.org/ws/data/v1"
BEANS_NS = "http://openclinica.org/ws/beans"
SHA1_RE = re.compile(r"^[a-f0-9]{40}$")
SUBJECT_REF_RE = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")

ET.register_namespace("soapenv", SOAP_ENV_NS)
ET.register_namespace("wsse", WSSE_NS)
ET.register_namespace("studySubject", STUDY_SUBJECT_NS)
ET.register_namespace("event", EVENT_NS)
ET.register_namespace("beans", BEANS_NS)
ET.register_namespace("data", DATA_NS)


def build_transfer_package(candidate: Mapping[str, Any]) -> dict[str, object]:
    """Return the canonical, review-bound package for one transfer."""

    return {
        "protocol": TRANSFER_PROTOCOL,
        "candidate": {
            "id": candidate["id"],
            "centre_code": candidate["centre_code"],
            "source_sha256": candidate["source_sha256"],
        },
        "edc_record": {
            "subject_ref": candidate["edc_subject_ref"],
            "event_ref": candidate["edc_event_ref"],
            "field_code": candidate["field_code"],
        },
        "value": {"final_value": candidate["final_value"], "unit": candidate["unit"]},
        "review": {"reviewed_by": candidate["reviewed_by"], "reviewed_at": candidate["reviewed_at"]},
    }


def transfer_package_sha256(transfer_package: Mapping[str, object]) -> str:
    encoded = canonical_transfer_package_json(transfer_package).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_transfer_package_json(transfer_package: Mapping[str, object]) -> str:
    """Serialize a package deterministically for persistence and integrity checks."""

    return json.dumps(transfer_package, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def build_transfer_receipt(transfer: Mapping[str, Any]) -> dict[str, object]:
    """Return the immutable receipt for the original transfer request."""

    return {
        "protocol": RECEIPT_PROTOCOL,
        "transfer": {
            "id": transfer["id"],
            "candidate_id": transfer["candidate_id"],
            "mode": transfer["mode"],
            "status": transfer["status"],
            "target": transfer["target_kind"],
            "package_sha256": transfer["package_sha256"],
        },
        "request": {
            "idempotency_key": transfer["idempotency_key"],
            "created_by": transfer["created_by"],
            "created_at": transfer["created_at"],
        },
    }


def canonical_transfer_receipt_json(transfer_receipt: Mapping[str, object]) -> str:
    """Serialize a receipt deterministically for persistence and verification."""

    return json.dumps(transfer_receipt, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def transfer_receipt_sha256(transfer_receipt: Mapping[str, object]) -> str:
    encoded = canonical_transfer_receipt_json(transfer_receipt).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class EdcSubmissionResult:
    external_reference: str
    response_sha256: str
    authority_status: str = "Success"


@dataclass(frozen=True)
class EdcReadbackResult:
    status: str
    observed_value: str | None = None
    response_sha256: str | None = None


@dataclass(frozen=True)
class EdcProvisioningResult:
    subject_ref: str
    subject_oid: str
    event_ref: str
    subject_created: bool
    event_scheduled: bool

    @property
    def external_reference(self) -> str:
        return f"{self.subject_oid}/{self.event_ref}"


class EdcAdapterError(RuntimeError):
    """Sanitized adapter error suitable for the reconciliation ledger."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.retryable = retryable


class AuthorityEdcAdapter(Protocol):
    mode: str
    target_kind: str

    def readiness(self) -> dict[str, object]: ...

    def provision_subject(
        self,
        subject_ref: str,
        event_ref: str,
        *,
        enrollment_date: date,
    ) -> EdcProvisioningResult: ...

    def submit(
        self,
        transfer_package: Mapping[str, object],
        *,
        idempotency_key: str,
    ) -> EdcSubmissionResult: ...

    def read_value(self, transfer_package: Mapping[str, object]) -> EdcReadbackResult: ...


class DisabledEdcAdapter:
    mode = "simulation"
    target_kind = "not_configured"

    def readiness(self) -> dict[str, object]:
        return {
            "authority_edc": "LibreClinica",
            "mode": "simulation_only",
            "write_path": "disabled",
            "status": "blocked",
            "blockers": [
                "no validated LibreClinica target is configured",
                "direct database write is prohibited",
                "a validated ODM or Web Service adapter is required before any Authority EDC submission",
            ],
            "transfer_protocol": TRANSFER_PROTOCOL,
        }

    def submit(
        self,
        transfer_package: Mapping[str, object],
        *,
        idempotency_key: str,
    ) -> EdcSubmissionResult:
        del transfer_package, idempotency_key
        raise EdcAdapterError(
            "edc_adapter_disabled",
            "Authority EDC adapter is disabled; no submission occurred.",
        )

    def provision_subject(
        self,
        subject_ref: str,
        event_ref: str,
        *,
        enrollment_date: date,
    ) -> EdcProvisioningResult:
        del subject_ref, event_ref, enrollment_date
        raise EdcAdapterError(
            "edc_adapter_disabled",
            "Authority EDC adapter is disabled; no subject was created.",
        )

    def read_value(self, transfer_package: Mapping[str, object]) -> EdcReadbackResult:
        del transfer_package
        return EdcReadbackResult(status="unsupported")


class BlockedEdcAdapter(DisabledEdcAdapter):
    mode = "libreclinica_soap"
    target_kind = "libreclinica"

    def __init__(self, blocker: str) -> None:
        self.blocker = blocker

    def readiness(self) -> dict[str, object]:
        return {
            "authority_edc": "LibreClinica",
            "mode": self.mode,
            "write_path": "disabled",
            "status": "blocked",
            "blockers": [self.blocker, "direct database write is prohibited"],
            "transfer_protocol": TRANSFER_PROTOCOL,
        }

    def submit(
        self,
        transfer_package: Mapping[str, object],
        *,
        idempotency_key: str,
    ) -> EdcSubmissionResult:
        del transfer_package, idempotency_key
        raise EdcAdapterError("edc_adapter_not_ready", self.blocker)


@dataclass(frozen=True)
class LibreClinicaFieldMapping:
    form_oid: str
    item_group_oid: str
    item_oid: str


@dataclass(frozen=True)
class LibreClinicaEventMapping:
    event_oid: str
    repeat_key: str


@dataclass(frozen=True)
class LibreClinicaOdmMapping:
    mapping_id: str
    mapping_version: str
    study_identifier: str
    study_oid: str
    events: Mapping[str, LibreClinicaEventMapping]
    fields_by_event: Mapping[str, Mapping[str, LibreClinicaFieldMapping]]

    @classmethod
    def from_file(cls, path: Path) -> "LibreClinicaOdmMapping":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            events = {
                str(code): LibreClinicaEventMapping(
                    event_oid=str(item["event_oid"]),
                    repeat_key=str(item.get("repeat_key", "1")),
                )
                for code, item in payload["events"].items()
            }
            raw_event_fields = payload.get("field_mappings")
            if raw_event_fields is None:
                legacy_fields = {
                    str(code): LibreClinicaFieldMapping(
                        form_oid=str(item["form_oid"]),
                        item_group_oid=str(item["item_group_oid"]),
                        item_oid=str(item["item_oid"]),
                    )
                    for code, item in payload["fields"].items()
                }
                fields_by_event = {event_ref: legacy_fields for event_ref in events}
            else:
                fields_by_event = {
                    str(event_ref): {
                        str(code): LibreClinicaFieldMapping(
                            form_oid=str(item["form_oid"]),
                            item_group_oid=str(item["item_group_oid"]),
                            item_oid=str(item["item_oid"]),
                        )
                        for code, item in event_fields.items()
                    }
                    for event_ref, event_fields in raw_event_fields.items()
                }
            mapping = cls(
                mapping_id=str(payload["mapping_id"]),
                mapping_version=str(payload["mapping_version"]),
                study_identifier=str(payload["study_identifier"]),
                study_oid=str(payload["study_oid"]),
                events=events,
                fields_by_event=fields_by_event,
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise EdcAdapterError(
                "libreclinica_mapping_invalid",
                "LibreClinica ODM mapping is missing or invalid.",
            ) from error
        if (
            not mapping.events
            or set(mapping.events) != set(mapping.fields_by_event)
            or any(not fields for fields in mapping.fields_by_event.values())
        ):
            raise EdcAdapterError(
                "libreclinica_mapping_invalid",
                "LibreClinica ODM mapping must contain a non-empty field map for every event.",
            )
        return mapping


SoapTransport = Callable[[str, bytes, float], bytes]


class LibreClinicaSoapAdapter:
    mode = "libreclinica_soap"
    target_kind = "libreclinica"

    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password_sha1: str,
        odm_mapping: LibreClinicaOdmMapping,
        timeout_seconds: float = 15.0,
        allow_remote: bool = False,
        allow_subject_provisioning: bool = False,
        transport: SoapTransport | None = None,
    ) -> None:
        normalized_url = base_url.rstrip("/")
        parsed = urlparse(normalized_url)
        local_hosts = {"127.0.0.1", "localhost", "::1"}
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise EdcAdapterError("libreclinica_url_invalid", "LibreClinica base URL is invalid.")
        if parsed.hostname not in local_hosts and not allow_remote:
            raise EdcAdapterError(
                "libreclinica_remote_target_blocked",
                "Remote LibreClinica targets require explicit approval and configuration.",
            )
        if parsed.hostname not in local_hosts and parsed.scheme != "https":
            raise EdcAdapterError(
                "libreclinica_https_required",
                "Remote LibreClinica targets must use HTTPS.",
            )
        if not username or not SHA1_RE.fullmatch(password_sha1):
            raise EdcAdapterError(
                "libreclinica_credentials_invalid",
                "LibreClinica SOAP credentials are missing or invalid.",
            )
        self.base_url = normalized_url
        self.username = username
        self._password_sha1 = password_sha1
        self.odm_mapping = odm_mapping
        self.timeout_seconds = timeout_seconds
        self.allow_subject_provisioning = allow_subject_provisioning
        self._transport = transport or self._http_transport

    @classmethod
    def from_environment(cls) -> AuthorityEdcAdapter:
        mode = os.getenv("COMPANION_EDC_MODE", "simulation_only").strip().lower()
        if mode not in {"libreclinica", "libreclinica_soap"}:
            return DisabledEdcAdapter()
        try:
            credentials_path = Path(
                os.getenv(
                    "LIBRECLINICA_SOAP_CREDENTIALS_FILE",
                    ".runtime/libreclinica-soap-credentials.json",
                )
            )
            credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
            mapping_path = Path(
                os.getenv(
                    "LIBRECLINICA_ODM_MAPPING_FILE",
                    "config/libreclinica-sandbox-odm-map.json",
                )
            )
            return cls(
                base_url=os.getenv("LIBRECLINICA_BASE_URL", "http://127.0.0.1:8081"),
                username=str(credentials["username"]),
                password_sha1=str(credentials["password_sha1"]),
                odm_mapping=LibreClinicaOdmMapping.from_file(mapping_path),
                timeout_seconds=float(os.getenv("LIBRECLINICA_TIMEOUT_SECONDS", "15")),
                allow_remote=os.getenv("LIBRECLINICA_ALLOW_REMOTE", "false").lower() == "true",
                allow_subject_provisioning=(
                    os.getenv("LIBRECLINICA_ALLOW_SUBJECT_PROVISIONING", "false").lower() == "true"
                ),
            )
        except EdcAdapterError as error:
            return BlockedEdcAdapter(error.safe_message)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return BlockedEdcAdapter("LibreClinica SOAP credential configuration is missing or invalid.")

    @property
    def ws_base_url(self) -> str:
        return f"{self.base_url}/LibreClinica-ws/ws"

    @property
    def wsdl_url(self) -> str:
        return f"{self.ws_base_url}/dataWsdl.wsdl"

    def readiness(self) -> dict[str, object]:
        try:
            response = self._post_soap(
                "studySubject/v1",
                STUDY_SUBJECT_NS,
                "listAllByStudyRequest",
                self._list_subjects_request(),
            )
            self._require_success(response, "libreclinica_auth_probe_failed")
        except EdcAdapterError as error:
            return {
                "authority_edc": "LibreClinica",
                "mode": self.mode,
                "write_path": "disabled",
                "status": "blocked",
                "endpoint": self.base_url,
                "mapping_id": self.odm_mapping.mapping_id,
                "mapping_version": self.odm_mapping.mapping_version,
                "blockers": [error.safe_message],
                "transfer_protocol": TRANSFER_PROTOCOL,
            }
        return {
            "authority_edc": "LibreClinica",
            "mode": self.mode,
            "write_path": "human_triggered",
            "status": "ready",
            "endpoint": self.base_url,
            "study_identifier": self.odm_mapping.study_identifier,
            "study_oid": self.odm_mapping.study_oid,
            "mapping_id": self.odm_mapping.mapping_id,
            "mapping_version": self.odm_mapping.mapping_version,
            "automatic_subject_provisioning": "enabled" if self.allow_subject_provisioning else "disabled",
            "blockers": [],
            "transfer_protocol": TRANSFER_PROTOCOL,
        }

    def submit(
        self,
        transfer_package: Mapping[str, object],
        *,
        idempotency_key: str,
    ) -> EdcSubmissionResult:
        del idempotency_key  # LibreClinica 1.4 SOAP has no idempotency-key header.
        record = self._package_section(transfer_package, "edc_record")
        value = self._package_section(transfer_package, "value")
        subject_ref = self._required_text(record, "subject_ref")
        event_ref = self._required_text(record, "event_ref")
        field_code = self._required_text(record, "field_code")
        final_value = self._required_text(value, "final_value")
        event_mapping = self.odm_mapping.events.get(event_ref)
        if event_mapping is None:
            raise EdcAdapterError(
                "libreclinica_event_not_mapped",
                f"Event reference {event_ref} is not in the approved LibreClinica mapping.",
            )
        field_mapping = self.odm_mapping.fields_by_event.get(event_ref, {}).get(field_code)
        if field_mapping is None:
            raise EdcAdapterError(
                "libreclinica_field_not_mapped",
                f"Field code {field_code} is not in the approved LibreClinica mapping.",
            )
        subject_oid = self.resolve_subject_oid(subject_ref)
        response = self._post_soap(
            "data/v1",
            DATA_NS,
            "importRequest",
            self._data_import_request(
                subject_oid=subject_oid,
                event=event_mapping,
                field=field_mapping,
                final_value=final_value,
            ),
        )
        self._require_success(response, "libreclinica_import_rejected")
        response_sha256 = hashlib.sha256(response).hexdigest()
        external_reference = "/".join(
            (
                self.odm_mapping.study_oid,
                subject_oid,
                f"{event_mapping.event_oid}:{event_mapping.repeat_key}",
                field_mapping.form_oid,
                field_mapping.item_oid,
            )
        )
        return EdcSubmissionResult(
            external_reference=external_reference,
            response_sha256=response_sha256,
        )

    def read_value(self, transfer_package: Mapping[str, object]) -> EdcReadbackResult:
        del transfer_package
        # The qualified LibreClinica 1.4 SOAP surface exposes ODM import but no
        # approved clinical-value read API. Direct database reads are prohibited.
        return EdcReadbackResult(status="unsupported")

    def provision_subject(
        self,
        subject_ref: str,
        event_ref: str,
        *,
        enrollment_date: date,
    ) -> EdcProvisioningResult:
        """Idempotently create a pseudonymous study subject and schedule one event."""

        if not self.allow_subject_provisioning:
            raise EdcAdapterError(
                "libreclinica_subject_provisioning_disabled",
                "Automatic LibreClinica subject provisioning is disabled.",
            )
        if not SUBJECT_REF_RE.fullmatch(subject_ref):
            raise EdcAdapterError(
                "libreclinica_subject_ref_invalid",
                "The LibreClinica subject reference must be a pseudonymous research code.",
            )
        if event_ref not in self.odm_mapping.events:
            raise EdcAdapterError(
                "libreclinica_event_not_mapped",
                f"Event reference {event_ref} is not in the approved LibreClinica mapping.",
            )

        subject_created = False
        try:
            subject_oid = self.resolve_subject_oid(subject_ref)
        except EdcAdapterError as error:
            if error.code != "libreclinica_subject_not_found":
                raise
            try:
                self.create_synthetic_subject(subject_ref, enrollment_date)
                subject_created = True
            except EdcAdapterError as create_error:
                # A concurrent request may have created the same research code.
                try:
                    subject_oid = self.resolve_subject_oid(subject_ref)
                except EdcAdapterError:
                    raise create_error
            else:
                subject_oid = self.resolve_subject_oid(subject_ref)

        event_scheduled = False
        if not self.has_scheduled_event(subject_ref, event_ref):
            try:
                self.schedule_synthetic_event(subject_ref, event_ref, enrollment_date)
                event_scheduled = True
            except EdcAdapterError as schedule_error:
                # Treat a concurrent schedule as success only after a read-back.
                if not self.has_scheduled_event(subject_ref, event_ref):
                    raise schedule_error

        return EdcProvisioningResult(
            subject_ref=subject_ref,
            subject_oid=subject_oid,
            event_ref=event_ref,
            subject_created=subject_created,
            event_scheduled=event_scheduled,
        )

    def resolve_subject_oid(self, subject_label: str) -> str:
        response = self._post_soap(
            "studySubject/v1",
            STUDY_SUBJECT_NS,
            "isStudySubjectRequest",
            self._subject_lookup_request(subject_label),
        )
        root = self._require_success(response, "libreclinica_subject_not_found")
        subject_oid = self._first_text(root, {"studySubjectOID", "subjectOID"})
        if not subject_oid:
            raise EdcAdapterError(
                "libreclinica_subject_not_found",
                f"Study subject {subject_label} does not exist in LibreClinica.",
            )
        return subject_oid

    def create_synthetic_subject(self, subject_label: str, enrollment_date: date) -> str:
        """Create a synthetic subject through SOAP; never called by submit()."""

        response = self._post_soap(
            "studySubject/v1",
            STUDY_SUBJECT_NS,
            "createRequest",
            self._subject_create_request(subject_label, enrollment_date),
        )
        root = self._require_success(response, "libreclinica_subject_create_failed")
        return self._first_text(root, {"label"}) or subject_label

    def schedule_synthetic_event(self, subject_label: str, event_ref: str, start_date: date) -> str:
        """Schedule a synthetic event through SOAP; never called by submit()."""

        event_mapping = self.odm_mapping.events.get(event_ref)
        if event_mapping is None:
            raise EdcAdapterError(
                "libreclinica_event_not_mapped",
                f"Event reference {event_ref} is not in the approved LibreClinica mapping.",
            )
        response = self._post_soap(
            "event/v1",
            EVENT_NS,
            "scheduleRequest",
            self._event_schedule_request(subject_label, event_mapping.event_oid, start_date),
        )
        root = self._require_success(response, "libreclinica_event_schedule_failed")
        return self._first_text(root, {"studyEventOrdinal"}) or event_mapping.repeat_key

    def has_scheduled_event(self, subject_label: str, event_ref: str) -> bool:
        """Read-only sandbox fixture check used to keep bootstrap idempotent."""

        event_mapping = self.odm_mapping.events.get(event_ref)
        if event_mapping is None:
            raise EdcAdapterError(
                "libreclinica_event_not_mapped",
                f"Event reference {event_ref} is not in the approved LibreClinica mapping.",
            )
        response = self._post_soap(
            "studySubject/v1",
            STUDY_SUBJECT_NS,
            "listAllByStudyRequest",
            self._list_subjects_request(),
        )
        root = self._require_success(response, "libreclinica_subject_list_failed")
        for study_subject in root.iter():
            if self._local_name(study_subject.tag) != "studySubject":
                continue
            label = self._first_text(study_subject, {"label"})
            if label != subject_label:
                continue
            return any(
                self._local_name(element.tag) == "eventDefinitionOID"
                and (element.text or "").strip() == event_mapping.event_oid
                for element in study_subject.iter()
            )
        return False

    def _list_subjects_request(self) -> ET.Element:
        request = ET.Element(f"{{{STUDY_SUBJECT_NS}}}listAllByStudyRequest")
        self._append_study_ref(request)
        return request

    def _subject_lookup_request(self, subject_label: str) -> ET.Element:
        request = ET.Element(f"{{{STUDY_SUBJECT_NS}}}isStudySubjectRequest")
        subject = ET.SubElement(request, f"{{{STUDY_SUBJECT_NS}}}studySubject")
        ET.SubElement(subject, f"{{{BEANS_NS}}}label").text = subject_label
        self._append_study_ref(subject)
        return request

    def _subject_create_request(self, subject_label: str, enrollment_date: date) -> ET.Element:
        request = ET.Element(f"{{{STUDY_SUBJECT_NS}}}createRequest")
        subject = ET.SubElement(request, f"{{{STUDY_SUBJECT_NS}}}studySubject")
        ET.SubElement(subject, f"{{{BEANS_NS}}}label").text = subject_label
        ET.SubElement(subject, f"{{{BEANS_NS}}}enrollmentDate").text = enrollment_date.isoformat()
        subject_details = ET.SubElement(subject, f"{{{BEANS_NS}}}subject")
        ET.SubElement(subject_details, f"{{{BEANS_NS}}}uniqueIdentifier").text = subject_label
        self._append_study_ref(subject)
        return request

    def _event_schedule_request(self, subject_label: str, event_oid: str, start_date: date) -> ET.Element:
        request = ET.Element(f"{{{EVENT_NS}}}scheduleRequest")
        event = ET.SubElement(request, f"{{{EVENT_NS}}}event")
        subject_ref = ET.SubElement(event, f"{{{BEANS_NS}}}studySubjectRef")
        ET.SubElement(subject_ref, f"{{{BEANS_NS}}}label").text = subject_label
        self._append_study_ref(event)
        ET.SubElement(event, f"{{{BEANS_NS}}}eventDefinitionOID").text = event_oid
        ET.SubElement(event, f"{{{BEANS_NS}}}location").text = "Synthetic sandbox"
        ET.SubElement(event, f"{{{BEANS_NS}}}startDate").text = start_date.isoformat()
        return request

    def _append_study_ref(self, parent: ET.Element) -> None:
        study_ref = ET.SubElement(parent, f"{{{BEANS_NS}}}studyRef")
        ET.SubElement(study_ref, f"{{{BEANS_NS}}}identifier").text = self.odm_mapping.study_identifier

    def _data_import_request(
        self,
        *,
        subject_oid: str,
        event: LibreClinicaEventMapping,
        field: LibreClinicaFieldMapping,
        final_value: str,
    ) -> ET.Element:
        request = ET.Element(f"{{{DATA_NS}}}importRequest")
        odm = ET.SubElement(request, "ODM")
        clinical = ET.SubElement(odm, "ClinicalData", {"StudyOID": self.odm_mapping.study_oid})
        ET.SubElement(
            clinical,
            "UpsertOn",
            {"NotStarted": "true", "DataEntryStarted": "true", "DataEntryComplete": "true"},
        )
        subject = ET.SubElement(clinical, "SubjectData", {"SubjectKey": subject_oid})
        event_data = ET.SubElement(
            subject,
            "StudyEventData",
            {"StudyEventOID": event.event_oid, "StudyEventRepeatKey": event.repeat_key},
        )
        form = ET.SubElement(event_data, "FormData", {"FormOID": field.form_oid})
        group = ET.SubElement(
            form,
            "ItemGroupData",
            {"ItemGroupOID": field.item_group_oid, "ItemGroupRepeatKey": "1"},
        )
        ET.SubElement(
            group,
            "ItemData",
            {"ItemOID": field.item_oid, "Value": final_value, "TransactionType": "Insert"},
        )
        return request

    def _post_soap(
        self,
        endpoint: str,
        namespace: str,
        action: str,
        payload: ET.Element,
    ) -> bytes:
        del namespace
        envelope = ET.Element(f"{{{SOAP_ENV_NS}}}Envelope")
        header = ET.SubElement(envelope, f"{{{SOAP_ENV_NS}}}Header")
        security = ET.SubElement(header, f"{{{WSSE_NS}}}Security")
        token = ET.SubElement(security, f"{{{WSSE_NS}}}UsernameToken")
        ET.SubElement(token, f"{{{WSSE_NS}}}Username").text = self.username
        password = ET.SubElement(token, f"{{{WSSE_NS}}}Password", {"Type": PASSWORD_TEXT_TYPE})
        password.text = self._password_sha1
        body = ET.SubElement(envelope, f"{{{SOAP_ENV_NS}}}Body")
        body.append(payload)
        encoded = ET.tostring(envelope, encoding="utf-8", xml_declaration=True)
        try:
            return self._transport(f"{self.ws_base_url}/{endpoint}", encoded, self.timeout_seconds)
        except EdcAdapterError:
            raise
        except (HTTPError, URLError, TimeoutError, socket.timeout, OSError) as error:
            raise EdcAdapterError(
                "libreclinica_unreachable",
                f"LibreClinica SOAP operation {action} could not be completed.",
                retryable=True,
            ) from error

    @staticmethod
    def _http_transport(url: str, payload: bytes, timeout: float) -> bytes:
        request = Request(
            url,
            data=payload,
            headers={"Content-Type": "text/xml; charset=utf-8", "Accept": "text/xml"},
            method="POST",
        )
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL is validated above.
            return response.read()

    @staticmethod
    def _require_success(response: bytes, failure_code: str) -> ET.Element:
        try:
            root = ET.fromstring(LibreClinicaSoapAdapter._soap_xml_part(response))
        except ET.ParseError as error:
            raise EdcAdapterError(
                "libreclinica_invalid_response",
                "LibreClinica returned an invalid SOAP response.",
            ) from error
        fault = LibreClinicaSoapAdapter._first_text(root, {"faultstring", "Reason", "Text"})
        result = LibreClinicaSoapAdapter._first_text(root, {"result"})
        if fault:
            raise EdcAdapterError(failure_code, f"LibreClinica rejected the SOAP request: {fault[:300]}")
        if result is None or not result.strip().lower().startswith("success"):
            errors = [
                (element.text or "").strip()
                for element in root.iter()
                if LibreClinicaSoapAdapter._local_name(element.tag) == "error" and (element.text or "").strip()
            ]
            message = errors[0][:300] if errors else "LibreClinica did not confirm success."
            raise EdcAdapterError(failure_code, message)
        return root

    @staticmethod
    def _soap_xml_part(response: bytes) -> bytes:
        """Extract the SOAP document from LibreClinica's single-part MTOM response."""

        stripped = response.lstrip()
        if stripped.startswith(b"<"):
            return stripped
        first_line, separator, _rest = response.partition(b"\r\n")
        if not separator or not first_line.startswith(b"--"):
            return response
        for part in response.split(first_line)[1:]:
            _headers, header_separator, body = part.partition(b"\r\n\r\n")
            if not header_separator:
                continue
            candidate = body.strip(b"\r\n-")
            if candidate.startswith(b"<"):
                return candidate
        return response

    @staticmethod
    def _first_text(root: ET.Element, local_names: set[str]) -> str | None:
        for element in root.iter():
            if LibreClinicaSoapAdapter._local_name(element.tag) in local_names:
                value = (element.text or "").strip()
                if value:
                    return value
        return None

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    @staticmethod
    def _package_section(
        transfer_package: Mapping[str, object],
        key: str,
    ) -> Mapping[str, object]:
        value = transfer_package.get(key)
        if not isinstance(value, Mapping):
            raise EdcAdapterError("transfer_package_invalid", "Frozen transfer package is invalid.")
        return value

    @staticmethod
    def _required_text(section: Mapping[str, object], key: str) -> str:
        value = section.get(key)
        if not isinstance(value, str) or not value.strip():
            raise EdcAdapterError("transfer_package_invalid", "Frozen transfer package is invalid.")
        return value.strip()


def load_edc_adapter_from_environment() -> AuthorityEdcAdapter:
    return LibreClinicaSoapAdapter.from_environment()


def readiness_payload() -> dict[str, object]:
    """Backward-compatible default readiness payload for callers without an app adapter."""

    return DisabledEdcAdapter().readiness()
