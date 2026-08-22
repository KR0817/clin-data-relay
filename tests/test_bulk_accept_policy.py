from __future__ import annotations

import pytest

from app.bulk_accept_policy import (
    BulkAcceptPolicyError,
    DEFAULT_BULK_ELIGIBLE_SOURCES,
    ITEM_REVIEW_REQUIRED_SOURCES,
    KNOWN_SOURCE_STATUSES,
    evaluate_bulk_accept,
)


def candidate(candidate_id: str, source: str, quality: str = "PASS", **extra: object) -> dict[str, object]:
    return {
        "id": candidate_id,
        "source_status": source,
        "quality_status": quality,
        **extra,
    }


def test_source_taxonomy_requires_an_explicit_decision_for_every_known_source() -> None:
    assert DEFAULT_BULK_ELIGIBLE_SOURCES.isdisjoint(ITEM_REVIEW_REQUIRED_SOURCES)
    assert DEFAULT_BULK_ELIGIBLE_SOURCES | ITEM_REVIEW_REQUIRED_SOURCES == KNOWN_SOURCE_STATUSES


def test_default_bulk_scope_excludes_conflict_kimi_only_and_block() -> None:
    decision = evaluate_bulk_accept(
        [
            candidate("a", "agreement"),
            candidate("l", "local_only"),
            candidate("f", "local_fallback", "WARN"),
            candidate("c", "conflict"),
            candidate("k", "kimi_only"),
            candidate("b", "agreement", "BLOCK"),
        ]
    )

    assert decision.accepted_ids == ("a", "l", "f")
    assert {item.candidate_id: item.reason for item in decision.skipped} == {
        "c": "item_review_required",
        "k": "item_review_required",
        "b": "quality_block",
    }
    assert decision.summary["skipped_by_reason"] == {
        "item_review_required": 2,
        "quality_block": 1,
    }


def test_august_14_composition_accepts_six_not_seventeen_by_default() -> None:
    candidates = [candidate(f"a{index}", "agreement") for index in range(6)]
    candidates += [candidate(f"k{index}", "kimi_only") for index in range(11)]

    decision = evaluate_bulk_accept(candidates)

    assert len(decision.accepted_ids) == 6
    assert len(decision.skipped) == 11
    assert {item.reason for item in decision.skipped} == {"item_review_required"}


@pytest.mark.parametrize(
    ("allowed", "reason", "error"),
    [
        (False, "approved exception", "bulk_override_forbidden"),
        (True, "", "bulk_override_reason_required"),
    ],
)
def test_override_requires_permission_and_a_reason(allowed: bool, reason: str, error: str) -> None:
    with pytest.raises(BulkAcceptPolicyError, match=error):
        evaluate_bulk_accept(
            [candidate("c", "conflict")],
            override_sources=["conflict"],
            override_reason=reason,
            override_allowed=allowed,
        )


def test_override_never_bypasses_block_or_unknown_states() -> None:
    decision = evaluate_bulk_accept(
        [
            candidate("c", "conflict"),
            candidate("b", "conflict", "BLOCK"),
            candidate("u", "unknown"),
        ],
        override_sources=["conflict"],
        override_reason="Documented central review exception.",
        override_allowed=True,
    )

    assert decision.accepted_ids == ("c",)
    assert {item.candidate_id: item.reason for item in decision.skipped} == {
        "b": "quality_block",
        "u": "unknown_source_status",
    }


def test_mutable_state_gates_are_reported_by_the_same_policy() -> None:
    decision = evaluate_bulk_accept(
        [
            candidate("decided", "local_only", candidate_status="human_confirmed"),
            candidate("held", "local_only", transfer_hold=True),
        ]
    )

    assert decision.accepted_ids == ()
    assert decision.summary["skipped_by_reason"] == {
        "candidate_already_decided": 1,
        "transfer_hold_active": 1,
    }
