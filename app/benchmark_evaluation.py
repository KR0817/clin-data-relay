"""Versioned, value-safe scoring for synthetic extraction benchmarks."""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Mapping, Sequence


GOLD_SCHEMA_VERSION = "clin-data-relay-gold-v1"
PREDICTION_SCHEMA_VERSION = "clin-data-relay-prediction-v1"
SUMMARY_SCHEMA_VERSION = "clin-data-relay-benchmark-summary-v1"
PACKAGE_SCHEMA_VERSION = "clin-data-relay-benchmark-package-v1"
NORMALIZATION_VERSION = "benchmark-normalization-v1"
ERROR_TAXONOMY_VERSION = "extraction-error-taxonomy-v0.1"
ALLOWED_PREDICTION_STATUSES = {"completed", "fallback", "provider_error", "timeout"}
ALLOWED_PRIVACY_GATE_DECISIONS = {"allow", "block"}
PRIMARY_ERROR_CATEGORIES = {
    "character_or_digit_recognition",
    "decimal_sign_or_comparison_symbol_error",
    "unit_missing_incorrect_or_unjustifiably_converted",
    "field_or_dictionary_mapping_error",
    "row_column_page_or_reading_order_error",
    "reference_interval_mistaken_for_result",
    "required_field_missed",
    "unsupported_or_hallucinated_value",
    "duplicate_candidate",
    "direct_identifier_privacy_gate_failure",
    "source_genuinely_unreadable_or_ambiguous",
}

_FIELD_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_COMPARATOR_MAP = {"": "", "<": "<", "<=": "<=", "≤": "<=", ">": ">", ">=": ">=", "≥": ">="}


class BenchmarkValidationError(ValueError):
    """Raised when a benchmark artifact violates its frozen contract."""


@dataclass(frozen=True)
class BenchmarkField:
    field_code: str
    value: str
    comparator: str
    unit: str
    reference_interval: str


@dataclass(frozen=True)
class GoldReport:
    report_id: str
    visit_ref: str
    report_type: str
    challenge_classes: tuple[str, ...]
    privacy_gate_expected: str
    fields: tuple[BenchmarkField, ...]


@dataclass(frozen=True)
class PredictionReport:
    report_id: str
    visit_ref: str
    arm: str
    status: str
    privacy_gate_decision: str
    fields: tuple[BenchmarkField, ...]
    latency_ms: int
    provider_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    fallback_reason: str
    review_outcome: tuple[int, int, int] | None


@dataclass(frozen=True)
class BenchmarkError:
    report_id: str
    visit_ref: str
    arm: str
    field_code: str
    error_kind: str
    primary_category: str


@dataclass(frozen=True)
class ReportScore:
    report_id: str
    gold_fields: int
    predicted_fields: int
    detected_fields: int
    strict_correct: int
    numeric_correct: int
    missing_fields: int
    unsupported_fields: int
    unit_errors: int
    comparator_errors: int
    reference_interval_errors: int
    privacy_gate_challenges: int
    privacy_gate_false_negatives: int
    privacy_gate_false_positives: int
    exact_report: int


def _required_keys(payload: Mapping[str, object], expected: set[str], code: str) -> None:
    if set(payload) != expected:
        raise BenchmarkValidationError(code)


def _bounded_string(value: object, *, code: str, limit: int = 200, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise BenchmarkValidationError(code)
    normalized = value.strip()
    if (not normalized and not allow_empty) or len(normalized) > limit or any(ord(char) < 32 for char in normalized):
        raise BenchmarkValidationError(code)
    return normalized


def _non_negative_int(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BenchmarkValidationError(code)
    return value


def _non_negative_decimal(value: object, code: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise BenchmarkValidationError(code) from error
    if not parsed.is_finite() or parsed < 0:
        raise BenchmarkValidationError(code)
    return parsed


def _parse_field(payload: object, *, gold: bool) -> BenchmarkField:
    if not isinstance(payload, Mapping):
        raise BenchmarkValidationError("benchmark_field_invalid")
    gold_keys = {
        "field_code",
        "displayed_label",
        "value",
        "comparator",
        "unit",
        "reference_interval",
        "page_number",
        "evidence_region",
    }
    prediction_keys = {"field_code", "value", "comparator", "unit", "reference_interval", "page_number"}
    _required_keys(payload, gold_keys if gold else prediction_keys, "benchmark_field_shape_invalid")
    field_code = _bounded_string(payload["field_code"], code="benchmark_field_code_invalid", limit=64).upper()
    if not _FIELD_CODE_RE.fullmatch(field_code):
        raise BenchmarkValidationError("benchmark_field_code_invalid")
    value = _bounded_string(payload["value"], code="benchmark_value_invalid")
    comparator = _bounded_string(payload["comparator"], code="benchmark_comparator_invalid", limit=2, allow_empty=True)
    if comparator not in _COMPARATOR_MAP:
        raise BenchmarkValidationError("benchmark_comparator_invalid")
    unit = _bounded_string(payload["unit"], code="benchmark_unit_invalid", limit=50, allow_empty=True)
    reference_interval = _bounded_string(
        payload["reference_interval"], code="benchmark_reference_interval_invalid", limit=100, allow_empty=True
    )
    page_number = payload["page_number"]
    if page_number is not None and (isinstance(page_number, bool) or not isinstance(page_number, int) or page_number < 1):
        raise BenchmarkValidationError("benchmark_page_number_invalid")
    if gold:
        _bounded_string(payload["displayed_label"], code="benchmark_displayed_label_invalid", limit=200)
        region = payload["evidence_region"]
        if region is not None:
            if not isinstance(region, list) or len(region) != 4:
                raise BenchmarkValidationError("benchmark_evidence_region_invalid")
            for coordinate in region:
                if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)) or not math.isfinite(coordinate):
                    raise BenchmarkValidationError("benchmark_evidence_region_invalid")
    return BenchmarkField(field_code, value, comparator, unit, reference_interval)


def _unique_fields(items: object, *, gold: bool) -> tuple[BenchmarkField, ...]:
    if not isinstance(items, list) or len(items) > 500:
        raise BenchmarkValidationError("benchmark_fields_invalid")
    fields = tuple(_parse_field(item, gold=gold) for item in items)
    codes = [field.field_code for field in fields]
    if len(codes) != len(set(codes)):
        raise BenchmarkValidationError("duplicate_candidate")
    return fields


def parse_gold_records(records: Iterable[Mapping[str, object]]) -> tuple[GoldReport, ...]:
    parsed: list[GoldReport] = []
    seen: set[tuple[str, str]] = set()
    required = {
        "schema_version",
        "report_id",
        "visit_ref",
        "report_type",
        "challenge_classes",
        "privacy_gate_expected",
        "fields",
    }
    for payload in records:
        _required_keys(payload, required, "benchmark_gold_shape_invalid")
        if payload["schema_version"] != GOLD_SCHEMA_VERSION:
            raise BenchmarkValidationError("benchmark_gold_schema_unsupported")
        report_id = _bounded_string(payload["report_id"], code="benchmark_report_id_invalid")
        visit_ref = _bounded_string(payload["visit_ref"], code="benchmark_visit_ref_invalid", limit=100)
        report_type = _bounded_string(payload["report_type"], code="benchmark_report_type_invalid", limit=100)
        raw_challenges = payload["challenge_classes"]
        if not isinstance(raw_challenges, list) or len(raw_challenges) > 20:
            raise BenchmarkValidationError("benchmark_challenge_classes_invalid")
        challenges = tuple(
            _bounded_string(item, code="benchmark_challenge_class_invalid", limit=100) for item in raw_challenges
        )
        privacy_gate_expected = _bounded_string(
            payload["privacy_gate_expected"], code="benchmark_privacy_gate_expected_invalid", limit=10
        )
        if privacy_gate_expected not in ALLOWED_PRIVACY_GATE_DECISIONS:
            raise BenchmarkValidationError("benchmark_privacy_gate_expected_invalid")
        key = (report_id, visit_ref)
        if key in seen:
            raise BenchmarkValidationError("benchmark_gold_report_duplicate")
        seen.add(key)
        fields = _unique_fields(payload["fields"], gold=True)
        if privacy_gate_expected == "block" and fields:
            raise BenchmarkValidationError("benchmark_blocked_gold_fields_forbidden")
        parsed.append(GoldReport(report_id, visit_ref, report_type, challenges, privacy_gate_expected, fields))
    if not parsed:
        raise BenchmarkValidationError("benchmark_gold_empty")
    return tuple(parsed)


def parse_prediction_records(
    records: Iterable[Mapping[str, object]], *, expected_arm: str
) -> tuple[PredictionReport, ...]:
    arm = _bounded_string(expected_arm, code="benchmark_arm_invalid", limit=64)
    parsed: list[PredictionReport] = []
    seen: set[tuple[str, str]] = set()
    required = {
        "schema_version",
        "report_id",
        "visit_ref",
        "arm",
        "status",
        "privacy_gate_decision",
        "fields",
        "latency_ms",
        "provider_calls",
        "token_usage",
        "cost_usd",
        "fallback_reason",
        "review_outcome",
    }
    for payload in records:
        _required_keys(payload, required, "benchmark_prediction_shape_invalid")
        if payload["schema_version"] != PREDICTION_SCHEMA_VERSION:
            raise BenchmarkValidationError("benchmark_prediction_schema_unsupported")
        if payload["arm"] != arm:
            raise BenchmarkValidationError("benchmark_prediction_arm_mismatch")
        report_id = _bounded_string(payload["report_id"], code="benchmark_report_id_invalid")
        visit_ref = _bounded_string(payload["visit_ref"], code="benchmark_visit_ref_invalid", limit=100)
        status = _bounded_string(payload["status"], code="benchmark_prediction_status_invalid", limit=30)
        if status not in ALLOWED_PREDICTION_STATUSES:
            raise BenchmarkValidationError("benchmark_prediction_status_invalid")
        privacy_gate_decision = _bounded_string(
            payload["privacy_gate_decision"], code="benchmark_privacy_gate_decision_invalid", limit=10
        )
        if privacy_gate_decision not in ALLOWED_PRIVACY_GATE_DECISIONS:
            raise BenchmarkValidationError("benchmark_privacy_gate_decision_invalid")
        token_usage = payload["token_usage"]
        if not isinstance(token_usage, Mapping):
            raise BenchmarkValidationError("benchmark_token_usage_invalid")
        _required_keys(token_usage, {"input", "output"}, "benchmark_token_usage_invalid")
        fallback_reason = _bounded_string(
            payload["fallback_reason"], code="benchmark_fallback_reason_invalid", limit=100, allow_empty=True
        )
        if status == "fallback" and not fallback_reason:
            raise BenchmarkValidationError("benchmark_fallback_reason_required")
        if status != "fallback" and fallback_reason:
            raise BenchmarkValidationError("benchmark_fallback_reason_unexpected")
        fields = _unique_fields(payload["fields"], gold=False)
        if privacy_gate_decision == "block" and fields:
            raise BenchmarkValidationError("benchmark_blocked_prediction_fields_forbidden")
        raw_review = payload["review_outcome"]
        review_outcome: tuple[int, int, int] | None = None
        if raw_review is not None:
            if not isinstance(raw_review, Mapping):
                raise BenchmarkValidationError("benchmark_review_outcome_invalid")
            _required_keys(raw_review, {"edits", "rejects", "review_time_ms"}, "benchmark_review_outcome_invalid")
            review_outcome = (
                _non_negative_int(raw_review["edits"], "benchmark_review_outcome_invalid"),
                _non_negative_int(raw_review["rejects"], "benchmark_review_outcome_invalid"),
                _non_negative_int(raw_review["review_time_ms"], "benchmark_review_outcome_invalid"),
            )
        key = (report_id, visit_ref)
        if key in seen:
            raise BenchmarkValidationError("benchmark_prediction_report_duplicate")
        seen.add(key)
        parsed.append(
            PredictionReport(
                report_id=report_id,
                visit_ref=visit_ref,
                arm=arm,
                status=status,
                privacy_gate_decision=privacy_gate_decision,
                fields=fields,
                latency_ms=_non_negative_int(payload["latency_ms"], "benchmark_latency_invalid"),
                provider_calls=_non_negative_int(payload["provider_calls"], "benchmark_provider_calls_invalid"),
                input_tokens=_non_negative_int(token_usage["input"], "benchmark_token_usage_invalid"),
                output_tokens=_non_negative_int(token_usage["output"], "benchmark_token_usage_invalid"),
                cost_usd=_non_negative_decimal(payload["cost_usd"], "benchmark_cost_invalid"),
                fallback_reason=fallback_reason,
                review_outcome=review_outcome,
            )
        )
    if not parsed:
        raise BenchmarkValidationError("benchmark_predictions_empty")
    return tuple(parsed)


def load_jsonl(path: Path) -> tuple[Mapping[str, object], ...]:
    records: list[Mapping[str, object]] = []
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as error:
        raise BenchmarkValidationError("benchmark_input_unreadable") from error
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise BenchmarkValidationError(f"benchmark_json_invalid_line_{line_number}") from error
        if not isinstance(payload, Mapping):
            raise BenchmarkValidationError(f"benchmark_json_object_required_line_{line_number}")
        records.append(payload)
    return tuple(records)


def _text(value: str) -> str:
    return " ".join(value.strip().split())


def _unit(value: str) -> str:
    return _text(value).casefold()


def _comparator(value: str) -> str:
    return _COMPARATOR_MAP[value]


def _decimal(value: str) -> Decimal | None:
    candidate = _text(value).replace(",", ".")
    try:
        number = Decimal(candidate)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _numeric_value_equal(expected: str, actual: str) -> bool:
    expected_number = _decimal(expected)
    actual_number = _decimal(actual)
    if expected_number is not None and actual_number is not None:
        return expected_number == actual_number
    return _text(expected) == _text(actual)


def _strict_equal(expected: BenchmarkField, actual: BenchmarkField) -> bool:
    return (
        _comparator(expected.comparator) == _comparator(actual.comparator)
        and _text(expected.value) == _text(actual.value)
        and _unit(expected.unit) == _unit(actual.unit)
    )


def _numeric_equal(expected: BenchmarkField, actual: BenchmarkField) -> bool:
    return (
        _comparator(expected.comparator) == _comparator(actual.comparator)
        and _numeric_value_equal(expected.value, actual.value)
        and _unit(expected.unit) == _unit(actual.unit)
    )


def _score_report(gold: GoldReport, prediction: PredictionReport) -> tuple[ReportScore, tuple[BenchmarkError, ...]]:
    gold_by_code = {field.field_code: field for field in gold.fields}
    predicted_by_code = {field.field_code: field for field in prediction.fields}
    matched_codes = sorted(set(gold_by_code) & set(predicted_by_code))
    missing_codes = sorted(set(gold_by_code) - set(predicted_by_code))
    extra_codes = sorted(set(predicted_by_code) - set(gold_by_code))
    strict_correct = numeric_correct = unit_errors = comparator_errors = reference_errors = 0
    errors: list[BenchmarkError] = []
    for code in matched_codes:
        expected = gold_by_code[code]
        actual = predicted_by_code[code]
        strict = _strict_equal(expected, actual)
        numeric = _numeric_equal(expected, actual)
        strict_correct += int(strict)
        numeric_correct += int(numeric)
        comparator_mismatch = _comparator(expected.comparator) != _comparator(actual.comparator)
        unit_mismatch = _unit(expected.unit) != _unit(actual.unit)
        reference_mismatch = _text(expected.reference_interval) != _text(actual.reference_interval)
        comparator_errors += int(comparator_mismatch)
        unit_errors += int(unit_mismatch)
        reference_errors += int(reference_mismatch)
        if not strict:
            if comparator_mismatch:
                category = "decimal_sign_or_comparison_symbol_error"
            elif _text(actual.value) == _text(expected.reference_interval) and expected.reference_interval:
                category = "reference_interval_mistaken_for_result"
            elif not _numeric_value_equal(expected.value, actual.value):
                category = "character_or_digit_recognition"
            elif unit_mismatch:
                category = "unit_missing_incorrect_or_unjustifiably_converted"
            else:
                category = "character_or_digit_recognition"
            errors.append(BenchmarkError(gold.report_id, gold.visit_ref, prediction.arm, code, "incorrect_field", category))
        if reference_mismatch:
            errors.append(BenchmarkError(gold.report_id, gold.visit_ref, prediction.arm, code, "reference_interval_error", ""))
    errors.extend(
        BenchmarkError(gold.report_id, gold.visit_ref, prediction.arm, code, "missing_field", "required_field_missed")
        for code in missing_codes
    )
    errors.extend(
        BenchmarkError(
            gold.report_id,
            gold.visit_ref,
            prediction.arm,
            code,
            "unsupported_field",
            "unsupported_or_hallucinated_value",
        )
        for code in extra_codes
    )
    privacy_false_negative = int(
        gold.privacy_gate_expected == "block" and prediction.privacy_gate_decision == "allow"
    )
    privacy_false_positive = int(
        gold.privacy_gate_expected == "allow" and prediction.privacy_gate_decision == "block"
    )
    if privacy_false_negative:
        errors.append(
            BenchmarkError(
                gold.report_id,
                gold.visit_ref,
                prediction.arm,
                "",
                "privacy_gate_false_negative",
                "direct_identifier_privacy_gate_failure",
            )
        )
    exact_report = int(
        len(gold.fields) == len(prediction.fields)
        and strict_correct == len(gold.fields)
        and reference_errors == 0
        and gold.privacy_gate_expected == prediction.privacy_gate_decision
    )
    return (
        ReportScore(
            report_id=gold.report_id,
            gold_fields=len(gold.fields),
            predicted_fields=len(prediction.fields),
            detected_fields=len(matched_codes),
            strict_correct=strict_correct,
            numeric_correct=numeric_correct,
            missing_fields=len(missing_codes),
            unsupported_fields=len(extra_codes),
            unit_errors=unit_errors,
            comparator_errors=comparator_errors,
            reference_interval_errors=reference_errors,
            privacy_gate_challenges=int(gold.privacy_gate_expected == "block"),
            privacy_gate_false_negatives=privacy_false_negative,
            privacy_gate_false_positives=privacy_false_positive,
            exact_report=exact_report,
        ),
        tuple(errors),
    )


def _sum_scores(scores: Sequence[ReportScore]) -> dict[str, int]:
    names = (
        "gold_fields",
        "predicted_fields",
        "detected_fields",
        "strict_correct",
        "numeric_correct",
        "missing_fields",
        "unsupported_fields",
        "unit_errors",
        "comparator_errors",
        "reference_interval_errors",
        "privacy_gate_challenges",
        "privacy_gate_false_negatives",
        "privacy_gate_false_positives",
        "exact_report",
    )
    return {name: sum(getattr(score, name) for score in scores) for name in names}


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _metrics(scores: Sequence[ReportScore]) -> dict[str, float | int]:
    totals = _sum_scores(scores)
    precision = _rate(totals["detected_fields"], totals["predicted_fields"])
    recall = _rate(totals["detected_fields"], totals["gold_fields"])
    f1 = round(2 * precision * recall / (precision + recall), 6) if precision + recall else 0.0
    return {
        "report_count": len(scores),
        "gold_field_count": totals["gold_fields"],
        "predicted_field_count": totals["predicted_fields"],
        "detected_field_count": totals["detected_fields"],
        "strict_correct_count": totals["strict_correct"],
        "numeric_normalized_correct_count": totals["numeric_correct"],
        "missing_field_count": totals["missing_fields"],
        "unsupported_value_count": totals["unsupported_fields"],
        "unit_error_count": totals["unit_errors"],
        "comparator_error_count": totals["comparator_errors"],
        "reference_interval_error_count": totals["reference_interval_errors"],
        "privacy_gate_challenge_count": totals["privacy_gate_challenges"],
        "privacy_gate_false_negative_count": totals["privacy_gate_false_negatives"],
        "privacy_gate_false_positive_count": totals["privacy_gate_false_positives"],
        "exact_report_count": totals["exact_report"],
        "strict_accuracy": _rate(totals["strict_correct"], totals["gold_fields"]),
        "numeric_normalized_accuracy": _rate(totals["numeric_correct"], totals["gold_fields"]),
        "field_detection_precision": precision,
        "field_detection_recall": recall,
        "field_detection_f1": f1,
        "missing_field_rate": _rate(totals["missing_fields"], totals["gold_fields"]),
        "unsupported_value_rate": _rate(totals["unsupported_fields"], totals["predicted_fields"]),
        "unit_error_rate": _rate(totals["unit_errors"], totals["detected_fields"]),
        "comparator_error_rate": _rate(totals["comparator_errors"], totals["detected_fields"]),
        "reference_interval_error_rate": _rate(totals["reference_interval_errors"], totals["detected_fields"]),
        "privacy_gate_false_negative_rate": _rate(
            totals["privacy_gate_false_negatives"], totals["privacy_gate_challenges"]
        ),
        "exact_report_rate": _rate(totals["exact_report"], len(scores)),
    }


_BOOTSTRAP_METRICS = (
    "strict_accuracy",
    "numeric_normalized_accuracy",
    "field_detection_precision",
    "field_detection_recall",
    "field_detection_f1",
    "missing_field_rate",
    "unsupported_value_rate",
    "unit_error_rate",
    "comparator_error_rate",
    "reference_interval_error_rate",
    "privacy_gate_false_negative_rate",
    "exact_report_rate",
)


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _metric_defined(scores: Sequence[ReportScore], metric: str) -> bool:
    totals = _sum_scores(scores)
    if metric in {"strict_accuracy", "numeric_normalized_accuracy", "field_detection_recall", "missing_field_rate"}:
        return totals["gold_fields"] > 0
    if metric in {"field_detection_precision", "unsupported_value_rate"}:
        return totals["predicted_fields"] > 0
    if metric in {"unit_error_rate", "comparator_error_rate", "reference_interval_error_rate"}:
        return totals["detected_fields"] > 0
    if metric == "field_detection_f1":
        return totals["gold_fields"] > 0 or totals["predicted_fields"] > 0
    if metric == "privacy_gate_false_negative_rate":
        return totals["privacy_gate_challenges"] > 0
    return bool(scores)


def _bootstrap_intervals(
    scores: Sequence[ReportScore], *, samples: int, seed: int
) -> dict[str, dict[str, float | None]]:
    if samples < 100 or samples > 100_000:
        raise BenchmarkValidationError("benchmark_bootstrap_samples_invalid")
    if not scores:
        raise BenchmarkValidationError("benchmark_scores_empty")
    clusters: dict[str, list[ReportScore]] = {}
    for score in scores:
        clusters.setdefault(score.report_id, []).append(score)
    report_ids = sorted(clusters)
    randomizer = random.Random(seed)
    distributions = {name: [] for name in _BOOTSTRAP_METRICS}
    for _ in range(samples):
        sampled_ids = [report_ids[randomizer.randrange(len(report_ids))] for _ in range(len(report_ids))]
        sampled = [score for report_id in sampled_ids for score in clusters[report_id]]
        metrics = _metrics(sampled)
        for name in _BOOTSTRAP_METRICS:
            if _metric_defined(sampled, name):
                distributions[name].append(float(metrics[name]))
    return {
        name: (
            {
                "lower": round(_percentile(values, 0.025), 6),
                "upper": round(_percentile(values, 0.975), 6),
            }
            if values
            else {"lower": None, "upper": None}
        )
        for name, values in distributions.items()
    }


def evaluate_benchmark(
    gold: Sequence[GoldReport],
    predictions_by_arm: Mapping[str, Sequence[PredictionReport]],
    *,
    bootstrap_samples: int = 2_000,
    seed: int = 20260831,
) -> tuple[dict[str, object], tuple[BenchmarkError, ...]]:
    gold_by_key = {(report.report_id, report.visit_ref): report for report in gold}
    arm_summaries: dict[str, object] = {}
    score_sets: dict[str, tuple[ReportScore, ...]] = {}
    all_errors: list[BenchmarkError] = []
    for arm, predictions in predictions_by_arm.items():
        prediction_by_key = {(report.report_id, report.visit_ref): report for report in predictions}
        if set(prediction_by_key) != set(gold_by_key):
            raise BenchmarkValidationError("benchmark_prediction_report_coverage_mismatch")
        scores: list[ReportScore] = []
        for key, expected in gold_by_key.items():
            score, errors = _score_report(expected, prediction_by_key[key])
            scores.append(score)
            all_errors.extend(errors)
        score_sets[arm] = tuple(scores)
        arm_seed = seed + int(hashlib.sha256(arm.encode("utf-8")).hexdigest()[:8], 16)
        status_counts = {status: 0 for status in sorted(ALLOWED_PREDICTION_STATUSES)}
        for prediction in predictions:
            status_counts[prediction.status] += 1
        observed_reviews = [item.review_outcome for item in predictions if item.review_outcome is not None]
        arm_summaries[arm] = {
            "metrics": _metrics(scores),
            "confidence_intervals_95": _bootstrap_intervals(scores, samples=bootstrap_samples, seed=arm_seed),
            "availability": {
                "status_counts": status_counts,
                "provider_calls": sum(item.provider_calls for item in predictions),
                "input_tokens": sum(item.input_tokens for item in predictions),
                "output_tokens": sum(item.output_tokens for item in predictions),
                "total_latency_ms": sum(item.latency_ms for item in predictions),
                "total_cost_usd": str(sum((item.cost_usd for item in predictions), Decimal("0"))),
                "review_observed_reports": len(observed_reviews),
                "human_edits": sum(item[0] for item in observed_reviews),
                "human_rejects": sum(item[1] for item in observed_reviews),
                "total_review_time_ms": sum(item[2] for item in observed_reviews),
            },
        }
    comparisons: list[dict[str, object]] = []
    arms = list(predictions_by_arm)
    for first_index, first_arm in enumerate(arms):
        for second_arm in arms[first_index + 1 :]:
            first_scores = score_sets[first_arm]
            second_scores = score_sets[second_arm]
            first_clusters: dict[str, list[ReportScore]] = {}
            second_clusters: dict[str, list[ReportScore]] = {}
            for score in first_scores:
                first_clusters.setdefault(score.report_id, []).append(score)
            for score in second_scores:
                second_clusters.setdefault(score.report_id, []).append(score)
            report_ids = sorted(first_clusters)
            point = float(_metrics(second_scores)["strict_accuracy"]) - float(_metrics(first_scores)["strict_accuracy"])
            randomizer = random.Random(seed + int(hashlib.sha256(f"{first_arm}:{second_arm}".encode()).hexdigest()[:8], 16))
            deltas: list[float] = []
            for _ in range(bootstrap_samples):
                sampled_ids = [report_ids[randomizer.randrange(len(report_ids))] for _ in range(len(report_ids))]
                first_sample = [score for report_id in sampled_ids for score in first_clusters[report_id]]
                second_sample = [score for report_id in sampled_ids for score in second_clusters[report_id]]
                if not _metric_defined(first_sample, "strict_accuracy"):
                    continue
                first_metric = float(_metrics(first_sample)["strict_accuracy"])
                second_metric = float(_metrics(second_sample)["strict_accuracy"])
                deltas.append(second_metric - first_metric)
            comparisons.append(
                {
                    "comparison": f"{second_arm}_minus_{first_arm}",
                    "metric": "strict_accuracy",
                    "absolute_difference": round(point, 6),
                    "confidence_interval_95": {
                        "lower": round(_percentile(deltas, 0.025), 6) if deltas else None,
                        "upper": round(_percentile(deltas, 0.975), 6) if deltas else None,
                    },
                }
            )
    return (
        {
            "schema_version": SUMMARY_SCHEMA_VERSION,
            "normalization_version": NORMALIZATION_VERSION,
            "error_taxonomy_version": ERROR_TAXONOMY_VERSION,
            "bootstrap": {"unit": "report", "samples": bootstrap_samples, "seed": seed},
            "arms": arm_summaries,
            "paired_comparisons": comparisons,
            "reporting_boundary": "SYNTHETIC_METRIC_ENGINE_ONLY_NOT_CLINICAL_VALIDATION",
        },
        tuple(all_errors),
    )
