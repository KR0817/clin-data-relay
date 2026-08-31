"""Allow-listed OpenAI-compatible transport for de-identified evidence only."""

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
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


BUILTIN_PROVIDER_URLS = {
    "kimi": {
        "https://api.moonshot.cn/v1",
        "https://api.moonshot.ai/v1",
    },
}
_PROVIDER_RE = re.compile(r"[a-z][a-z0-9._-]{1,63}")
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
DIRECT_IDENTIFIER_PATTERNS = (
    re.compile(r"\b1[3-9]\d{9}\b"),
    re.compile(r"\b\d{17}[0-9Xx]\b"),
)
DIRECT_IDENTIFIER_MARKERS = ("姓名", "住院号", "身份证", "手机号", "电话", "patient name")


class ModelConfigurationError(RuntimeError):
    """Raised when a model request is not explicitly and safely configured."""


class ModelServiceError(RuntimeError):
    """Raised when a provider does not produce valid structured candidate data."""


@dataclass(frozen=True)
class ModelCandidate:
    field_code: str
    proposed_value: str | None
    unit: str | None
    confidence: float
    evidence_text: str = ""
    status: str = "read"


@dataclass(frozen=True)
class ModelProviderSettings:
    enabled: bool
    api_key: str | None
    base_url: str
    model: str
    timeout_seconds: int = 45
    max_retries: int = 2
    provider: str = "kimi"
    allowed_base_urls: tuple[str, ...] = ()
    api_key_required: bool = True
    reasoning_effort: str | None = "low"

    @classmethod
    def from_environment(cls) -> "ModelProviderSettings":
        provider = (os.getenv("MODEL_PROVIDER") or "kimi").strip().lower()
        api_key = os.getenv("MODEL_API_KEY") or os.getenv("KIMI_API_KEY")
        if not api_key:
            credential_path = Path(
                os.getenv("MODEL_API_KEY_FILE")
                or os.getenv("KIMI_API_KEY_FILE", ".runtime/kimi-api-key.txt")
            )
            try:
                api_key = credential_path.read_text(encoding="utf-8").strip()
            except OSError:
                api_key = None
        raw_allowlist = os.getenv("MODEL_ALLOWED_BASE_URLS", "")
        allowed_base_urls = tuple(
            sorted({item.strip().rstrip("/") for item in raw_allowlist.split(",") if item.strip()})
        )
        enabled_value = os.getenv("MODEL_ENABLED")
        if enabled_value is None:
            enabled_value = os.getenv("KIMI_ENABLED", "true")
        key_required_value = os.getenv("MODEL_API_KEY_REQUIRED", "true")
        reasoning_default = "low" if provider == "kimi" else ""
        reasoning_effort = os.getenv("MODEL_REASONING_EFFORT", reasoning_default).strip() or None
        default_base_url = "https://api.moonshot.cn/v1" if provider == "kimi" else ""
        default_model = "kimi-k3" if provider == "kimi" else ""
        return cls(
            enabled=enabled_value.lower() == "true",
            api_key=api_key or None,
            base_url=(os.getenv("MODEL_BASE_URL") or os.getenv("KIMI_BASE_URL") or default_base_url).rstrip("/"),
            model=os.getenv("MODEL_NAME") or os.getenv("KIMI_MODEL") or default_model,
            timeout_seconds=int(os.getenv("MODEL_TIMEOUT_SECONDS") or os.getenv("KIMI_TIMEOUT_SECONDS", "45")),
            max_retries=int(os.getenv("MODEL_MAX_RETRIES") or os.getenv("KIMI_MAX_RETRIES", "2")),
            provider=provider,
            allowed_base_urls=allowed_base_urls,
            api_key_required=key_required_value.lower() != "false",
            reasoning_effort=reasoning_effort,
        )

    @property
    def normalized_base_url(self) -> str | None:
        candidate = self.base_url.rstrip("/")
        try:
            parsed = urlsplit(candidate)
            hostname = parsed.hostname
        except ValueError:
            return None
        if (
            parsed.scheme not in {"http", "https"}
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            return None
        if parsed.scheme == "http" and hostname.casefold() not in _LOOPBACK_HOSTS:
            return None
        return candidate

    @property
    def endpoint_allowed(self) -> bool:
        normalized = self.normalized_base_url
        if normalized is None or not _PROVIDER_RE.fullmatch(self.provider):
            return False
        allowed = set(BUILTIN_PROVIDER_URLS.get(self.provider, set())) | {
            item.rstrip("/") for item in self.allowed_base_urls
        }
        return normalized in allowed

    @property
    def loopback(self) -> bool:
        normalized = self.normalized_base_url
        return bool(normalized and (urlsplit(normalized).hostname or "").casefold() in _LOOPBACK_HOSTS)


class OpenAICompatibleClient:
    def __init__(
        self,
        settings: ModelProviderSettings,
        opener: Callable[..., Any] = urlopen,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self._opener = opener
        self._sleeper = sleeper

    @classmethod
    def from_environment(cls) -> "OpenAICompatibleClient":
        return cls(ModelProviderSettings.from_environment())

    def reload_from_environment(self) -> None:
        self.settings = ModelProviderSettings.from_environment()

    @property
    def enabled(self) -> bool:
        return self.settings.enabled

    @property
    def ready(self) -> bool:
        return bool(
            self.settings.enabled
            and (self.settings.api_key or (not self.settings.api_key_required and self.settings.loopback))
            and self.settings.endpoint_allowed
            and 0 < len(self.settings.model.strip()) <= 200
            and 1 <= self.settings.timeout_seconds <= 300
            and 0 <= self.settings.max_retries <= 5
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
    ) -> list[ModelCandidate]:
        self._validate_request(deidentified_ocr_text)
        allowed_fields = list(field_dictionary or {})
        if not allowed_fields:
            raise ModelConfigurationError("model_field_dictionary_required")
        if image_bytes is None or not image_bytes:
            raise ModelConfigurationError("model_deidentified_image_required")
        if media_type not in {
            "image/jpeg",
            "image/png",
            "image/gif",
            "image/webp",
            "image/bmp",
            "image/heic",
            "image/heif",
        }:
            raise ModelConfigurationError("model_image_type_not_supported")
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
        if self.settings.reasoning_effort:
            request_body["reasoning_effort"] = self.settings.reasoning_effort
        headers = {"Content-Type": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        request = Request(
            f"{self.settings.base_url}/chat/completions",
            data=json.dumps(request_body).encode("utf-8"),
            headers=headers,
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
                    raise ModelServiceError(f"Model provider returned HTTP {error.code}") from error
                retry_after = error.headers.get("Retry-After") if error.headers is not None else None
                try:
                    delay = float(retry_after) if retry_after is not None else float(2**attempt)
                except ValueError:
                    delay = float(2**attempt)
                self._sleeper(max(0.0, min(delay, 30.0)))
            except URLError as error:
                raise ModelServiceError("Model provider could not be reached") from error
            except TimeoutError as error:
                raise ModelServiceError("Model provider request timed out") from error
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ModelServiceError("Model provider did not return valid JSON") from error

        if payload is None:
            raise ModelServiceError("Model provider did not return a response")

        try:
            choice = payload["choices"][0]
            if choice["finish_reason"] != "stop":
                raise ModelServiceError("Model provider response was incomplete")
            content = choice["message"]["content"]
            structured = json.loads(content)
            raw_candidates = structured["candidates"]
        except ModelServiceError:
            raise
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise ModelServiceError("Model provider response did not contain valid candidate JSON") from error

        candidates: list[ModelCandidate] = []
        for raw_candidate in raw_candidates:
            try:
                field_code = str(raw_candidate["field_code"]).upper()
                raw_value = raw_candidate["proposed_value"]
                proposed_value = None if raw_value is None else str(raw_value)
                unit = raw_candidate.get("unit")
                evidence = str(raw_candidate["evidence_text"])
                candidate_status = str(raw_candidate["status"])
            except (AttributeError, KeyError, TypeError, ValueError) as error:
                raise ModelServiceError("Model provider response contains an invalid candidate") from error
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", field_code):
                raise ModelServiceError("Model provider response contains an invalid field_code")
            if field_code not in allowed_fields:
                raise ModelServiceError("Model provider response contains a field outside the CRF dictionary")
            if candidate_status == "not_visible":
                proposed_value = None
            elif not proposed_value:
                raise ModelServiceError("Model provider response contains an invalid value or evidence")
            if (proposed_value is not None and len(proposed_value) > 200) or len(evidence) > 500:
                raise ModelServiceError("Model provider response contains an invalid value or evidence")
            if unit is not None and len(str(unit)) > 50:
                raise ModelServiceError("Model provider response contains an invalid unit")
            if candidate_status not in {"read", "uncertain", "not_visible"}:
                raise ModelServiceError("Model provider response contains an invalid status")
            confidence = 0.8 if candidate_status == "read" else 0.35 if candidate_status == "uncertain" else 0.1
            candidates.append(
                ModelCandidate(
                    field_code,
                    proposed_value,
                    str(unit) if unit else None,
                    confidence,
                    evidence,
                    candidate_status,
                )
            )
        if not candidates:
            raise ModelServiceError("Model provider response contains no candidates")
        return candidates

    def _validate_request(self, text: str) -> None:
        if not self.settings.enabled:
            raise ModelConfigurationError("model_integration_disabled")
        if self.settings.api_key_required and not self.settings.api_key:
            raise ModelConfigurationError("model_api_key_not_configured")
        if not self.settings.endpoint_allowed:
            raise ModelConfigurationError("model_base_url_not_allowlisted")
        if not self.settings.api_key and not self.settings.loopback:
            raise ModelConfigurationError("model_api_key_not_configured")
        if not (0 < len(self.settings.model.strip()) <= 200):
            raise ModelConfigurationError("model_name_invalid")
        if not (1 <= self.settings.timeout_seconds <= 300 and 0 <= self.settings.max_retries <= 5):
            raise ModelConfigurationError("model_runtime_limits_invalid")
        lowered = text.lower()
        if any(marker.lower() in lowered for marker in DIRECT_IDENTIFIER_MARKERS):
            raise ModelConfigurationError("deidentified_text_required")
        if any(pattern.search(text) for pattern in DIRECT_IDENTIFIER_PATTERNS):
            raise ModelConfigurationError("deidentified_text_required")


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
                raise OSError("model_credential_acl_failed")
        else:
            os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, credential_path)
    except subprocess.SubprocessError as error:
        raise OSError("model_credential_acl_failed") from error
    finally:
        temporary_path.unlink(missing_ok=True)
