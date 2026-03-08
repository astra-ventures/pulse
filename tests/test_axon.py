"""Tests for AXON — Cross-Peer Task Delegation Engine."""

import json
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src import axon


# ── Helpers ────────────────────────────────────────────────────────────────────

FAKE_BEACON = {"instance_id": "iris-main", "host": "localhost", "version": "0.3.4"}
FAKE_PEER_ID = "vera-agent"


def _patch_beacon():
    """Patch pneuma.build_self_beacon to return a stable beacon."""
    return patch("src.axon._pneuma.build_self_beacon", return_value=FAKE_BEACON)


def _sample_delegation(
    drive="goals",
    pressure=0.7,
    priority=axon.PRIORITY_NORMAL,
    ttl=3600,
    sender_id="vera-agent",
    target_peer_id="iris-main",
    offset_secs=0,
) -> dict:
    """Build a minimal inbound delegation dict."""
    import uuid
    return {
        "id": str(uuid.uuid4()),
        "sender_id": sender_id,
        "target_peer_id": target_peer_id,
        "drive": drive,
        "pressure": pressure,
        "priority": priority,
        "payload": {"hint": "focus on launch"},
        "state": axon.STATE_PENDING,
        "created_at": time.time() + offset_secs,
        "expires_at": time.time() + offset_secs + ttl,
        "acked_at": None,
    }


# ── Constants ──────────────────────────────────────────────────────────────────

class TestConstants:
    def test_priority_multipliers_present(self):
        for p in axon.ALL_PRIORITIES:
            assert p in axon.PRIORITY_MULTIPLIERS

    def test_priority_multipliers_in_range(self):
        for v in axon.PRIORITY_MULTIPLIERS.values():
            assert 0.0 <= v <= 1.0

    def test_critical_highest_multiplier(self):
        mults = axon.PRIORITY_MULTIPLIERS
        assert mults[axon.PRIORITY_CRITICAL] >= mults[axon.PRIORITY_HIGH]
        assert mults[axon.PRIORITY_HIGH] >= mults[axon.PRIORITY_NORMAL]
        assert mults[axon.PRIORITY_NORMAL] >= mults[axon.PRIORITY_LOW]


# ── send_delegation (outbox) ───────────────────────────────────────────────────

class TestSendDelegation:
    def test_creates_entry_in_outbox(self, tmp_path):
        with _patch_beacon():
            d = axon.send_delegation(
                drive="goals", pressure=0.8, target_peer_id=FAKE_PEER_ID,
                state_dir=tmp_path,
            )
        assert d["state"] == axon.STATE_PENDING
        assert d["drive"] == "goals"
        assert d["pressure"] == 0.8
        assert d["sender_id"] == FAKE_BEACON["instance_id"]

    def test_delegation_id_is_uuid(self, tmp_path):
        with _patch_beacon():
            d = axon.send_delegation(
                drive="curiosity", pressure=0.5, target_peer_id=FAKE_PEER_ID,
                state_dir=tmp_path,
            )
        import uuid
        uuid.UUID(d["id"])  # raises if not valid UUID

    def test_pressure_clamped(self, tmp_path):
        with _patch_beacon():
            d = axon.send_delegation(
                drive="goals", pressure=5.0, target_peer_id=FAKE_PEER_ID,
                state_dir=tmp_path,
            )
        assert d["pressure"] == 1.0

    def test_pressure_clamped_low(self, tmp_path):
        with _patch_beacon():
            d = axon.send_delegation(
                drive="goals", pressure=-0.5, target_peer_id=FAKE_PEER_ID,
                state_dir=tmp_path,
            )
        assert d["pressure"] == 0.0

    def test_invalid_priority_defaults_to_normal(self, tmp_path):
        with _patch_beacon():
            d = axon.send_delegation(
                drive="goals", pressure=0.5, target_peer_id=FAKE_PEER_ID,
                priority="turbo",
                state_dir=tmp_path,
            )
        assert d["priority"] == axon.PRIORITY_NORMAL

    def test_outbox_persisted(self, tmp_path):
        with _patch_beacon():
            axon.send_delegation(
                drive="goals", pressure=0.6, target_peer_id=FAKE_PEER_ID,
                state_dir=tmp_path,
            )
        outbox = axon.list_outbox(state_dir=tmp_path)
        assert len(outbox) == 1

    def test_multiple_sends_accumulate(self, tmp_path):
        with _patch_beacon():
            for _ in range(3):
                axon.send_delegation(
                    drive="goals", pressure=0.5, target_peer_id=FAKE_PEER_ID,
                    state_dir=tmp_path,
                )
        outbox = axon.list_outbox(state_dir=tmp_path)
        assert len(outbox) == 3


# ── mark_outbox_acked ──────────────────────────────────────────────────────────

class TestMarkOutboxAcked:
    def test_marks_pending_as_acked(self, tmp_path):
        with _patch_beacon():
            d = axon.send_delegation(
                drive="goals", pressure=0.5, target_peer_id=FAKE_PEER_ID,
                state_dir=tmp_path,
            )
        result = axon.mark_outbox_acked(d["id"], state_dir=tmp_path)
        assert result is True
        outbox = axon.list_outbox(state_dir=tmp_path)
        assert outbox[0]["state"] == axon.STATE_ACKED

    def test_returns_false_if_not_found(self, tmp_path):
        result = axon.mark_outbox_acked("nonexistent-id", state_dir=tmp_path)
        assert result is False

    def test_cannot_ack_already_acked(self, tmp_path):
        with _patch_beacon():
            d = axon.send_delegation(
                drive="goals", pressure=0.5, target_peer_id=FAKE_PEER_ID,
                state_dir=tmp_path,
            )
        axon.mark_outbox_acked(d["id"], state_dir=tmp_path)
        result = axon.mark_outbox_acked(d["id"], state_dir=tmp_path)
        assert result is False


# ── cancel_delegation ──────────────────────────────────────────────────────────

class TestCancelDelegation:
    def test_cancels_pending(self, tmp_path):
        with _patch_beacon():
            d = axon.send_delegation(
                drive="goals", pressure=0.5, target_peer_id=FAKE_PEER_ID,
                state_dir=tmp_path,
            )
        result = axon.cancel_delegation(d["id"], state_dir=tmp_path)
        assert result is True
        outbox = axon.list_outbox(state_dir=tmp_path)
        assert outbox[0]["state"] == axon.STATE_CANCELLED

    def test_cannot_cancel_acked(self, tmp_path):
        with _patch_beacon():
            d = axon.send_delegation(
                drive="goals", pressure=0.5, target_peer_id=FAKE_PEER_ID,
                state_dir=tmp_path,
            )
        axon.mark_outbox_acked(d["id"], state_dir=tmp_path)
        result = axon.cancel_delegation(d["id"], state_dir=tmp_path)
        assert result is False


# ── expire_stale_outbox ────────────────────────────────────────────────────────

class TestExpireStaleOutbox:
    def test_expires_past_ttl(self, tmp_path):
        with _patch_beacon():
            d = axon.send_delegation(
                drive="goals", pressure=0.5, target_peer_id=FAKE_PEER_ID,
                ttl=1,  # 1 second TTL
                state_dir=tmp_path,
            )
        time.sleep(1.1)
        count = axon.expire_stale_outbox(state_dir=tmp_path)
        assert count == 1
        outbox = axon.list_outbox(state_dir=tmp_path)
        assert outbox[0]["state"] == axon.STATE_EXPIRED

    def test_does_not_expire_valid(self, tmp_path):
        with _patch_beacon():
            axon.send_delegation(
                drive="goals", pressure=0.5, target_peer_id=FAKE_PEER_ID,
                ttl=3600,
                state_dir=tmp_path,
            )
        count = axon.expire_stale_outbox(state_dir=tmp_path)
        assert count == 0


# ── list_outbox filter ─────────────────────────────────────────────────────────

class TestListOutbox:
    def test_filter_by_state(self, tmp_path):
        with _patch_beacon():
            d = axon.send_delegation(
                drive="goals", pressure=0.5, target_peer_id=FAKE_PEER_ID,
                state_dir=tmp_path,
            )
        axon.cancel_delegation(d["id"], state_dir=tmp_path)
        with _patch_beacon():
            axon.send_delegation(
                drive="curiosity", pressure=0.4, target_peer_id=FAKE_PEER_ID,
                state_dir=tmp_path,
            )
        pending = axon.list_outbox(states=[axon.STATE_PENDING], state_dir=tmp_path)
        cancelled = axon.list_outbox(states=[axon.STATE_CANCELLED], state_dir=tmp_path)
        assert len(pending) == 1
        assert len(cancelled) == 1


# ── receive_delegation (inbox) ─────────────────────────────────────────────────

class TestReceiveDelegation:
    def test_accepts_valid_delegation(self, tmp_path):
        d = _sample_delegation()
        accepted, reason = axon.receive_delegation(d, state_dir=tmp_path)
        assert accepted is True
        inbox = axon.list_inbox(state_dir=tmp_path)
        assert len(inbox) == 1

    def test_rejects_expired(self, tmp_path):
        d = _sample_delegation(ttl=-10)  # already expired
        accepted, reason = axon.receive_delegation(d, state_dir=tmp_path)
        assert accepted is False
        assert "expired" in reason

    def test_rejects_missing_field(self, tmp_path):
        d = _sample_delegation()
        del d["drive"]
        accepted, reason = axon.receive_delegation(d, state_dir=tmp_path)
        assert accepted is False
        assert "missing" in reason

    def test_idempotent_receive(self, tmp_path):
        d = _sample_delegation()
        axon.receive_delegation(d, state_dir=tmp_path)
        accepted, reason = axon.receive_delegation(d, state_dir=tmp_path)
        assert accepted is True
        assert reason == "already received"
        inbox = axon.list_inbox(state_dir=tmp_path)
        assert len(inbox) == 1

    def test_stamps_received_at(self, tmp_path):
        d = _sample_delegation()
        before = time.time()
        axon.receive_delegation(d, state_dir=tmp_path)
        after = time.time()
        inbox = axon.list_inbox(state_dir=tmp_path)
        assert before <= inbox[0]["received_at"] <= after


# ── acknowledge_delegation (inbox) ─────────────────────────────────────────────

class TestAcknowledgeDelegation:
    def test_acks_pending(self, tmp_path):
        d = _sample_delegation()
        axon.receive_delegation(d, state_dir=tmp_path)
        result = axon.acknowledge_delegation(d["id"], state_dir=tmp_path)
        assert result is True
        inbox = axon.list_inbox(state_dir=tmp_path)
        assert inbox[0]["state"] == axon.STATE_ACKED

    def test_cannot_ack_nonexistent(self, tmp_path):
        result = axon.acknowledge_delegation("bad-id", state_dir=tmp_path)
        assert result is False


# ── pop_pending_delegations ────────────────────────────────────────────────────

class TestPopPendingDelegations:
    def test_pops_and_acks(self, tmp_path):
        d = _sample_delegation()
        axon.receive_delegation(d, state_dir=tmp_path)
        popped = axon.pop_pending_delegations(state_dir=tmp_path)
        assert len(popped) == 1
        assert popped[0]["id"] == d["id"]
        # Should be acked in inbox now
        inbox = axon.list_inbox(state_dir=tmp_path)
        assert inbox[0]["state"] == axon.STATE_ACKED

    def test_does_not_pop_already_acked(self, tmp_path):
        d = _sample_delegation()
        axon.receive_delegation(d, state_dir=tmp_path)
        axon.pop_pending_delegations(state_dir=tmp_path)
        popped_again = axon.pop_pending_delegations(state_dir=tmp_path)
        assert len(popped_again) == 0

    def test_skips_expired_during_pop(self, tmp_path):
        d = _sample_delegation(ttl=1)
        axon.receive_delegation(d, state_dir=tmp_path)
        time.sleep(1.1)
        popped = axon.pop_pending_delegations(state_dir=tmp_path)
        assert len(popped) == 0
        inbox = axon.list_inbox(state_dir=tmp_path)
        assert inbox[0]["state"] == axon.STATE_EXPIRED

    def test_multiple_pops(self, tmp_path):
        for _ in range(4):
            axon.receive_delegation(_sample_delegation(), state_dir=tmp_path)
        popped = axon.pop_pending_delegations(state_dir=tmp_path)
        assert len(popped) == 4


# ── compute_injected_pressure ──────────────────────────────────────────────────

class TestComputeInjectedPressure:
    def test_normal_priority(self):
        d = _sample_delegation(pressure=1.0, priority=axon.PRIORITY_NORMAL)
        p = axon.compute_injected_pressure(d)
        assert p == pytest.approx(0.5, abs=0.01)

    def test_critical_priority(self):
        d = _sample_delegation(pressure=1.0, priority=axon.PRIORITY_CRITICAL)
        p = axon.compute_injected_pressure(d)
        assert p == 1.0

    def test_low_priority(self):
        d = _sample_delegation(pressure=1.0, priority=axon.PRIORITY_LOW)
        p = axon.compute_injected_pressure(d)
        assert p == pytest.approx(0.25, abs=0.01)

    def test_clamped_max(self):
        d = _sample_delegation(pressure=0.99, priority=axon.PRIORITY_CRITICAL)
        p = axon.compute_injected_pressure(d)
        assert 0.0 <= p <= 1.0

    def test_missing_priority_defaults(self):
        d = _sample_delegation(pressure=0.8)
        del d["priority"]
        p = axon.compute_injected_pressure(d)
        assert p == pytest.approx(0.4, abs=0.01)  # normal multiplier 0.5


# ── summary ────────────────────────────────────────────────────────────────────

class TestSummary:
    def test_empty_summary(self, tmp_path):
        s = axon.summary(state_dir=tmp_path)
        assert s["inbox_total"] == 0
        assert s["outbox_total"] == 0

    def test_summary_counts(self, tmp_path):
        with _patch_beacon():
            axon.send_delegation(
                drive="goals", pressure=0.5, target_peer_id=FAKE_PEER_ID,
                state_dir=tmp_path,
            )
        axon.receive_delegation(_sample_delegation(), state_dir=tmp_path)
        s = axon.summary(state_dir=tmp_path)
        assert s["outbox_total"] == 1
        assert s["inbox_total"] == 1
        assert axon.STATE_PENDING in s["outbox"]
        assert axon.STATE_PENDING in s["inbox"]
