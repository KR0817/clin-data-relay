"""Synthetic-only extractor qualification metrics."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Mapping


def _numeric(value: object) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", ".").strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def evaluate_predictions(
    expected: Mapping[str, Mapping[str, object]],
    predicted: Mapping[str, Mapping[str, object]],
    *,
    numeric_tolerance: Decimal = Decimal("0.01"),
) -> dict[str, object]:
    fields = sorted(set(expected) | set(predicted))
    exact = numeric = unit = missing = extra = 0
    for field in fields:
        expected_value = expected.get(field)
        actual_value = predicted.get(field)
        if expected_value is None:
            extra += 1
            continue
        if actual_value is None:
            missing += 1
            continue
        expected_text = str(expected_value.get("value", "")).strip()
        actual_text = str(actual_value.get("value", "")).strip()
        if expected_text == actual_text:
            exact += 1
        else:
            expected_number = _numeric(expected_text)
            actual_number = _numeric(actual_text)
            if expected_number is not None and actual_number is not None and abs(expected_number - actual_number) <= numeric_tolerance:
                numeric += 1
        if str(expected_value.get("unit", "") or "").strip().lower() == str(actual_value.get("unit", "") or "").strip().lower():
            unit += 1
    total = len(expected)
    return {
        "field_count": total,
        "exact_match_count": exact,
        "numeric_tolerance_match_count": numeric,
        "unit_match_count": unit,
        "missing_count": missing,
        "extra_count": extra,
        "exact_match_rate": round(exact / total, 4) if total else 0.0,
        "numeric_tolerance_match_rate": round((exact + numeric) / total, 4) if total else 0.0,
        "unit_match_rate": round(unit / total, 4) if total else 0.0,
    }
