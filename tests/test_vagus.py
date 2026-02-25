"""Tests for Silence Detector."""

import json
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from pulse.src import vagus, thalamus


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    bf = tmp_path / "thalamus.jsonl"
    sf = tmp_path / "silence-state.json"
    with patch.object(vagus, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(vagus, "_DEFAULT_STATE_FILE", sf), \
         patch.object(thalamus, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(thalamus, "_DEFAULT_BROADCAST_FILE", bf):
        yield tmp_path


class TestSignificanceScoring:
    def test_josh_waking_hours_linear(self):
        # 4 hours into silence during waking = (4-2)/6 = 0.333
        sig = vagus._josh_significance(4.0, datetime(2026, 2, 20, 14, 0))
        assert abs(sig - 0.333) < 0.01

    def test_josh_caps_at_one(self):
        sig = vagus._josh_significance(10.0, datetime(2026, 2, 20, 14, 0))
        assert sig == 1.0

    def test_josh_under_two_hours(self):
        sig = vagus._josh_significance(1.5, datetime(2026, 2, 20, 14, 0))
        assert sig == 0.0

    def test_cron_significance(self):
        assert vagus._cron_significance(3.0) == 0.5
        assert vagus._cron_significance(1.0) == 0.0

    def test_market_significance(self):
        assert vagus._market_significance(2.0) == 0.8
        assert vagus._market_significance(0.5) == 0.0


class TestTimeOfDay:
    def test_josh_sleep_hours_zero(self):
        # 11PM - should be zero
        sig = vagus._josh_significance(5.0, datetime(2026, 2, 20, 23, 30))
        assert sig == 0.0

    def test_josh_early_morning_zero(self):
        sig = vagus._josh_significance(5.0, datetime(2026, 2, 20, 3, 0))
        assert sig == 0.0

    def test_josh_8am_is_waking(self):
        sig = vagus._josh_significance(5.0, datetime(2026, 2, 20, 8, 0))
        assert sig == 0.5


class TestBroadcastWrites:
    def test_broadcasts_at_threshold(self, tmp_state):
        # Set josh timestamp 5 hours ago
        now_ms = int(time.time() * 1000)
        state = {
            "timestamps": {"josh": now_ms - 5 * 3_600_000},
            "broadcast_flags": {}
        }
        vagus._save_state(state)
        
        # Check during waking hours
        silences = vagus.check_silence(now=datetime(2026, 2, 20, 14, 0))
        entries = thalamus.read_by_source("vagus")
        # Josh significance = (5-2)/6 = 0.5, should broadcast
        assert len(entries) >= 1
        assert entries[-1]["data"]["silent_source"] == "josh"

    def test_no_double_broadcast(self, tmp_state):
        now_ms = int(time.time() * 1000)
        state = {
            "timestamps": {"josh": now_ms - 5 * 3_600_000},
            "broadcast_flags": {}
        }
        vagus._save_state(state)
        
        vagus.check_silence(now=datetime(2026, 2, 20, 14, 0))
        vagus.check_silence(now=datetime(2026, 2, 20, 14, 0))
        entries = thalamus.read_by_source("vagus")
        assert len(entries) == 1  # Only once


class TestUpdateTimestamp:
    def test_update_resets_flag(self):
        vagus.update_timestamp("josh")
        state = vagus._load_state()
        assert "josh" in state["timestamps"]
        assert state["broadcast_flags"].get("josh") is False


class TestPressureDelta:
    def test_pressure_from_josh_silence(self, tmp_state):
        now_ms = int(time.time() * 1000)
        state = {
            "timestamps": {"josh": now_ms - 5 * 3_600_000},
            "broadcast_flags": {}
        }
        vagus._save_state(state)
        
        with patch.object(vagus, "check_silence", return_value=[
            {"source": "josh", "duration_hours": 5.0, "duration_ms": 18000000, "significance": 0.5}
        ]):
            pressure = vagus.get_pressure_delta()
            assert "connection" in pressure
