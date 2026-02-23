"""Tests for HYPOTHALAMUS — Meta-Drive Layer."""

import json
import time
from unittest.mock import patch

import pytest

from pulse.src import hypothalamus, thalamus


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    bf = tmp_path / "thalamus.jsonl"
    sf = tmp_path / "hypothalamus-state.json"
    with patch.object(hypothalamus, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(hypothalamus, "_DEFAULT_STATE_FILE", sf), \
         patch.object(thalamus, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(thalamus, "_DEFAULT_BROADCAST_FILE", bf):
        yield tmp_path


class TestNeedSignals:
    def test_single_signal(self):
        result = hypothalamus.record_need_signal("rest", "soma")
        assert result["module_count"] == 1
        assert result["birthed"] is False

    def test_multiple_modules_births_drive(self):
        hypothalamus.record_need_signal("rest", "soma")
        hypothalamus.record_need_signal("rest", "vestibular")
        result = hypothalamus.record_need_signal("rest", "endocrine")
        assert result["birthed"] is True
        drives = hypothalamus.get_active_drives()
        assert "rest" in drives
        assert drives["rest"]["weight"] == 1.0

    def test_same_module_doesnt_double_count(self):
        hypothalamus.record_need_signal("rest", "soma")
        hypothalamus.record_need_signal("rest", "soma")
        result = hypothalamus.record_need_signal("rest", "soma")
        assert result["module_count"] == 1
        assert result["birthed"] is False

    def test_drive_born_broadcast(self):
        hypothalamus.record_need_signal("explore", "telomere")
        hypothalamus.record_need_signal("explore", "adipose")
        hypothalamus.record_need_signal("explore", "spine")
        entries = thalamus.read_by_source("hypothalamus")
        assert any(e["type"] == "drive_born" for e in entries)


class TestScanDrives:
    def test_scan_empty(self):
        result = hypothalamus.scan_drives()
        assert result["active_drives"] == 0

    def test_scan_with_active_drives(self):
        hypothalamus.record_need_signal("rest", "soma")
        hypothalamus.record_need_signal("rest", "vestibular")
        hypothalamus.record_need_signal("rest", "endocrine")
        result = hypothalamus.scan_drives()
        assert result["active_drives"] == 1


class TestReinforce:
    def test_reinforce_drive(self):
        hypothalamus.record_need_signal("rest", "soma")
        hypothalamus.record_need_signal("rest", "vestibular")
        hypothalamus.record_need_signal("rest", "endocrine")
        hypothalamus.reinforce_drive("rest", 0.1)
        drives = hypothalamus.get_active_drives()
        assert drives["rest"]["weight"] == 1.0  # clamped at max


class TestStatus:
    def test_status(self):
        status = hypothalamus.get_status()
        assert "active_drives" in status
        assert "pending_signals" in status


class TestDriveBirthThreshold:
    """Reduced-threshold needs (connection, social) birth at 2 signals;
    regular needs require 3; same module repeated does NOT count."""

    def test_connection_birthed_at_reduced_threshold(self):
        hypothalamus.record_need_signal("connection", "vagus")
        result = hypothalamus.record_need_signal("connection", "endocrine")
        assert result["birthed"] is True

    def test_regular_need_requires_full_threshold(self):
        hypothalamus.record_need_signal("focus", "vagus")
        result = hypothalamus.record_need_signal("focus", "endocrine")
        assert result["birthed"] is False
        result = hypothalamus.record_need_signal("focus", "vestibular")
        assert result["birthed"] is True

    def test_drive_not_birthed_same_module(self):
        hypothalamus.record_need_signal("connection", "endocrine")
        hypothalamus.record_need_signal("connection", "endocrine")
        result = hypothalamus.record_need_signal("connection", "endocrine")
        assert result["birthed"] is False
        assert result["module_count"] == 1


class TestVestibularEmitSignals:
    def test_high_build_ship_ratio_emits(self, tmp_path):
        from pulse.src import vestibular
        sf = tmp_path / "vestibular-state.json"
        with patch.object(vestibular, "_DEFAULT_STATE_DIR", tmp_path), \
             patch.object(vestibular, "_DEFAULT_STATE_FILE", sf):
            state = {
                "counters": {
                    "building": 40, "shipping": 10,
                    "working": 0, "reflecting": 0,
                    "autonomy": 0, "collaboration": 0,
                },
                "imbalances": [],
                "last_check": 0,
            }
            sf.write_text(json.dumps(state))
            result = vestibular.emit_need_signals()
            assert "ship_something" in result

    def test_balanced_emits_nothing(self, tmp_path):
        from pulse.src import vestibular
        sf = tmp_path / "vestibular-state.json"
        with patch.object(vestibular, "_DEFAULT_STATE_DIR", tmp_path), \
             patch.object(vestibular, "_DEFAULT_STATE_FILE", sf):
            state = {
                "counters": {
                    "building": 5, "shipping": 5,
                    "working": 5, "reflecting": 5,
                    "autonomy": 5, "collaboration": 5,
                },
                "imbalances": [],
                "last_check": 0,
            }
            sf.write_text(json.dumps(state))
            result = vestibular.emit_need_signals()
            assert result == {}


class TestEndocrineEmitSignals:
    def test_low_oxytocin_emits_connection(self, tmp_path):
        from pulse.src import endocrine
        sf = tmp_path / "endocrine-state.json"
        with patch.object(endocrine, "_DEFAULT_STATE_DIR", tmp_path), \
             patch.object(endocrine, "_DEFAULT_STATE_FILE", sf):
            state = endocrine._default_state()
            state["hormones"]["oxytocin"] = 0.05
            sf.write_text(json.dumps(state))
            result = endocrine.emit_need_signals()
            assert "connection" in result

    def test_high_cortisol_emits_reduce_stress(self, tmp_path):
        from pulse.src import endocrine
        sf = tmp_path / "endocrine-state.json"
        with patch.object(endocrine, "_DEFAULT_STATE_DIR", tmp_path), \
             patch.object(endocrine, "_DEFAULT_STATE_FILE", sf):
            state = endocrine._default_state()
            state["hormones"]["cortisol"] = 0.8
            sf.write_text(json.dumps(state))
            result = endocrine.emit_need_signals()
            assert "reduce_stress" in result

    def test_normal_hormones_emit_nothing(self, tmp_path):
        from pulse.src import endocrine
        sf = tmp_path / "endocrine-state.json"
        with patch.object(endocrine, "_DEFAULT_STATE_DIR", tmp_path), \
             patch.object(endocrine, "_DEFAULT_STATE_FILE", sf):
            state = endocrine._default_state()
            sf.write_text(json.dumps(state))
            result = endocrine.emit_need_signals()
            assert result == {}


class TestEmitGracefulOnMissingState:
    """Missing state file returns {} gracefully for each emitter."""

    def test_vestibular_missing_state(self, tmp_path):
        from pulse.src import vestibular
        sf = tmp_path / "nonexistent" / "vestibular-state.json"
        with patch.object(vestibular, "_DEFAULT_STATE_FILE", sf):
            result = vestibular.emit_need_signals()
            assert result == {}

    def test_endocrine_missing_state(self, tmp_path):
        from pulse.src import endocrine
        sf = tmp_path / "nonexistent" / "endocrine-state.json"
        with patch.object(endocrine, "_DEFAULT_STATE_FILE", sf):
            result = endocrine.emit_need_signals()
            assert result == {}

    def test_vagus_missing_state(self, tmp_path):
        from pulse.src import vagus
        sf = tmp_path / "nonexistent" / "silence-state.json"
        with patch.object(vagus, "_DEFAULT_STATE_FILE", sf):
            result = vagus.emit_need_signals()
            assert result == {}

    def test_thymus_missing_state(self, tmp_path):
        from pulse.src import thymus
        sf = tmp_path / "nonexistent" / "thymus-state.json"
        with patch.object(thymus, "_DEFAULT_STATE_FILE", sf):
            result = thymus.emit_need_signals()
            assert result == {}

    def test_telomere_missing_state(self, tmp_path):
        from pulse.src import telomere
        sf = tmp_path / "nonexistent" / "telomere-state.json"
        with patch.object(telomere, "_DEFAULT_STATE_FILE", sf):
            result = telomere.emit_need_signals()
            assert result == {}

    def test_adipose_missing_state(self, tmp_path):
        from pulse.src import adipose
        sf = tmp_path / "nonexistent" / "adipose-state.json"
        with patch.object(adipose, "_DEFAULT_STATE_FILE", sf):
            result = adipose.emit_need_signals()
            assert result == {}
