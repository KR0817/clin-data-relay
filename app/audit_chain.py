"""Tamper-evident SHA-256 chaining for immutable audit event payloads.

This detects modification or deletion after an anchor has left the workstation.
It is not WORM storage and does not prevent a privileged user from rewriting an
unanchored chain.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass


CHAIN_VERSION = "audit-chain-v1"
GENESIS_PREV_HASH = "0" * 64
_HEX_DIGITS = frozenset("0123456789abcdef")


def _validated_hash(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in _HEX_DIGITS for char in value):
        raise ValueError(f"{name}_must_be_lowercase_sha256")
    return value


def canonical_payload(payload: Mapping[str, object]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def compute_event_hash(prev_hash: str, payload: Mapping[str, object]) -> str:
    previous = _validated_hash(prev_hash, "prev_hash")
    material = f"{previous}\n{canonical_payload(payload)}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def event_payload(
    *,
    event_id: str,
    candidate_id: str | None,
    centre_code: str,
    event_type: str,
    actor_username: str,
    created_at: str,
    details: Mapping[str, object],
) -> dict[str, object]:
    """Build the complete immutable payload protected by the chain."""

    return {
        "id": event_id,
        "candidate_id": candidate_id,
        "centre_code": centre_code,
        "event_type": event_type,
        "actor_username": actor_username,
        "created_at": created_at,
        "details": dict(details),
    }


@dataclass(frozen=True)
class ChainVerification:
    ok: bool
    checked: int
    first_break_index: int | None
    reason: str | None
    head_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "version": CHAIN_VERSION,
            "ok": self.ok,
            "checked": self.checked,
            "first_break_index": self.first_break_index,
            "reason": self.reason,
            "head_hash": self.head_hash,
        }


def verify_chain(
    events: Sequence[Mapping[str, object]],
    *,
    expected_head_hash: str | None = None,
) -> ChainVerification:
    previous = GENESIS_PREV_HASH
    for index, event in enumerate(events):
        if event.get("prev_hash") != previous:
            return ChainVerification(False, index, index, "audit_prev_hash_mismatch", previous)
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            return ChainVerification(False, index, index, "audit_payload_missing", previous)
        try:
            recomputed = compute_event_hash(previous, payload)
        except (TypeError, ValueError):
            return ChainVerification(False, index, index, "audit_payload_invalid", previous)
        if event.get("event_hash") != recomputed:
            return ChainVerification(False, index, index, "audit_event_hash_mismatch", previous)
        previous = recomputed

    if expected_head_hash is not None:
        try:
            expected = _validated_hash(expected_head_hash, "expected_head_hash")
        except ValueError:
            return ChainVerification(False, len(events), None, "audit_anchor_invalid", previous)
        if previous != expected:
            return ChainVerification(False, len(events), None, "audit_anchor_mismatch", previous)
    return ChainVerification(True, len(events), None, None, previous)


def build_chain(
    payloads: Iterable[Mapping[str, object]],
    *,
    start_prev_hash: str = GENESIS_PREV_HASH,
) -> list[dict[str, object]]:
    previous = _validated_hash(start_prev_hash, "start_prev_hash")
    chain: list[dict[str, object]] = []
    for payload in payloads:
        digest = compute_event_hash(previous, payload)
        chain.append({"prev_hash": previous, "event_hash": digest, "payload": dict(payload)})
        previous = digest
    return chain


def make_anchor(head_hash: str, event_count: int, generated_at: str) -> dict[str, object]:
    digest = _validated_hash(head_hash, "head_hash")
    count = int(event_count)
    if count < 0:
        raise ValueError("event_count_must_be_nonnegative")
    return {
        "version": CHAIN_VERSION,
        "head_hash": digest,
        "event_count": count,
        "generated_at": str(generated_at),
    }
