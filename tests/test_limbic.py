"""Tests for Emotional Afterimage."""

import json
import math
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pulse.src import limbic, thalamus


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    bf = tmp_path / "thalamus.jsonl"
    sf = tmp_path / "limbic.json"
    with patch.object(limbic, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(limbic, "_DEFAULT_STATE_FILE", sf), \
         patch.object(thalamus, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(thalamus, "_DEFAULT_BROADCAST_FILE", bf):
        yield tmp_path


class TestCreationThresholds:
    def test_high_intensity_creates(self):
        result = limbic.record_emotion(0.5, 8.0, "test high intensity")
        assert result is not None
        assert result["emotion"] in ("warmth", "joy", "elation", "excitement")

    def test_high_valence_creates(self):
        result = limbic.record_emotion(2.5, 5.0, "test high valence")
        assert result is not None

    def test_negative_valence_creates(self):
        result = limbic.record_emotion(-2.5, 5.0, "test negative valence")
        assert result is not None

    def test_low_intensity_and_valence_skips(self):
        result = limbic.record_emotion(0.5, 3.0, "boring")
        assert result is None

    def test_boundary_no_create(self):
        # Exactly at threshold - should NOT create (need > 7, > 2)
        result = limbic.record_emotion(2.0, 7.0, "boundary")
        assert result is None


class TestDecayMath:
    def test_no_decay_at_creation(self):
        ai = {"intensity": 9.0, "created_at": int(time.time() * 1000), "half_life_ms": 14400000}
        decayed = limbic._decayed_intensity(ai)
        assert abs(decayed - 9.0) < 0.1

    def test_half_life_decay(self):
        now = int(time.time() * 1000)
        ai = {"intensity": 8.0, "created_at": now - 14400000, "half_life_ms": 14400000}
        decayed = limbic._decayed_intensity(ai, now)
        assert abs(decayed - 4.0) < 0.1

    def test_two_half_lives(self):
        now = int(time.time() * 1000)
        ai = {"intensity": 8.0, "created_at": now - 28800000, "half_life_ms": 14400000}
        decayed = limbic._decayed_intensity(ai, now)
        assert abs(decayed - 2.0) < 0.1


class TestCleanup:
    def test_faded_afterimages_removed(self):
        # Create an afterimage that's very old
        limbic.record_emotion(1.0, 9.0, "will fade")
        state = limbic._load_state()
        # Backdate it heavily
        state[0]["created_at"] = int(time.time() * 1000) - 200_000_000  # ~55 hours
        limbic._save_state(state)
        
        active = limbic.get_current_afterimages()
        assert len(active) == 0


class TestBroadcastIntegration:
    def test_creation_broadcasts(self):
        limbic.record_emotion(0.0, 9.0, "broadcast test")
        entries = thalamus.read_by_source("limbic")
        assert len(entries) >= 1
        assert entries[-1]["data"]["event"] == "created"

    def test_emotional_color(self):
        limbic.record_emotion(2.5, 9.0, "joyful moment")
        color = limbic.get_emotional_color()
        assert color is not None
        assert "current_intensity" in color

    def test_no_color_when_empty(self):
        assert limbic.get_emotional_color() is None
