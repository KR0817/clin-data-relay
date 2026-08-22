"""Deterministic, versioned candidate quality assessment."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Mapping


QUALITY_STATUS_ORDER = {"PASS": 0, "WARN": 1, "BLOCK": 2}
NUMBER_RE = re.compile(r"^(?P<operator>[<>≤≥])?\s*(?P<number>-?\d+(?:[.,]\d+)?)$")


class QualityRuleError(RuntimeError):
    """Raised when the quality-rule artifact is invalid."""


def load_quality_rules(path: Path | None = None) -> dict[str, object]:
    rules_path = path or Path(__file__).resolve().parents[1] / "config" / "clinical_quality_rules.v1.json"
    try:
        payload = json.loads(rules_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise QualityRuleError("quality_rules_unavailable") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("version"), str):
        raise QualityRuleError("quality_rules_invalid")
    if not isinstance(payload.get("default"), dict) or not isinstance(payload.get("fields"), dict):
        raise QualityRuleError("quality_rules_invalid")
    return payload


def assess_candidate(
    rules: Mapping[str, object],
    *,
    event_ref: str,
    field_code: str,
    value: str,
    unit: str | None,
) -> dict[str, object]:
    default_rule = rules.get("default")
    field_rules = rules.get("fields")
    if not isinstance(default_rule, Mapping) or not isinstance(field_rules, Mapping):
        raise QualityRuleError("quality_rules_invalid")
    rule = dict(default_rule)
    configured = field_rules.get(field_code)
    if isinstance(configured, Mapping):
        rule.update(configured)

    findings: list[dict[str, object]] = []
    stripped_value = value.strip()
    if not stripped_value:
        findings.append(_finding("BLOCK", "value_required", "A value is required."))
    max_length = rule.get("max_length")
    if isinstance(max_length, int) and len(stripped_value) > max_length:
        findings.append(_finding("BLOCK", "value_too_long", "The value exceeds the configured length."))

    if rule.get("data_type") == "number" and stripped_value:
        match = NUMBER_RE.fullmatch(stripped_value)
        if match is None:
            findings.append(_finding("BLOCK", "invalid_numeric", "The configured field requires a number."))
        else:
            operator = match.group("operator")
            numeric_value = float(match.group("number").replace(",", "."))
            if operator and not rule.get("allow_inequality"):
                findings.append(
                    _finding("WARN", "inequality_not_expected", "The numeric qualifier requires review.")
                )
            _append_range_findings(findings, rule, numeric_value)

        allowed_units = rule.get("units")
        if isinstance(allowed_units, list) and unit and _normalise_unit(unit) not in {
            _normalise_unit(str(allowed_unit)) for allowed_unit in allowed_units
        }:
            findings.append(
                _finding("WARN", "unit_not_expected", "The unit differs from the configured field units.")
            )

    status = "PASS"
    for finding in findings:
        severity = str(finding["severity"])
        if QUALITY_STATUS_ORDER[severity] > QUALITY_STATUS_ORDER[status]:
            status = severity
    return {
        "status": status,
        "rule_version": str(rules["version"]),
        "event_ref": event_ref,
        "field_code": field_code,
        "findings": findings,
    }


def _append_range_findings(
    findings: list[dict[str, object]],
    rule: Mapping[str, object],
    value: float,
) -> None:
    block_min = rule.get("block_min")
    block_max = rule.get("block_max")
    if isinstance(block_min, (int, float)) and value < float(block_min):
        findings.append(_finding("BLOCK", "below_block_min", "The value is below the blocking range."))
        return
    if isinstance(block_max, (int, float)) and value > float(block_max):
        findings.append(_finding("BLOCK", "above_block_max", "The value is above the blocking range."))
        return
    warn_min = rule.get("warn_min")
    warn_max = rule.get("warn_max")
    if isinstance(warn_min, (int, float)) and value < float(warn_min):
        findings.append(_finding("WARN", "below_warning_min", "The value is below the review range."))
    elif isinstance(warn_max, (int, float)) and value > float(warn_max):
        findings.append(_finding("WARN", "above_warning_max", "The value is above the review range."))


def _finding(severity: str, code: str, message: str) -> dict[str, object]:
    return {"severity": severity, "code": code, "message": message}


def _normalise_unit(unit: str) -> str:
    return re.sub(r"\s+", "", unit).replace("×", "x").casefold()
