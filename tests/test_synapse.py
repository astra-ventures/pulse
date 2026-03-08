"""Tests for SYNAPSE — Signal Junction & Weighted Inter-Agent Transmission."""

import json
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_tmp_state(tmp_path):
    """Redirect synapse state files to a temp directory."""
    state_file = tmp_path / "synapse-state.json"
    return state_file


def patch_synapse(tmp_path):
    """Context manager: redirect synapse module to use tmp_path for state."""
    from src import synapse
    state_file = tmp_path / "synapse-state.json"
    return (
        patch.object(synapse, "_DEFAULT_STATE_DIR", tmp_path),
        patch.object(synapse, "_DEFAULT_STATE_FILE", state_file),
    )


# ── Transmit ──────────────────────────────────────────────────────────────────

class TestTransmit:
    def test_transmit_creates_connection(self, tmp_path):
        from src import synapse
        patches = patch_synapse(tmp_path)
        with patches[0], patches[1]:
            synapse.reset()
            rec = synapse.transmit("iris", "vera", synapse.EXCITATORY, 0.8)
            assert rec["source"] == "iris"
            assert rec["target"] == "vera"
            assert rec["signal_type"] == synapse.EXCITATORY
            assert rec["strength"] == 0.8

    def test_transmit_effective_strength_scales_with_weight(self, tmp_path):
        from src import synapse
        patches = patch_synapse(tmp_path)
        with patches[0], patches[1]:
            synapse.reset()
            # First fire: weight = 1.0, potentiate → 1.05
            rec = synapse.transmit("a", "b", synapse.EXCITATORY, 0.5)
            # effective = min(1.0, 0.5 * 1.05) = 0.525
            assert rec["effective_strength"] == pytest.approx(0.525, abs=0.01)

    def test_transmit_queues_pending(self, tmp_path):
        from src import synapse
        patches = patch_synapse(tmp_path)
        with patches[0], patches[1]:
            synapse.reset()
            synapse.transmit("iris", "mira", synapse.EXCITATORY, 0.7)
            pending = synapse.receive("mira", clear=False)
            assert len(pending) == 1
            assert pending[0]["source"] == "iris"

    def test_transmit_increments_fired_total(self, tmp_path):
        from src import synapse
        patches = patch_synapse(tmp_path)
        with patches[0], patches[1]:
            synapse.reset()
            synapse.transmit("a", "b")
            synapse.transmit("a", "b")
            stats = synapse.get_stats()
            assert stats["fired_total"] == 2

    def test_transmit_inhibitory_type(self, tmp_path):
        from src import synapse
        patches = patch_synapse(tmp_path)
        with patches[0], patches[1]:
            synapse.reset()
            rec = synapse.transmit("cortex", "hypothalamus", synapse.INHIBITORY, 1.0)
            assert rec["signal_type"] == synapse.INHIBITORY

    def test_transmit_payload_attached(self, tmp_path):
        from src import synapse
        patches = patch_synapse(tmp_path)
        with patches[0], patches[1]:
            synapse.reset()
            rec = synapse.transmit("iris", "vera", payload={"drive": "goals", "delta": 0.3})
            assert rec["payload"]["drive"] == "goals"


# ── Receive ───────────────────────────────────────────────────────────────────

class TestReceive:
    def test_receive_clears_queue(self, tmp_path):
        from src import synapse
        patches = patch_synapse(tmp_path)
        with patches[0], patches[1]:
            synapse.reset()
            synapse.transmit("a", "target")
            signals = synapse.receive("target", clear=True)
            assert len(signals) == 1
            signals_after = synapse.receive("target")
            assert len(signals_after) == 0

    def test_receive_no_clear_keeps_queue(self, tmp_path):
        from src import synapse
        patches = patch_synapse(tmp_path)
        with patches[0], patches[1]:
            synapse.reset()
            synapse.transmit("a", "target")
            signals = synapse.receive("target", clear=False)
            assert len(signals) == 1
            signals_again = synapse.receive("target", clear=False)
            assert len(signals_again) == 1

    def test_receive_only_own_signals(self, tmp_path):
        from src import synapse
        patches = patch_synapse(tmp_path)
        with patches[0], patches[1]:
            synapse.reset()
            synapse.transmit("a", "vera")
            synapse.transmit("a", "mira")
            vera_signals = synapse.receive("vera")
            assert all(s["target"] == "vera" for s in vera_signals)

    def test_receive_empty_when_none(self, tmp_path):
        from src import synapse
        patches = patch_synapse(tmp_path)
        with patches[0], patches[1]:
            synapse.reset()
            signals = synapse.receive("nobody")
            assert signals == []


# ── Weight / Potentiation ─────────────────────────────────────────────────────

class TestWeights:
    def test_get_weight_unknown_connection(self, tmp_path):
        from src import synapse
        patches = patch_synapse(tmp_path)
        with patches[0], patches[1]:
            synapse.reset()
            assert synapse.get_weight("x", "y") == 0.0

    def test_potentiate_increases_weight(self, tmp_path):
        from src import synapse
        patches = patch_synapse(tmp_path)
        with patches[0], patches[1]:
            synapse.reset()
            synapse.transmit("a", "b")  # creates connection at ~1.05
            w0 = synapse.get_weight("a", "b")
            w1 = synapse.potentiate("a", "b", 0.1)
            assert w1 > w0

    def test_weight_capped_at_max(self, tmp_path):
        from src import synapse
        patches = patch_synapse(tmp_path)
        with patches[0], patches[1]:
            synapse.reset()
            synapse.potentiate("a", "b", 999.0)
            assert synapse.get_weight("a", "b") <= synapse.WEIGHT_MAX

    def test_depress_decreases_weight(self, tmp_path):
        from src import synapse
        patches = patch_synapse(tmp_path)
        with patches[0], patches[1]:
            synapse.reset()
            synapse.transmit("a", "b")
            w0 = synapse.get_weight("a", "b")
            w1 = synapse.depress("a", "b", 0.3)
            assert w1 < w0

    def test_weight_floor_at_min(self, tmp_path):
        from src import synapse
        patches = patch_synapse(tmp_path)
        with patches[0], patches[1]:
            synapse.reset()
            synapse.transmit("a", "b")
            synapse.depress("a", "b", 999.0)
            assert synapse.get_weight("a", "b") >= synapse.WEIGHT_MIN

    def test_get_weights_returns_all(self, tmp_path):
        from src import synapse
        patches = patch_synapse(tmp_path)
        with patches[0], patches[1]:
            synapse.reset()
            synapse.transmit("a", "b")
            synapse.transmit("c", "d")
            weights = synapse.get_weights()
            assert "a->b" in weights
            assert "c->d" in weights


# ── Pruning ───────────────────────────────────────────────────────────────────

class TestPruning:
    def test_prune_removes_weak_connections(self, tmp_path):
        from src import synapse
        patches = patch_synapse(tmp_path)
        with patches[0], patches[1]:
            synapse.reset()
            synapse.transmit("a", "b")
            # Force weight very low
            synapse.depress("a", "b", 999.0)  # hits WEIGHT_MIN
            # Manually set below prune threshold
            state = synapse._load_state()
            state["connections"]["a->b"]["weight"] = 0.05  # = PRUNE_THRESHOLD
            synapse._save_state(state)
            pruned = synapse.prune(threshold=0.06)
            assert pruned == 1
            assert synapse.get_weight("a", "b") == 0.0

    def test_prune_keeps_strong_connections(self, tmp_path):
        from src import synapse
        patches = patch_synapse(tmp_path)
        with patches[0], patches[1]:
            synapse.reset()
            synapse.transmit("a", "b")  # weight ~1.05
            pruned = synapse.prune(threshold=0.1)
            assert pruned == 0
            assert synapse.get_weight("a", "b") > 0


# ── Tick (depression) ─────────────────────────────────────────────────────────

class TestTick:
    def test_tick_reduces_idle_weights(self, tmp_path):
        from src import synapse
        patches = patch_synapse(tmp_path)
        with patches[0], patches[1]:
            synapse.reset()
            synapse.transmit("a", "b")
            # Backdate last_fired by 10 hours
            state = synapse._load_state()
            state["connections"]["a->b"]["last_fired"] = time.time() - 36000
            synapse._save_state(state)
            w_before = synapse.get_weight("a", "b")
            synapse.tick(hours=1.0)
            w_after = synapse.get_weight("a", "b")
            assert w_after < w_before

    def test_tick_ignores_never_fired(self, tmp_path):
        from src import synapse
        patches = patch_synapse(tmp_path)
        with patches[0], patches[1]:
            synapse.reset()
            synapse.potentiate("a", "b", 0.0)  # create connection, never fired
            state = synapse._load_state()
            state["connections"]["a->b"]["last_fired"] = None
            synapse._save_state(state)
            # Should not raise
            synapse.tick(hours=1.0)


# ── Stats / Connections ───────────────────────────────────────────────────────

class TestStats:
    def test_stats_initial(self, tmp_path):
        from src import synapse
        patches = patch_synapse(tmp_path)
        with patches[0], patches[1]:
            synapse.reset()
            stats = synapse.get_stats()
            assert stats["connection_count"] == 0
            assert stats["fired_total"] == 0

    def test_get_connections_metadata(self, tmp_path):
        from src import synapse
        patches = patch_synapse(tmp_path)
        with patches[0], patches[1]:
            synapse.reset()
            synapse.transmit("iris", "vera", synapse.EXCITATORY)
            conns = synapse.get_connections()
            assert len(conns) == 1
            assert conns[0]["source"] == "iris"
            assert conns[0]["target"] == "vera"
            assert conns[0]["fire_count"] == 1
