from __future__ import annotations

from app.audit_chain import GENESIS_PREV_HASH, build_chain, make_anchor, verify_chain


def payload(index: int) -> dict[str, object]:
    return {
        "id": f"event-{index}",
        "candidate_id": f"candidate-{index}",
        "centre_code": "SITE_A",
        "event_type": "candidate_human_confirmed",
        "actor_username": "reviewer@example.test",
        "created_at": f"2026-08-17T00:00:0{index}+00:00",
        "details": {"index": index},
    }


def test_chain_verifies_and_produces_an_external_anchor() -> None:
    chain = build_chain([payload(1), payload(2), payload(3)])

    result = verify_chain(chain)
    anchor = make_anchor(result.head_hash, result.checked, "2026-08-17T01:00:00+00:00")

    assert result.ok is True
    assert result.checked == 3
    assert result.head_hash != GENESIS_PREV_HASH
    assert anchor["event_count"] == 3


def test_chain_locates_payload_tampering_and_middle_deletion() -> None:
    chain = build_chain([payload(1), payload(2), payload(3)])
    tampered = [dict(item) for item in chain]
    tampered[1] = {**tampered[1], "payload": {**tampered[1]["payload"], "event_type": "changed"}}
    deleted = [chain[0], chain[2]]

    tampered_result = verify_chain(tampered)
    deleted_result = verify_chain(deleted)

    assert tampered_result.ok is False
    assert tampered_result.first_break_index == 1
    assert deleted_result.ok is False
    assert deleted_result.first_break_index == 1


def test_external_anchor_detects_a_complete_chain_rewrite() -> None:
    original = build_chain([payload(1), payload(2)])
    rewritten = build_chain([payload(1), {**payload(2), "details": {"index": 999}}])

    result = verify_chain(rewritten, expected_head_hash=original[-1]["event_hash"])

    assert result.ok is False
    assert result.reason == "audit_anchor_mismatch"
