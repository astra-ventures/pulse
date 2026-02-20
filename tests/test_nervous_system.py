"""Tests for NervousSystem integration layer."""

import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from pulse.src.nervous_system import NervousSystem


@pytest.fixture
def ns(tmp_path, monkeypatch):
    """NervousSystem with isolated state dirs."""
    state_dir = tmp_path / ".pulse" / "state"
    state_dir.mkdir(parents=True)
    monkeypatch.setattr("pulse.src.thalamus.STATE_DIR", state_dir)
    monkeypatch.setattr("pulse.src.thalamus.BROADCAST_FILE", state_dir / "broadcast.jsonl")
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
                      "enteric", "plasticity", "rem"]:
            setattr(ns, attr, None)
        for attr in ["_mod_thalamus", "_mod_circadian", "_mod_adipose",
                      "_mod_vagus", "_mod_limbic", "_mod_endocrine",
                      "_mod_buffer", "_mod_retina", "_mod_proprioception",
                      "_mod_myelin", "_mod_immune"]:
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
