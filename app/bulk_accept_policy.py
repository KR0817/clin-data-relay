"""Pure, fail-closed policy for candidate bulk review."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


POLICY_VERSION = "bulk-accept-policy-v1"

KNOWN_SOURCE_STATUSES = frozenset(
    {"agreement", "conflict", "kimi_only", "local_only", "local_fallback"}
)
DEFAULT_BULK_ELIGIBLE_SOURCES = frozenset(
    {"agreement", "local_only", "local_fallback"}
)
ITEM_REVIEW_REQUIRED_SOURCES = frozenset({"conflict", "kimi_only"})
KNOWN_QUALITY_STATUSES = frozenset({"PASS", "WARN", "BLOCK"})

SKIP_ALREADY_DECIDED = "candidate_already_decided"
SKIP_TRANSFER_HOLD = "transfer_hold_active"
SKIP_QUALITY_BLOCK = "quality_block"
SKIP_QUALITY_WARN_EXCLUDED = "quality_warn_excluded"
SKIP_ITEM_REVIEW_REQUIRED = "item_review_required"
SKIP_UNKNOWN_SOURCE_STATUS = "unknown_source_status"
SKIP_UNKNOWN_QUALITY_STATUS = "unknown_quality_status"


class BulkAcceptPolicyError(ValueError):
    """Raised when a caller attempts an invalid policy override."""


@dataclass(frozen=True)
class SkippedCandidate:
    candidate_id: str
    reason: str
    source_status: str
    quality_status: str

    def as_dict(self) -> dict[str, str]:
        return {
            "candidate_id": self.candidate_id,
            "reason": self.reason,
            "source_status": self.source_status,
            "quality_status": self.quality_status,
        }


@dataclass(frozen=True)
class BulkAcceptDecision:
    accepted_ids: tuple[str, ...]
    skipped: tuple[SkippedCandidate, ...]
    summary: dict[str, object]


def evaluate_bulk_accept(
    candidates: Iterable[Mapping[str, object]],
    *,
    include_warn: bool = True,
    override_sources: Iterable[str] = (),
    override_reason: str | None = None,
    override_allowed: bool = False,
) -> BulkAcceptDecision:
    """Return the accepted IDs and stable skip reasons for one request."""

    override = frozenset(str(source) for source in override_sources)
    reason = (override_reason or "").strip()
    if override:
        if not override_allowed:
            raise BulkAcceptPolicyError("bulk_override_forbidden")
        if not reason:
            raise BulkAcceptPolicyError("bulk_override_reason_required")
        if not override <= ITEM_REVIEW_REQUIRED_SOURCES:
            raise BulkAcceptPolicyError("bulk_override_source_invalid")
    eligible_sources = DEFAULT_BULK_ELIGIBLE_SOURCES | override

    accepted: list[str] = []
    skipped: list[SkippedCandidate] = []
    seen: set[str] = set()
    accepted_by_source: dict[str, int] = {}
    skipped_by_reason: dict[str, int] = {}

    for candidate in candidates:
        try:
            candidate_id = str(candidate["id"])
            source_status = str(candidate["source_status"])
            quality_status = str(candidate["quality_status"])
        except KeyError as error:
            raise BulkAcceptPolicyError("bulk_candidate_fields_required") from error
        if candidate_id in seen:
            raise BulkAcceptPolicyError("bulk_candidate_ids_must_be_unique")
        seen.add(candidate_id)

        skip_reason: str | None = None
        if str(candidate.get("candidate_status", "candidate")) != "candidate":
            skip_reason = SKIP_ALREADY_DECIDED
        elif bool(candidate.get("transfer_hold", False)):
            skip_reason = SKIP_TRANSFER_HOLD
        elif quality_status not in KNOWN_QUALITY_STATUSES:
            skip_reason = SKIP_UNKNOWN_QUALITY_STATUS
        elif quality_status == "BLOCK":
            skip_reason = SKIP_QUALITY_BLOCK
        elif quality_status == "WARN" and not include_warn:
            skip_reason = SKIP_QUALITY_WARN_EXCLUDED
        elif source_status not in KNOWN_SOURCE_STATUSES:
            skip_reason = SKIP_UNKNOWN_SOURCE_STATUS
        elif source_status not in eligible_sources:
            skip_reason = SKIP_ITEM_REVIEW_REQUIRED

        if skip_reason is None:
            accepted.append(candidate_id)
            accepted_by_source[source_status] = accepted_by_source.get(source_status, 0) + 1
            continue
        skipped.append(
            SkippedCandidate(
                candidate_id=candidate_id,
                reason=skip_reason,
                source_status=source_status,
                quality_status=quality_status,
            )
        )
        skipped_by_reason[skip_reason] = skipped_by_reason.get(skip_reason, 0) + 1

    summary: dict[str, object] = {
        "policy": POLICY_VERSION,
        "total": len(seen),
        "accepted": len(accepted),
        "skipped": len(skipped),
        "include_warn": include_warn,
        "eligible_sources": sorted(eligible_sources),
        "accepted_by_source": dict(sorted(accepted_by_source.items())),
        "skipped_by_reason": dict(sorted(skipped_by_reason.items())),
        "override": {
            "used": bool(override),
            "sources": sorted(override),
            "reason": reason,
        },
    }
    return BulkAcceptDecision(tuple(accepted), tuple(skipped), summary)
