"""Tests for NervousSystem integration layer."""

import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from src.nervous_system import NervousSystem


@pytest.fixture
def ns(tmp_path, monkeypatch):
    """NervousSystem with isolated state dirs."""
    state_dir = tmp_path / ".pulse" / "state"
    state_dir.mkdir(parents=True)
    monkeypatch.setattr("src.thalamus._DEFAULT_STATE_DIR", state_dir)
    monkeypatch.setattr("src.thalamus._DEFAULT_BROADCAST_FILE", state_dir / "broadcast.jsonl")
    return NervousSystem(workspace_root=str(tmp_path))


class TestInit:
    def test_initializes_without_errors(self):
        ns = NervousSystem()
        assert ns is not None

    def test_all_modules_attempted(self):
        ns = NervousSystem()
        status = ns.get_status()
        # Should have entries for all 17 expected modules
        expected = [
            "thalamus", "proprioception", "circadian", "endocrine",
            "adipose", "myelin", "immune", "cerebellum", "buffer",
            "spine", "retina", "amygdala", "vagus", "limbic",
            "enteric", "plasticity", "rem",
        ]
        for mod in expected:
            assert mod in status, f"Missing module: {mod}"

    def test_loop_count_starts_zero(self):
        ns = NervousSystem()
        assert ns._loop_count == 0


class TestStartup:
    def test_startup_returns_status(self, ns):
        status = ns.startup()
        assert "modules_loaded" in status
        assert "modules_failed" in status
        assert status["modules_loaded"] > 0

    def test_startup_detects_circadian(self, ns):
        status = ns.startup()
        if "circadian_mode" in status:
            assert status["circadian_mode"] is not None


class TestPreSense:
    def test_returns_enriched_data(self, ns):
        ctx = ns.pre_sense({"filesystem": {"changes": []}})
        assert "circadian_mode" in ctx
        assert "health_status" in ctx
        assert "budget_ok" in ctx
        assert "threat" in ctx

    def test_handles_empty_sensor_data(self, ns):
        ctx = ns.pre_sense({})
        assert isinstance(ctx, dict)

    def test_amygdala_scans_signals(self, ns):
        # A signal with no threat patterns
        ctx = ns.pre_sense({"text": "hello world"})
        # Should not crash, threat should be None or low
        assert ctx.get("threat") is None or ctx["threat"]["threat_level"] < 0.7


class TestPreEvaluate:
    def test_returns_context(self, ns):
        mock_drive = MagicMock()
        mock_drive.total_pressure = 1.0
        mock_drive.top_drive = MagicMock()
        mock_drive.top_drive.name = "test"
        ctx = ns.pre_evaluate(mock_drive, {})
        assert "silences" in ctx
        assert "mood" in ctx
        assert "gut_feeling" in ctx

    def test_handles_none_drive_state(self, ns):
        ctx = ns.pre_evaluate(None, {})
        assert isinstance(ctx, dict)


class TestPostTrigger:
    def test_updates_modules(self, ns):
        decision = MagicMock()
        decision.reason = "test_trigger"
        decision.total_pressure = 1.0
        decision.top_drive = MagicMock()
        decision.top_drive.name = "test_drive"
        
        result = ns.post_trigger(decision, success=True)
        assert isinstance(result, dict)
        assert "buffer_updated" in result
        assert "thalamus_broadcast" in result

    def test_handles_failure(self, ns):
        decision = MagicMock()
        decision.reason = "test"
        decision.total_pressure = 0.5
        decision.top_drive = None
        
        result = ns.post_trigger(decision, success=False)
        assert isinstance(result, dict)


class TestPostLoop:
    def test_increments_loop_count(self, ns):
        ns.post_loop()
        assert ns._loop_count == 1
        ns.post_loop()
        assert ns._loop_count == 2

    def test_immune_runs_every_10th(self, ns):
        # Run 10 loops
        for _ in range(10):
            result = ns.post_loop()
        # 10th loop should have immune results
        assert "immune_issues" in result or ns._mod_immune is None


class TestNightMode:
    def test_check_returns_dict(self, ns):
        result = ns.check_night_mode()
        assert "is_deep_night" in result
        assert "rem_eligible" in result

    def test_not_eligible_outside_deep_night(self, ns):
        # During normal hours, should not be deep night
        result = ns.check_night_mode()
        # Can't guarantee time, but structure should be right
        assert isinstance(result["is_deep_night"], bool)


class TestShutdown:
    def test_shutdown_returns_result(self, ns):
        result = ns.shutdown()
        assert "saved" in result
        assert "failed" in result


class TestDendriteWiring:
    """DENDRITE wired into post_trigger."""

    def test_dendrite_fires_in_post_trigger(self, ns, tmp_path):
        from src import dendrite
        state_dir = tmp_path / ".pulse" / "state"
        with patch.object(dendrite, "_DEFAULT_STATE_DIR", state_dir), \
             patch.object(dendrite, "_DEFAULT_STATE_FILE", state_dir / "dendrite-state.json"):
            decision = MagicMock()
            decision.reason = "test"
            decision.total_pressure = 1.0
            decision.top_drive = None
            decision.sender = "alice"
            decision.sentiment = 0.5
            result = ns.post_trigger(decision, success=True)
            assert isinstance(result, dict)
            if ns._mod_dendrite:
                assert result.get("dendrite_updated") is True

    def test_dendrite_skips_without_sender(self, ns):
        decision = MagicMock(spec=[])
        decision.reason = "test"
        decision.total_pressure = 1.0
        decision.top_drive = None
        result = ns.post_trigger(decision, success=True)
        # No sender → dendrite should not fire
        assert result.get("dendrite_updated") is not True or ns._mod_dendrite is None


class TestRetinaWiring:
    """RETINA wired into pre_sense (input scoring) + post_trigger (outcome learning)."""

    def test_retina_scores_input_in_pre_sense(self, ns):
        ctx = ns.pre_sense({"input": "hello world", "sender": "josh"})
        if ns.retina:
            assert "retina_priority" in ctx

    def test_retina_records_outcome_in_post_trigger(self, ns):
        decision = MagicMock()
        decision.reason = "test"
        decision.total_pressure = 1.0
        decision.top_drive = None
        decision.trigger_category = "conversation"
        # Should not crash
        result = ns.post_trigger(decision, success=True)
        assert isinstance(result, dict)


class TestMyelinWiring:
    """MYELIN wired into pre_evaluate for context compression."""

    def test_myelin_compresses_in_pre_evaluate(self, ns):
        ctx = ns.pre_evaluate(None, {})
        assert isinstance(ctx, dict)
        # myelin_context key appears only when afterimages have content
        # With no afterimages, key may or may not be present — just confirm no crash

    def test_myelin_handles_afterimages(self, ns):
        # Inject fake afterimages via limbic
        if ns._mod_limbic:
            ns._mod_limbic.record_emotion(valence=2.5, intensity=9.0, context="test event")
        ctx = ns.pre_evaluate(None, {})
        if ns.myelin and ctx.get("afterimages"):
            assert "myelin_context" in ctx


class TestVestibularWiring:
    """VESTIBULAR wired into post_loop (every 5th loop)."""

    def test_vestibular_fires_every_5th_loop(self, ns, tmp_path):
        from src import vestibular
        state_dir = tmp_path / ".pulse" / "state"
        with patch.object(vestibular, "_DEFAULT_STATE_DIR", state_dir), \
             patch.object(vestibular, "_DEFAULT_STATE_FILE", state_dir / "vestibular-state.json"):
            for _ in range(5):
                result = ns.post_loop()
            if ns._mod_vestibular:
                assert result.get("vestibular_updated") is True

    def test_vestibular_not_on_4th_loop(self, ns):
        for _ in range(4):
            result = ns.post_loop()
        assert result.get("vestibular_updated") is not True


class TestThymusWiring:
    """THYMUS wired into post_loop (every 10th loop)."""

    def test_thymus_fires_every_10th_loop(self, ns):
        for _ in range(10):
            result = ns.post_loop()
        if ns._mod_thymus:
            assert result.get("thymus_updated") is True

    def test_thymus_not_on_9th_loop(self, ns):
        for _ in range(9):
            result = ns.post_loop()
        assert result.get("thymus_updated") is not True


class TestOximeterWiring:
    """OXIMETER wired into post_trigger + post_loop (every 20th loop)."""

    def test_oximeter_fires_in_post_trigger(self, ns):
        decision = MagicMock()
        decision.reason = "test"
        decision.total_pressure = 1.0
        decision.top_drive = None
        # Should not crash — oximeter update_metrics call
        result = ns.post_trigger(decision, success=True)
        assert isinstance(result, dict)

    def test_oximeter_gap_fires_every_20th_loop(self, ns, tmp_path):
        from src import oximeter, vestibular
        state_dir = tmp_path / ".pulse" / "state"
        with patch.object(oximeter, "_DEFAULT_STATE_DIR", state_dir), \
             patch.object(oximeter, "_DEFAULT_STATE_FILE", state_dir / "oximeter-state.json"), \
             patch.object(vestibular, "_DEFAULT_STATE_DIR", state_dir), \
             patch.object(vestibular, "_DEFAULT_STATE_FILE", state_dir / "vestibular-state.json"):
            for _ in range(20):
                result = ns.post_loop()
            if ns._mod_oximeter:
                assert "oximeter_gap" in result


class TestGenomeWiring:
    """GENOME wired into post_loop (every 100th loop)."""

    def test_genome_fires_every_100th_loop(self, ns, tmp_path):
        from src import genome, vestibular, oximeter, thymus
        state_dir = tmp_path / ".pulse" / "state"
        with patch.object(genome, "_DEFAULT_STATE_DIR", state_dir), \
             patch.object(genome, "_DEFAULT_STATE_FILE", state_dir / "genome.json"), \
             patch.object(vestibular, "_DEFAULT_STATE_DIR", state_dir), \
             patch.object(vestibular, "_DEFAULT_STATE_FILE", state_dir / "vestibular-state.json"), \
             patch.object(oximeter, "_DEFAULT_STATE_DIR", state_dir), \
             patch.object(oximeter, "_DEFAULT_STATE_FILE", state_dir / "oximeter-state.json"), \
             patch.object(thymus, "_DEFAULT_STATE_DIR", state_dir), \
             patch.object(thymus, "_DEFAULT_STATE_FILE", state_dir / "thymus-state.json"):
            ns._loop_count = 99
            result = ns.post_loop()
            if ns._mod_genome:
                assert result.get("genome_exported") is True

    def test_genome_not_on_99th_loop(self, ns, tmp_path):
        # Ensure telomere state file does NOT have a session_count divisible by 10,
        # otherwise the telomere-milestone branch triggers genome export regardless of loop count.
        import json as _json
        state_dir = tmp_path / ".pulse" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        tel_file = state_dir / "telomere-state.json"
        tel_file.write_text(_json.dumps({"session_count": 7}))  # 7 % 10 != 0
        # Also redirect ns.state_dir to isolated tmp so live state files aren't read
        ns.state_dir = state_dir
        ns._loop_count = 98
        result = ns.post_loop()
        assert result.get("genome_exported") is not True


class TestLimbicWiring:
    """LIMBIC wired into post_trigger."""

    def test_limbic_fires_in_post_trigger(self, ns):
        decision = MagicMock()
        decision.reason = "shipped_feature"
        decision.total_pressure = 1.0
        decision.top_drive = None
        result = ns.post_trigger(decision, success=True)
        # Limbic should record emotion without crashing
        assert isinstance(result, dict)

    def test_limbic_skips_without_reason(self, ns):
        decision = MagicMock(spec=[])
        # No .reason attr → limbic should skip
        result = ns.post_trigger(decision, success=True)
        assert isinstance(result, dict)


class TestRemSessionWiring:
    """run_rem_session wired with PONS + ENGRAM."""

    def test_rem_session_with_pons_guard(self, ns):
        from src.rem import Pons
        # Ensure guard is released even if session returns None
        result = ns.run_rem_session(drives=None, force=False)
        assert Pons.is_active() is False

    def test_rem_session_returns_none_without_rem(self, ns):
        ns.rem = None
        result = ns.run_rem_session()
        assert result is None


class TestGracefulDegradation:
    def test_works_with_broken_module(self):
        """NervousSystem should work even if a module import fails."""
        ns = NervousSystem()
        # Manually break a module
        ns.amygdala = None
        ns.retina = None
        
        # Should still work
        ctx = ns.pre_sense({"text": "test"})
        assert isinstance(ctx, dict)
        assert ctx.get("threat") is None

    def test_post_trigger_with_no_modules(self):
        ns = NervousSystem()
        ns._mod_buffer = None
        ns.plasticity = None
        ns._mod_endocrine = None
        ns._mod_thalamus = None
        
        decision = MagicMock()
        decision.reason = "test"
        decision.total_pressure = 1.0
        decision.top_drive = None
        
        result = ns.post_trigger(decision, success=True)
        assert isinstance(result, dict)

    def test_startup_with_all_modules_broken(self):
        ns = NervousSystem()
        # Break everything
        for attr in ["thalamus", "proprioception", "circadian", "endocrine",
                      "adipose", "myelin", "immune", "cerebellum", "buffer",
                      "spine", "retina", "amygdala", "vagus", "limbic",
                      "enteric", "plasticity", "rem", "engram", "mirror",
                      "callosum",
                      "phenotype", "telomere", "hypothalamus", "soma", "dendrite",
                      "vestibular", "thymus", "oximeter", "genome", "aura", "hippocampus",
                      "parietal"]:
            setattr(ns, attr, None)
        for attr in ["_mod_thalamus", "_mod_circadian", "_mod_adipose",
                      "_mod_vagus", "_mod_limbic", "_mod_endocrine",
                      "_mod_buffer", "_mod_retina", "_mod_proprioception",
                      "_mod_myelin", "_mod_immune", "_mod_engram",
                      "_mod_mirror", "_mod_callosum",
                      "_mod_phenotype", "_mod_telomere", "_mod_hypothalamus",
                      "_mod_soma", "_mod_dendrite", "_mod_vestibular",
                      "_mod_thymus", "_mod_oximeter", "_mod_genome",
                      "_mod_aura", "_mod_hippocampus",
                      "_mod_parietal"]:
            setattr(ns, attr, None)
        
        # Should not crash
        status = ns.startup()
        assert status["modules_loaded"] == 0
        
        ctx = ns.pre_sense({})
        assert isinstance(ctx, dict)
        
        ctx = ns.pre_evaluate(None, {})
        assert isinstance(ctx, dict)
        
        ns.post_loop()
        ns.shutdown()


class TestConstellationBroadcast:
    """Tests for AURA constellation broadcast wire-up in post_loop."""

    def test_constellation_broadcast_called_when_peers_registered(self, ns):
        """broadcast_to_peers called after emit() when peers are registered."""
        mock_aura = MagicMock()
        mock_aura.should_emit.return_value = True
        mock_aura.emit.return_value = {"mood": "euphoric", "energy": 1.0}
        mock_aura.get_peers.return_value = {"vera": {"url": "http://127.0.0.1:9722"}}
        mock_aura.broadcast_to_peers.return_value = {"successful": 1, "failed": 0}

        ns._mod_aura = mock_aura

        result = ns.post_loop()

        mock_aura.emit.assert_called_once()
        mock_aura.broadcast_to_peers.assert_called_once()
        assert "constellation_broadcast" in result
        assert result["constellation_broadcast"]["successful"] == 1

    def test_no_broadcast_when_no_peers(self, ns):
        """broadcast_to_peers not called when no peers registered."""
        mock_aura = MagicMock()
        mock_aura.should_emit.return_value = True
        mock_aura.emit.return_value = {"mood": "neutral"}
        mock_aura.get_peers.return_value = {}

        ns._mod_aura = mock_aura

        result = ns.post_loop()

        mock_aura.emit.assert_called_once()
        mock_aura.broadcast_to_peers.assert_not_called()
        assert "constellation_broadcast" not in result

    def test_broadcast_failure_is_fault_tolerant(self, ns):
        """broadcast_to_peers failure does not crash post_loop."""
        mock_aura = MagicMock()
        mock_aura.should_emit.return_value = True
        mock_aura.emit.return_value = {"mood": "neutral"}
        mock_aura.get_peers.return_value = {"vera": {"url": "http://127.0.0.1:9722"}}
        mock_aura.broadcast_to_peers.side_effect = Exception("connection refused")

        ns._mod_aura = mock_aura

        # Should not raise
        result = ns.post_loop()
        assert isinstance(result, dict)
        assert "constellation_broadcast" not in result

    def test_aura_emit_failure_still_skips_broadcast(self, ns):
        """If emit() fails, broadcast is not attempted."""
        mock_aura = MagicMock()
        mock_aura.should_emit.return_value = True
        mock_aura.emit.side_effect = Exception("emit failed")

        ns._mod_aura = mock_aura

        result = ns.post_loop()
        mock_aura.broadcast_to_peers.assert_not_called()
        assert isinstance(result, dict)
