"""Tests for Pulse v0.3.0 Biosensor Integration.

Tests:
  - BiosensorCache: read, freshness, stale detection, field helpers
  - soma.update_from_biosensors: energy, posture changes
  - endocrine.update_from_biosensors: hormone deltas
  - nervous_system.pre_sense: biosensor block runs without error
"""

import json
import time
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

# ── BiosensorCache tests ─────────────────────────────────────────────────────

class TestBiosensorCache:

    def _make_state(self, hr=72, hr_zone="relaxed", hrv=55, hrv_stress="low",
                    move=400, goal=600, sleep_stage=None, workout_active=False,
                    age_seconds=0) -> dict:
        """Build a synthetic biosensor-state.json dict."""
        ts = time.time() - age_seconds
        return {
            "heart_rate": {"value": hr, "ts": ts, "zone": hr_zone},
            "hrv": {"value": hrv, "ts": ts, "stress_level": hrv_stress},
            "activity": {"move": move, "exercise": 20, "stand": 8,
                         "goal_move": goal, "ts": ts},
            "sleep": {"stage": sleep_stage, "minutes": 90, "ts": ts},
            "workout": {"active": workout_active, "activity": "running", "started": ts},
            "last_update": ts,
        }

    def test_read_returns_none_when_file_missing(self, tmp_path):
        from pulse.src.biosensor_cache import BiosensorCache
        cache = BiosensorCache(state_file=tmp_path / "missing.json")
        cache.invalidate()
        assert cache.read() is None

    def test_read_returns_data_when_fresh(self, tmp_path):
        from pulse.src.biosensor_cache import BiosensorCache
        state_file = tmp_path / "biosensor-state.json"
        data = self._make_state()
        state_file.write_text(json.dumps(data))
        cache = BiosensorCache(state_file=state_file)
        cache.invalidate()
        result = cache.read()
        assert result is not None
        assert result["heart_rate"]["value"] == 72

    def test_read_returns_none_when_stale(self, tmp_path):
        from pulse.src.biosensor_cache import BiosensorCache
        state_file = tmp_path / "biosensor-state.json"
        data = self._make_state(age_seconds=400)  # > 300s max_age
        state_file.write_text(json.dumps(data))
        cache = BiosensorCache(state_file=state_file, max_age_seconds=300)
        cache.invalidate()
        assert cache.read() is None

    def test_read_returns_none_on_invalid_json(self, tmp_path):
        from pulse.src.biosensor_cache import BiosensorCache
        state_file = tmp_path / "biosensor-state.json"
        state_file.write_text("not valid json {{{")
        cache = BiosensorCache(state_file=state_file)
        cache.invalidate()
        assert cache.read() is None

    def test_is_active_true_when_fresh(self, tmp_path):
        from pulse.src.biosensor_cache import BiosensorCache
        state_file = tmp_path / "biosensor-state.json"
        state_file.write_text(json.dumps(self._make_state()))
        cache = BiosensorCache(state_file=state_file)
        cache.invalidate()
        assert cache.is_active() is True

    def test_is_active_false_when_stale(self, tmp_path):
        from pulse.src.biosensor_cache import BiosensorCache
        state_file = tmp_path / "biosensor-state.json"
        state_file.write_text(json.dumps(self._make_state(age_seconds=400)))
        cache = BiosensorCache(state_file=state_file, max_age_seconds=300)
        cache.invalidate()
        assert cache.is_active() is False

    def test_heart_rate_returns_value(self, tmp_path):
        from pulse.src.biosensor_cache import BiosensorCache
        state_file = tmp_path / "biosensor-state.json"
        state_file.write_text(json.dumps(self._make_state(hr=85)))
        cache = BiosensorCache(state_file=state_file)
        cache.invalidate()
        assert cache.heart_rate() == 85

    def test_hr_zone_returns_zone(self, tmp_path):
        from pulse.src.biosensor_cache import BiosensorCache
        state_file = tmp_path / "biosensor-state.json"
        state_file.write_text(json.dumps(self._make_state(hr_zone="elevated")))
        cache = BiosensorCache(state_file=state_file)
        cache.invalidate()
        assert cache.hr_zone() == "elevated"

    def test_hrv_stress_returns_level(self, tmp_path):
        from pulse.src.biosensor_cache import BiosensorCache
        state_file = tmp_path / "biosensor-state.json"
        state_file.write_text(json.dumps(self._make_state(hrv_stress="high")))
        cache = BiosensorCache(state_file=state_file)
        cache.invalidate()
        assert cache.hrv_stress() == "high"

    def test_move_ring_pct_partial(self, tmp_path):
        from pulse.src.biosensor_cache import BiosensorCache
        state_file = tmp_path / "biosensor-state.json"
        state_file.write_text(json.dumps(self._make_state(move=300, goal=600)))
        cache = BiosensorCache(state_file=state_file)
        cache.invalidate()
        pct = cache.move_ring_pct()
        assert pct == pytest.approx(0.5)

    def test_move_ring_pct_closed(self, tmp_path):
        from pulse.src.biosensor_cache import BiosensorCache
        state_file = tmp_path / "biosensor-state.json"
        state_file.write_text(json.dumps(self._make_state(move=650, goal=600)))
        cache = BiosensorCache(state_file=state_file)
        cache.invalidate()
        assert cache.move_ring_pct() == 1.0

    def test_workout_returns_none_when_inactive(self, tmp_path):
        from pulse.src.biosensor_cache import BiosensorCache
        state_file = tmp_path / "biosensor-state.json"
        state_file.write_text(json.dumps(self._make_state(workout_active=False)))
        cache = BiosensorCache(state_file=state_file)
        cache.invalidate()
        assert cache.workout() is None

    def test_workout_returns_dict_when_active(self, tmp_path):
        from pulse.src.biosensor_cache import BiosensorCache
        state_file = tmp_path / "biosensor-state.json"
        state_file.write_text(json.dumps(self._make_state(workout_active=True)))
        cache = BiosensorCache(state_file=state_file)
        cache.invalidate()
        w = cache.workout()
        assert w is not None
        assert w["active"] is True


# ── soma.update_from_biosensors ───────────────────────────────────────────────

class TestSomaBiosensorUpdate:

    def test_returns_empty_when_no_bridge(self, tmp_path):
        from pulse.src import soma
        mock_cache = MagicMock()
        mock_cache.read.return_value = None
        with patch.object(soma, "_DEFAULT_STATE_FILE", tmp_path / "soma-state.json"):
            result = soma.update_from_biosensors(cache=mock_cache)
        assert result == {}

    def test_move_ring_closed_boosts_energy(self, tmp_path):
        from pulse.src import soma
        soma_file = tmp_path / "soma-state.json"
        soma_file.write_text(json.dumps({
            "energy": 0.7, "posture": "neutral", "temperature": "warm",
            "last_update": time.time(), "tokens_spent": 0, "history": []
        }))
        mock_cache = MagicMock()
        mock_cache.read.return_value = {"active": True}
        mock_cache.workout.return_value = None
        mock_cache.move_ring_pct.return_value = 1.0
        mock_cache.sleep.return_value = None
        mock_cache.hr_zone.return_value = "relaxed"
        with patch.object(soma, "_DEFAULT_STATE_FILE", soma_file):
            changes = soma.update_from_biosensors(cache=mock_cache)
        assert "energy" in changes
        updated = json.loads(soma_file.read_text())
        assert updated["energy"] > 0.7

    def test_high_hr_zone_drains_energy(self, tmp_path):
        from pulse.src import soma
        soma_file = tmp_path / "soma-state.json"
        soma_file.write_text(json.dumps({
            "energy": 0.8, "posture": "neutral", "temperature": "warm",
            "last_update": time.time(), "tokens_spent": 0, "history": []
        }))
        mock_cache = MagicMock()
        mock_cache.read.return_value = {"active": True}
        mock_cache.workout.return_value = None
        mock_cache.move_ring_pct.return_value = 0.5
        mock_cache.sleep.return_value = None
        mock_cache.hr_zone.return_value = "high"
        with patch.object(soma, "_DEFAULT_STATE_FILE", soma_file):
            changes = soma.update_from_biosensors(cache=mock_cache)
        updated = json.loads(soma_file.read_text())
        assert updated["energy"] < 0.8

    def test_no_changes_when_all_normal(self, tmp_path):
        from pulse.src import soma
        soma_file = tmp_path / "soma-state.json"
        initial_energy = 0.7
        soma_file.write_text(json.dumps({
            "energy": initial_energy, "posture": "neutral", "temperature": "warm",
            "last_update": time.time(), "tokens_spent": 0, "history": []
        }))
        mock_cache = MagicMock()
        mock_cache.read.return_value = {"active": True}
        mock_cache.workout.return_value = None
        mock_cache.move_ring_pct.return_value = 0.5  # not closed
        mock_cache.sleep.return_value = None
        mock_cache.hr_zone.return_value = "relaxed"  # not high/max
        with patch.object(soma, "_DEFAULT_STATE_FILE", soma_file):
            changes = soma.update_from_biosensors(cache=mock_cache)
        assert changes == {}


# ── endocrine.update_from_biosensors ─────────────────────────────────────────

class TestEndocrineBiosensorUpdate:

    def _make_endo_state(self) -> dict:
        return {
            "hormones": {
                "dopamine": 0.5, "serotonin": 0.5, "oxytocin": 0.3,
                "cortisol": 0.2, "adrenaline": 0.1, "melatonin": 0.0
            },
            "last_update": time.time(),
            "mood_history": [],
        }

    def test_returns_empty_when_no_bridge(self, tmp_path):
        from pulse.src import endocrine
        mock_cache = MagicMock()
        mock_cache.read.return_value = None
        with patch.object(endocrine, "_DEFAULT_STATE_FILE", tmp_path / "endo.json"):
            result = endocrine.update_from_biosensors(cache=mock_cache)
        assert result == {}

    def test_high_hr_zone_raises_adrenaline(self, tmp_path):
        from pulse.src import endocrine
        endo_file = tmp_path / "endo.json"
        endo_file.write_text(json.dumps(self._make_endo_state()))
        mock_cache = MagicMock()
        mock_cache.read.return_value = {"active": True}
        mock_cache.hr_zone.return_value = "high"
        mock_cache.hrv_stress.return_value = "moderate"
        mock_cache.move_ring_pct.return_value = 0.5
        mock_cache.sleep.return_value = None
        with patch.object(endocrine, "_DEFAULT_STATE_FILE", endo_file):
            deltas = endocrine.update_from_biosensors(cache=mock_cache)
        assert "adrenaline" in deltas
        updated = json.loads(endo_file.read_text())
        assert updated["hormones"]["adrenaline"] > 0.1

    def test_low_hrv_stress_lowers_cortisol_raises_serotonin(self, tmp_path):
        from pulse.src import endocrine
        endo_file = tmp_path / "endo.json"
        state = self._make_endo_state()
        state["hormones"]["cortisol"] = 0.5
        endo_file.write_text(json.dumps(state))
        mock_cache = MagicMock()
        mock_cache.read.return_value = {"active": True}
        mock_cache.hr_zone.return_value = "relaxed"
        mock_cache.hrv_stress.return_value = "low"
        mock_cache.move_ring_pct.return_value = 0.5
        mock_cache.sleep.return_value = None
        with patch.object(endocrine, "_DEFAULT_STATE_FILE", endo_file):
            deltas = endocrine.update_from_biosensors(cache=mock_cache)
        updated = json.loads(endo_file.read_text())
        assert updated["hormones"]["cortisol"] < 0.5
        assert updated["hormones"]["serotonin"] > 0.5

    def test_move_ring_closed_boosts_dopamine(self, tmp_path):
        from pulse.src import endocrine
        endo_file = tmp_path / "endo.json"
        endo_file.write_text(json.dumps(self._make_endo_state()))
        mock_cache = MagicMock()
        mock_cache.read.return_value = {"active": True}
        mock_cache.hr_zone.return_value = "moderate"
        mock_cache.hrv_stress.return_value = "moderate"
        mock_cache.move_ring_pct.return_value = 1.0
        mock_cache.sleep.return_value = None
        with patch.object(endocrine, "_DEFAULT_STATE_FILE", endo_file):
            deltas = endocrine.update_from_biosensors(cache=mock_cache)
        assert "dopamine" in deltas
        updated = json.loads(endo_file.read_text())
        assert updated["hormones"]["dopamine"] > 0.5
