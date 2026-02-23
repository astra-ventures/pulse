"""Tests for CIRCADIAN — Internal Clock / Rhythm Awareness."""

import json
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from pulse.src import circadian, thalamus
from pulse.src.circadian import CircadianMode


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    bf = tmp_path / "thalamus.jsonl"
    sf = tmp_path / "circadian-state.json"
    with patch.object(circadian, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(circadian, "_DEFAULT_STATE_FILE", sf), \
         patch.object(thalamus, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(thalamus, "_DEFAULT_BROADCAST_FILE", bf):
        yield tmp_path


class TestModeForTime:
    def test_dawn(self):
        assert circadian.get_mode_for_time(7) == CircadianMode.DAWN

    def test_daylight(self):
        assert circadian.get_mode_for_time(12) == CircadianMode.DAYLIGHT

    def test_golden(self):
        assert circadian.get_mode_for_time(18) == CircadianMode.GOLDEN

    def test_twilight_late(self):
        assert circadian.get_mode_for_time(23) == CircadianMode.TWILIGHT

    def test_twilight_early_morning(self):
        assert circadian.get_mode_for_time(1) == CircadianMode.TWILIGHT

    def test_deep_night(self):
        assert circadian.get_mode_for_time(3) == CircadianMode.DEEP_NIGHT

    def test_boundaries(self):
        assert circadian.get_mode_for_time(6) == CircadianMode.DAWN
        assert circadian.get_mode_for_time(9) == CircadianMode.DAYLIGHT
        assert circadian.get_mode_for_time(17) == CircadianMode.GOLDEN
        assert circadian.get_mode_for_time(22) == CircadianMode.TWILIGHT
        assert circadian.get_mode_for_time(2) == CircadianMode.DEEP_NIGHT


class TestCurrentMode:
    def test_returns_valid_mode(self):
        mode = circadian.get_current_mode()
        assert isinstance(mode, CircadianMode)

    def test_mode_matches_current_hour(self):
        now = datetime.now()
        expected = circadian.get_mode_for_time(now.hour)
        # Without override, should match
        mode = circadian.get_current_mode()
        assert mode == expected


class TestOverride:
    def test_override_changes_mode(self):
        circadian.override_mode("twilight", duration_hours=1.0)
        mode = circadian.get_current_mode()
        assert mode == CircadianMode.TWILIGHT

    def test_override_expires(self):
        circadian.override_mode("twilight", duration_hours=0.0001)
        time.sleep(0.5)
        # After expiry, should return to natural mode
        mode = circadian.get_current_mode()
        expected = circadian.get_mode_for_time(datetime.now().hour)
        assert mode == expected

    def test_override_broadcasts(self):
        circadian.override_mode("deep_night", duration_hours=1.0)
        entries = thalamus.read_by_source("circadian")
        assert any(e["data"].get("override") for e in entries)


class TestSettings:
    def test_get_mode_settings_has_required_keys(self):
        settings = circadian.get_mode_settings()
        assert "retina_threshold" in settings
        assert "tone" in settings
        assert "mode" in settings
        assert "adipose_priority" in settings

    def test_tone_guidance_returns_string(self):
        tone = circadian.get_tone_guidance()
        assert isinstance(tone, str)
        assert len(tone) > 10


class TestJoshHours:
    def test_golden_is_josh_hours(self):
        circadian.override_mode("golden", 1.0)
        assert circadian.is_josh_hours() is True

    def test_daylight_not_josh_hours(self):
        circadian.override_mode("daylight", 1.0)
        assert circadian.is_josh_hours() is False

    def test_twilight_is_josh_hours(self):
        circadian.override_mode("twilight", 1.0)
        assert circadian.is_josh_hours() is True


class TestThalamusIntegration:
    def test_mode_change_broadcasts(self):
        # Force a mode change by calling get_current_mode after clearing state
        circadian.get_current_mode()
        entries = thalamus.read_by_source("circadian")
        # Should have at least one broadcast (initial mode set)
        assert len(entries) >= 1
        assert entries[-1]["type"] == "mode_change"
