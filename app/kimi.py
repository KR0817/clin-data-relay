"""A server-side Kimi K3 adapter for de-identified OCR text only.

Kimi is enabled by default at the application boundary, but outbound calls
remain fail-closed until a recipient-local key is configured.  ``KIMI_ENABLED``
can still be set to ``false`` for a local-only run.
"""

from __future__ import annotations

import json
import os
import re
import base64
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ALLOWED_BASE_URLS = {
    "https://api.moonshot.cn/v1",
    "https://api.moonshot.ai/v1",
}
DIRECT_IDENTIFIER_PATTERNS = (
    re.compile(r"\b1[3-9]\d{9}\b"),
    re.compile(r"\b\d{17}[0-9Xx]\b"),
)
DIRECT_IDENTIFIER_MARKERS = ("姓名", "住院号", "身份证", "手机号", "电话", "patient name")


class KimiConfigurationError(RuntimeError):
    """Raised when a Kimi request is not explicitly and safely configured."""


class KimiServiceError(RuntimeError):
    """Raised when Kimi does not produce valid structured candidate data."""


@dataclass(frozen=True)
class KimiCandidate:
    field_code: str
    proposed_value: str | None
    unit: str | None
    confidence: float
    evidence_text: str = ""
    status: str = "read"


@dataclass(frozen=True)
class KimiSettings:
    enabled: bool
    api_key: str | None
    base_url: str
    model: str
    timeout_seconds: int = 45
    max_retries: int = 2

    @classmethod
    def from_environment(cls) -> "KimiSettings":
        api_key = os.getenv("KIMI_API_KEY")
        if not api_key:
            credential_path = Path(os.getenv("KIMI_API_KEY_FILE", ".runtime/kimi-api-key.txt"))
            try:
                api_key = credential_path.read_text(encoding="utf-8").strip()
            except OSError:
                api_key = None
        return cls(
            enabled=os.getenv("KIMI_ENABLED", "true").lower() == "true",
            api_key=api_key or None,
            base_url=os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1").rstrip("/"),
            model=os.getenv("KIMI_MODEL", "kimi-k3"),
            timeout_seconds=int(os.getenv("KIMI_TIMEOUT_SECONDS", "45")),
            max_retries=int(os.getenv("KIMI_MAX_RETRIES", "2")),
        )


class KimiClient:
    def __init__(
        self,
        settings: KimiSettings,
        opener: Callable[..., Any] = urlopen,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self._opener = opener
        self._sleeper = sleeper

    @classmethod
    def from_environment(cls) -> "KimiClient":
        return cls(KimiSettings.from_environment())

    def reload_from_environment(self) -> None:
        self.settings = KimiSettings.from_environment()

    @property
    def enabled(self) -> bool:
        return self.settings.enabled

    @property
    def ready(self) -> bool:
        return bool(
            self.settings.enabled
            and self.settings.api_key
            and self.settings.base_url in ALLOWED_BASE_URLS
            and self.settings.model == "kimi-k3"
        )

    def extract_candidates(
        self,
        deidentified_ocr_text: str,
        *,
        image_bytes: bytes | None = None,
        media_type: str = "image/png",
        ocr_evidence: str = "",
        event_ref: str = "UNSPECIFIED",
        field_dictionary: Mapping[str, str] | None = None,
    ) -> list[KimiCandidate]:
        self._validate_request(deidentified_ocr_text)
        allowed_fields = list(field_dictionary or {})
        if not allowed_fields:
            raise KimiConfigurationError("kimi_field_dictionary_required")
        if image_bytes is None or not image_bytes:
            raise KimiConfigurationError("kimi_deidentified_image_required")
        if media_type not in {
            "image/jpeg",
            "image/png",
            "image/gif",
            "image/webp",
            "image/bmp",
            "image/heic",
            "image/heif",
        }:
            raise KimiConfigurationError("kimi_image_type_not_supported")
        dictionary_text = "\n".join(
            f"- {code}: {str(label)[:200]}" for code, label in (field_dictionary or {}).items()
        )
        evidence_text = ocr_evidence[:100_000]
        if evidence_text:
            self._validate_request(evidence_text)
        user_text = (
            f"EVENT: {event_ref}\n"
            "ALLOWED CRF FIELDS:\n"
            f"{dictionary_text}\n\n"
            "LOCAL OCR TEXT:\n"
            f"{deidentified_ocr_text[:20_000]}\n\n"
            "LOCAL OCR WORD/COORDINATE EVIDENCE:\n"
            f"{evidence_text or '[not available]'}"
        )
        image_data_url = (
            f"data:{media_type};base64," + base64.b64encode(image_bytes).decode("ascii")
        )
        candidate_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "field_code": {"type": "string", "enum": allowed_fields},
                "proposed_value": {"type": ["string", "null"], "minLength": 1, "maxLength": 200},
                "unit": {"type": ["string", "null"], "maxLength": 50},
                "evidence_text": {"type": "string", "maxLength": 500},
                "status": {"type": "string", "enum": ["read", "uncertain", "not_visible"]},
            },
            "required": ["field_code", "proposed_value", "unit", "evidence_text", "status"],
        }
        request_body = {
            "model": self.settings.model,
            "reasoning_effort": "low",
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "clinical_lab_candidates",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "candidates": {"type": "array", "items": candidate_schema, "maxItems": 200}
                        },
                        "required": ["candidates"],
                    },
                },
            },
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Extract candidate values only from visible evidence in this confirmed de-identified image. "
                        "Use the local OCR only as fallible supporting evidence. Never guess, complete missing values, "
                        "infer diagnoses, or return a field outside the supplied CRF dictionary. Mark ambiguous readings "
                        "as uncertain. Return only the required structured output."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                },
            ],
        }
        request = Request(
            f"{self.settings.base_url}/chat/completions",
            data=json.dumps(request_body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        payload: dict[str, Any] | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                with self._opener(request, timeout=self.settings.timeout_seconds) as response:  # nosec B310: URL is allow-listed below
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as error:
                retryable = error.code in {429, 503, 504} and attempt < self.settings.max_retries
                if not retryable:
                    raise KimiServiceError(f"Kimi API returned HTTP {error.code}") from error
                retry_after = error.headers.get("Retry-After") if error.headers is not None else None
                try:
                    delay = float(retry_after) if retry_after is not None else float(2**attempt)
                except ValueError:
                    delay = float(2**attempt)
                self._sleeper(max(0.0, min(delay, 30.0)))
            except URLError as error:
                raise KimiServiceError("Kimi API could not be reached") from error
            except TimeoutError as error:
                raise KimiServiceError("Kimi API request timed out") from error
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise KimiServiceError("Kimi API did not return valid JSON") from error

        if payload is None:
            raise KimiServiceError("Kimi API did not return a response")

        try:
            choice = payload["choices"][0]
            if choice["finish_reason"] != "stop":
                raise KimiServiceError("Kimi response was incomplete")
            content = choice["message"]["content"]
            structured = json.loads(content)
            raw_candidates = structured["candidates"]
        except KimiServiceError:
            raise
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise KimiServiceError("Kimi response did not contain valid candidate JSON") from error

        candidates: list[KimiCandidate] = []
        for raw_candidate in raw_candidates:
            try:
                field_code = str(raw_candidate["field_code"]).upper()
                raw_value = raw_candidate["proposed_value"]
                proposed_value = None if raw_value is None else str(raw_value)
                unit = raw_candidate.get("unit")
                evidence = str(raw_candidate["evidence_text"])
                candidate_status = str(raw_candidate["status"])
            except (AttributeError, KeyError, TypeError, ValueError) as error:
                raise KimiServiceError("Kimi response contains an invalid candidate") from error
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", field_code):
                raise KimiServiceError("Kimi response contains an invalid field_code")
            if field_code not in allowed_fields:
                raise KimiServiceError("Kimi response contains a field outside the CRF dictionary")
            if candidate_status == "not_visible":
                proposed_value = None
            elif not proposed_value:
                raise KimiServiceError("Kimi response contains an invalid value or evidence")
            if (proposed_value is not None and len(proposed_value) > 200) or len(evidence) > 500:
                raise KimiServiceError("Kimi response contains an invalid value or evidence")
            if unit is not None and len(str(unit)) > 50:
                raise KimiServiceError("Kimi response contains an invalid unit")
            if candidate_status not in {"read", "uncertain", "not_visible"}:
                raise KimiServiceError("Kimi response contains an invalid status")
            confidence = 0.8 if candidate_status == "read" else 0.35 if candidate_status == "uncertain" else 0.1
            candidates.append(
                KimiCandidate(
                    field_code,
                    proposed_value,
                    str(unit) if unit else None,
                    confidence,
                    evidence,
                    candidate_status,
                )
            )
        if not candidates:
            raise KimiServiceError("Kimi response contains no candidates")
        return candidates

    def _validate_request(self, text: str) -> None:
        if not self.settings.enabled:
            raise KimiConfigurationError("kimi_integration_disabled")
        if not self.settings.api_key:
            raise KimiConfigurationError("kimi_api_key_not_configured")
        if self.settings.base_url not in ALLOWED_BASE_URLS:
            raise KimiConfigurationError("kimi_base_url_not_allowlisted")
        lowered = text.lower()
        if any(marker.lower() in lowered for marker in DIRECT_IDENTIFIER_MARKERS):
            raise KimiConfigurationError("deidentified_text_required")
        if any(pattern.search(text) for pattern in DIRECT_IDENTIFIER_PATTERNS):
            raise KimiConfigurationError("deidentified_text_required")


def write_local_api_key(credential_path: Path, api_key: str) -> None:
    """Atomically replace a recipient-local key without exposing it to logs."""

    credential_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = credential_path.with_name(f".{credential_path.name}.{os.getpid()}.tmp")
    try:
        descriptor = os.open(temporary_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(api_key)
        if os.name == "nt":
            domain = os.getenv("USERDOMAIN", "").strip()
            username = os.getenv("USERNAME", "").strip()
            identity = f"{domain}\\{username}" if domain and username else username
            if not identity:
                identity = subprocess.run(
                    ["whoami.exe"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                ).stdout.strip()
            result = subprocess.run(
                [
                    "icacls.exe",
                    str(temporary_path),
                    "/inheritance:r",
                    "/grant:r",
                    f"{identity}:(R,W)",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise OSError("kimi_credential_acl_failed")
        else:
            os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, credential_path)
    except subprocess.SubprocessError as error:
        raise OSError("kimi_credential_acl_failed") from error
    finally:
        temporary_path.unlink(missing_ok=True)
