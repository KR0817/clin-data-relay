from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from app.kimi import KimiClient, KimiConfigurationError, KimiServiceError, KimiSettings


class SyntheticHttpResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "SyntheticHttpResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class SyntheticInvalidJsonResponse(SyntheticHttpResponse):
    def read(self) -> bytes:
        return b"not-json"


def test_kimi_multimodal_extraction_uses_confirmed_image_and_strict_field_schema() -> None:
    captured: dict[str, object] = {}

    def synthetic_open(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return SyntheticHttpResponse(
            {
                "id": "chatcmpl_synthetic_001",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "candidates": [
                                        {
                                            "field_code": "ALT",
                                            "proposed_value": "31",
                                            "unit": "U/L",
                                            "evidence_text": "ALT 31 U/L",
                                            "status": "read",
                                        }
                                    ]
                                }
                            )
                        },
                    }
                ],
            }
        )

    client = KimiClient(
        KimiSettings(
            enabled=True,
            api_key="synthetic-secret",
            base_url="https://api.moonshot.cn/v1",
            model="kimi-k3",
        ),
        opener=synthetic_open,
    )

    candidates = client.extract_candidates(
        image_bytes=b"synthetic-deidentified-png",
        media_type="image/png",
        deidentified_ocr_text="ALT 3l U/L",
        ocr_evidence="ALT\t3l\tU/L",
        event_ref="WEEK_0",
        field_dictionary={"ALT": "丙氨酸氨基转移酶", "AST": "天门冬氨酸氨基转移酶"},
    )

    assert [(item.field_code, item.proposed_value, item.unit, item.status) for item in candidates] == [
        ("ALT", "31", "U/L", "read")
    ]
    request = captured["request"]
    body = json.loads(request.data.decode("utf-8"))
    assert body["model"] == "kimi-k3"
    assert body["reasoning_effort"] == "low"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    candidate_schema = body["response_format"]["json_schema"]["schema"]["properties"]["candidates"]["items"]
    assert candidate_schema["additionalProperties"] is False
    assert candidate_schema["properties"]["field_code"]["enum"] == ["ALT", "AST"]
    user_content = body["messages"][1]["content"]
    assert user_content[0]["type"] == "text"
    assert "WEEK_0" in user_content[0]["text"]
    assert "ALT" in user_content[0]["text"]
    assert user_content[1] == {
        "type": "image_url",
        "image_url": {
            "url": "data:image/png;base64,"
            + base64.b64encode(b"synthetic-deidentified-png").decode("ascii")
        },
    }
    assert request.headers["Authorization"] == "Bearer synthetic-secret"
    assert captured["timeout"] == 45


def test_kimi_accepts_single_character_field_code_from_the_crf_dictionary() -> None:
    client = KimiClient(
        KimiSettings(
            enabled=True,
            api_key="synthetic-secret",
            base_url="https://api.moonshot.cn/v1",
            model="kimi-k3",
        ),
        opener=lambda _request, *, timeout: SyntheticHttpResponse(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "candidates": [
                                        {
                                            "field_code": "K",
                                            "proposed_value": "3.9",
                                            "unit": "mmol/L",
                                            "evidence_text": "K 3.9 mmol/L",
                                            "status": "read",
                                        }
                                    ]
                                }
                            )
                        },
                    }
                ]
            }
        ),
    )

    candidates = client.extract_candidates(
        image_bytes=b"synthetic-image",
        media_type="image/png",
        deidentified_ocr_text="K 3.9 mmol/L",
        event_ref="WEEK_0",
        field_dictionary={"K": "Potassium"},
    )

    assert [(item.field_code, item.proposed_value, item.unit) for item in candidates] == [
        ("K", "3.9", "mmol/L")
    ]


def test_kimi_retries_a_transient_overload_before_returning_candidates() -> None:
    calls = 0
    sleeps: list[float] = []

    def synthetic_open(_request, *, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HTTPError(
                "https://api.moonshot.cn/v1/chat/completions",
                429,
                "overloaded",
                {"Retry-After": "0"},
                None,
            )
        return SyntheticHttpResponse(
            {
                "id": "chatcmpl_synthetic_retry",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "candidates": [
                                        {
                                            "field_code": "ALT",
                                            "proposed_value": "31",
                                            "unit": "U/L",
                                            "evidence_text": "ALT 31 U/L",
                                            "status": "read",
                                        }
                                    ]
                                }
                            )
                        },
                    }
                ],
            }
        )

    client = KimiClient(
        KimiSettings(
            enabled=True,
            api_key="synthetic-secret",
            base_url="https://api.moonshot.cn/v1",
            model="kimi-k3",
        ),
        opener=synthetic_open,
        sleeper=sleeps.append,
    )

    result = client.extract_candidates(
        image_bytes=b"synthetic-deidentified-png",
        media_type="image/png",
        deidentified_ocr_text="ALT 3l U/L",
        event_ref="WEEK_0",
        field_dictionary={"ALT": "丙氨酸氨基转移酶"},
    )

    assert [(item.field_code, item.proposed_value) for item in result] == [("ALT", "31")]
    assert calls == 2
    assert sleeps == [0.0]


def test_kimi_settings_load_the_server_side_key_from_an_ignored_runtime_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential_file = tmp_path / "kimi-api-key.txt"
    credential_file.write_text("synthetic-runtime-secret\n", encoding="utf-8")
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.setenv("KIMI_API_KEY_FILE", str(credential_file))
    monkeypatch.setenv("KIMI_ENABLED", "true")

    settings = KimiSettings.from_environment()

    assert settings.enabled is True
    assert settings.api_key == "synthetic-runtime-secret"


def test_kimi_is_enabled_by_default_but_not_ready_without_a_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KIMI_ENABLED", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.setenv("KIMI_API_KEY_FILE", "C:/path/that/does/not/exist/kimi-api-key.txt")

    settings = KimiSettings.from_environment()

    assert settings.enabled is True
    assert settings.api_key is None


def test_kimi_blocks_outbound_request_when_ocr_coordinate_evidence_still_contains_an_identifier() -> None:
    def forbidden_open(_request, _timeout):
        raise AssertionError("identified OCR evidence must not leave the server")

    client = KimiClient(
        KimiSettings(
            enabled=True,
            api_key="synthetic-secret",
            base_url="https://api.moonshot.cn/v1",
            model="kimi-k3",
        ),
        opener=forbidden_open,
    )

    with pytest.raises(KimiConfigurationError, match="deidentified_text_required"):
        client.extract_candidates(
            image_bytes=b"synthetic-image",
            media_type="image/png",
            deidentified_ocr_text="ALT 31 U/L",
            ocr_evidence="text\tleft\ttop\n姓名\t10\t20\n张三\t40\t20",
            event_ref="WEEK_0",
            field_dictionary={"ALT": "ALT"},
        )


def test_kimi_reports_a_bounded_service_error_for_a_malformed_provider_response() -> None:
    client = KimiClient(
        KimiSettings(
            enabled=True,
            api_key="synthetic-secret",
            base_url="https://api.moonshot.cn/v1",
            model="kimi-k3",
        ),
        opener=lambda _request, *, timeout: SyntheticInvalidJsonResponse({}),
    )

    with pytest.raises(KimiServiceError, match="valid JSON"):
        client.extract_candidates(
            image_bytes=b"synthetic-image",
            media_type="image/png",
            deidentified_ocr_text="ALT 31 U/L",
            event_ref="WEEK_0",
            field_dictionary={"ALT": "ALT"},
        )


def test_kimi_preserves_not_visible_as_missing_instead_of_a_literal_none_value() -> None:
    client = KimiClient(
        KimiSettings(
            enabled=True,
            api_key="synthetic-secret",
            base_url="https://api.moonshot.cn/v1",
            model="kimi-k3",
        ),
        opener=lambda _request, *, timeout: SyntheticHttpResponse(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "candidates": [
                                        {
                                            "field_code": "ALT",
                                            "proposed_value": None,
                                            "unit": None,
                                            "evidence_text": "ALT row is obscured",
                                            "status": "not_visible",
                                        }
                                    ]
                                }
                            )
                        },
                    }
                ]
            }
        ),
    )

    candidates = client.extract_candidates(
        image_bytes=b"synthetic-image",
        media_type="image/png",
        deidentified_ocr_text="ALT",
        event_ref="WEEK_0",
        field_dictionary={"ALT": "ALT"},
    )

    assert candidates[0].status == "not_visible"
    assert candidates[0].proposed_value is None
