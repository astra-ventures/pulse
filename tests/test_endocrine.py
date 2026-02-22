"""Tests for ENDOCRINE — Hormonal System / Mood Baseline."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from pulse.src import endocrine, thalamus


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    bf = tmp_path / "thalamus.jsonl"
    sf = tmp_path / "endocrine-state.json"
    with patch.object(endocrine, "STATE_DIR", tmp_path), \
         patch.object(endocrine, "STATE_FILE", sf), \
         patch.object(thalamus, "STATE_DIR", tmp_path), \
         patch.object(thalamus, "BROADCAST_FILE", bf):
        yield tmp_path


class TestHormoneUpdates:
    def test_update_increases(self):
        result = endocrine.update_hormone("cortisol", 0.3, "test")
        assert result["cortisol"] == pytest.approx(0.5, abs=0.01)  # 0.2 default + 0.3

    def test_update_clamps_high(self):
        result = endocrine.update_hormone("dopamine", 1.0, "overflow")
        assert result["dopamine"] == 1.0

    def test_update_clamps_low(self):
        result = endocrine.update_hormone("serotonin", -2.0, "underflow")
        assert result["serotonin"] == 0.0

    def test_unknown_hormone_raises(self):
        with pytest.raises(ValueError):
            endocrine.update_hormone("norepinephrine", 0.5, "nope")


class TestEventApplication:
    def test_shipped_something(self):
        result = endocrine.apply_event("shipped_something")
        # cortisol should decrease, dopamine increase
        assert result["dopamine"] > 0.3  # default 0.3 + 0.4
        assert result["cortisol"] < 0.2  # default 0.2 - 0.3 → clamped to 0

    def test_unknown_event_raises(self):
        with pytest.raises(ValueError):
            endocrine.apply_event("alien_invasion")

    def test_rate_limit_hit(self):
        result = endocrine.apply_event("rate_limit_hit")
        assert result["cortisol"] == pytest.approx(0.5, abs=0.01)

    def test_intimate_conversation(self):
        result = endocrine.apply_event("intimate_conversation")
        assert result["oxytocin"] == pytest.approx(0.6, abs=0.01)


class TestDecay:
    def test_tick_decays_hormones(self):
        # Set high values first
        endocrine.update_hormone("cortisol", 0.5, "setup")
        endocrine.update_hormone("dopamine", 0.5, "setup")
        
        result = endocrine.tick(1.0)
        # cortisol decays -0.05/hr, dopamine -0.08/hr
        assert result["cortisol"] < 0.7
        assert result["dopamine"] < 0.8

    def test_tick_adds_history(self):
        endocrine.tick(1.0)
        state = json.loads((endocrine.STATE_FILE).read_text())
        assert len(state["mood_history"]) == 1

    def test_tick_multiple_hours(self):
        endocrine.update_hormone("cortisol", 0.8, "max it out")
        result = endocrine.tick(10.0)
        # 10 hrs * -0.05 = -0.5 decay
        assert result["cortisol"] < 0.6


class TestMoodLabels:
    def test_euphoric(self):
        endocrine.update_hormone("dopamine", 0.5, "high")
        endocrine.update_hormone("oxytocin", 0.5, "high")
        assert endocrine.get_mood_label() == "euphoric"

    def test_burned_out(self):
        endocrine.update_hormone("cortisol", 0.5, "stressed")
        endocrine.update_hormone("serotonin", -0.5, "low")
        assert endocrine.get_mood_label() == "burned out"

    def test_content(self):
        # serotonin starts at 0.5 (high), cortisol at 0.2 (low)
        assert endocrine.get_mood_label() == "content"

    def test_flat(self):
        for h in ["cortisol", "dopamine", "serotonin", "oxytocin"]:
            endocrine.update_hormone(h, -1.0, "zero")
        assert endocrine.get_mood_label() == "flat"

    def test_wired(self):
        endocrine.update_hormone("cortisol", 0.5, "high")
        endocrine.update_hormone("dopamine", 0.5, "high")
        assert endocrine.get_mood_label() == "wired"

    def test_energized(self):
        endocrine.update_hormone("dopamine", 0.5, "high")
        endocrine.update_hormone("cortisol", -0.2, "low")
        assert endocrine.get_mood_label() == "energized"


class TestMoodInfluence:
    def test_high_cortisol_risk_aversion(self):
        endocrine.update_hormone("cortisol", 0.5, "stressed")
        influence = endocrine.get_mood_influence()
        assert "risk_aversion" in influence

    def test_low_serotonin_reduces_creativity(self):
        endocrine.update_hormone("serotonin", -0.5, "low")
        influence = endocrine.get_mood_influence()
        assert influence.get("creativity", 0) < 0

    def test_high_dopamine_initiative(self):
        endocrine.update_hormone("dopamine", 0.5, "motivated")
        influence = endocrine.get_mood_influence()
        assert "initiative" in influence


class TestGetMood:
    def test_returns_hormones_and_label(self):
        mood = endocrine.get_mood()
        assert "hormones" in mood
        assert "label" in mood
        assert len(mood["hormones"]) == 6


class TestThalamusIntegration:
    def test_significant_shift_broadcasts(self):
        # A 0.4 delta should trigger broadcast
        endocrine.update_hormone("cortisol", 0.4, "big shift")
        entries = thalamus.read_by_source("endocrine")
        assert len(entries) >= 1
        assert entries[-1]["type"] == "mood_update"

    def test_apply_event_broadcasts(self):
        endocrine.apply_event("shipped_something")
        entries = thalamus.read_by_source("endocrine")
        assert len(entries) >= 1
