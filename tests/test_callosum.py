"""Tests for CALLOSUM — Logic-Emotion Bridge."""

import json
import time
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from pulse.src.callosum import (
    BridgeInsight, bridge, get_recent_insights, get_integration_score,
    detect_split, should_run, _load_state, _save_state,
    _calculate_integration, _detect_tension,
)


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    state_file = tmp_path / "callosum-state.json"
    monkeypatch.setattr("pulse.src.callosum.STATE_FILE", state_file)
    monkeypatch.setattr("pulse.src.callosum.STATE_DIR", tmp_path)
    monkeypatch.setattr("pulse.src.callosum.DREAM_DIR", tmp_path / "dreams")
    monkeypatch.setattr("pulse.src.callosum.thalamus", MagicMock())
    yield tmp_path


class TestBridge:
    @patch("pulse.src.callosum._get_logical_state", return_value="processing tasks")
    @patch("pulse.src.callosum._get_emotional_state", return_value=("mood: content", {"label": "content"}))
    @patch("pulse.src.callosum._get_gut_signal", return_value="toward")
    def test_produces_insight(self, mock_gut, mock_emo, mock_logic):
        insight = bridge()
        assert isinstance(insight, BridgeInsight)
        assert insight.logical_state == "processing tasks"
        assert insight.gut_signal == "toward"
        assert 0 <= insight.integration_score <= 1.0

    @patch("pulse.src.callosum._get_logical_state", return_value="shipping feature")
    @patch("pulse.src.callosum._get_emotional_state", return_value=("mood: stressed | cortisol high", {}))
    @patch("pulse.src.callosum._get_gut_signal", return_value="away")
    def test_detects_split(self, mock_gut, mock_emo, mock_logic):
        insight = bridge()
        assert insight.split_detected is True
        assert insight.tension

    @patch("pulse.src.callosum._get_logical_state", return_value="quiet — no recent logical activity")
    @patch("pulse.src.callosum._get_emotional_state", return_value=("mood: content", {}))
    @patch("pulse.src.callosum._get_gut_signal", return_value="neutral")
    def test_no_split_when_aligned(self, mock_gut, mock_emo, mock_logic):
        insight = bridge()
        assert insight.split_detected is False

    @patch("pulse.src.callosum._get_logical_state", return_value="planning")
    @patch("pulse.src.callosum._get_emotional_state", return_value=("mood: calm", {}))
    @patch("pulse.src.callosum._get_gut_signal", return_value="toward")
    def test_saves_to_state(self, mock_gut, mock_emo, mock_logic):
        bridge()
        state = _load_state()
        assert len(state["insights"]) == 1
        assert state["bridge_count"] == 1

    @patch("pulse.src.callosum._get_logical_state", return_value="working")
    @patch("pulse.src.callosum._get_emotional_state", return_value=("mood: ok", {}))
    @patch("pulse.src.callosum._get_gut_signal", return_value="neutral")
    def test_broadcasts_to_thalamus(self, mock_gut, mock_emo, mock_logic):
        import pulse.src.callosum as cal
        bridge()
        cal.thalamus.append.assert_called_once()
        call_data = cal.thalamus.append.call_args[0][0]
        assert call_data["source"] == "callosum"
        assert call_data["type"] == "insight"


class TestGetRecentInsights:
    @patch("pulse.src.callosum._get_logical_state", return_value="x")
    @patch("pulse.src.callosum._get_emotional_state", return_value=("y", {}))
    @patch("pulse.src.callosum._get_gut_signal", return_value="neutral")
    def test_returns_insights(self, *mocks):
        bridge()
        bridge()
        insights = get_recent_insights(5)
        assert len(insights) == 2

    def test_empty_state(self):
        insights = get_recent_insights()
        assert insights == []


class TestIntegrationScore:
    def test_default_score(self):
        score = get_integration_score()
        assert score == 0.5

    def test_score_from_history(self, tmp_path):
        state = _load_state()
        state["integration_history"] = [{"ts": 1, "score": 0.8}, {"ts": 2, "score": 0.6}]
        _save_state(state)
        score = get_integration_score()
        assert abs(score - 0.7) < 0.01


class TestDetectSplit:
    @patch("pulse.src.callosum._get_logical_state", return_value="quiet — no recent logical activity")
    @patch("pulse.src.callosum._get_emotional_state", return_value=("mood: calm", {}))
    @patch("pulse.src.callosum._get_gut_signal", return_value="neutral")
    def test_no_split(self, *mocks):
        assert detect_split() is None

    @patch("pulse.src.callosum._get_logical_state", return_value="active shipping")
    @patch("pulse.src.callosum._get_emotional_state", return_value=("mood: stressed | cortisol", {}))
    @patch("pulse.src.callosum._get_gut_signal", return_value="away")
    def test_split_detected(self, *mocks):
        result = detect_split()
        assert result is not None
        assert "tension" in result
        assert "bridge" in result


class TestShouldRun:
    def test_every_10th(self):
        assert should_run(10) is True
        assert should_run(20) is True
        assert should_run(5) is False
        assert should_run(0) is False


class TestCalculateIntegration:
    def test_positive_alignment(self):
        score = _calculate_integration("active work", "mood: content", "toward")
        assert score > 0.5

    def test_negative_alignment(self):
        score = _calculate_integration("active", "mood: stressed", "away")
        assert score < 0.5


class TestDetectTension:
    def test_gut_away_with_active_logic(self):
        split, tension, _ = _detect_tension("shipping fast", "mood: ok", "away")
        assert split is True

    def test_no_tension_when_quiet(self):
        split, _, _ = _detect_tension("quiet — no recent logical activity", "mood: calm", "neutral")
        assert split is False


class TestBridgeInsightDataclass:
    def test_roundtrip(self):
        bi = BridgeInsight(timestamp=1000, logical_state="x", emotional_state="y",
                          gut_signal="toward", split_detected=False, tension="",
                          bridge="all good", integration_score=0.8)
        d = bi.to_dict()
        bi2 = BridgeInsight.from_dict(d)
        assert bi2.integration_score == 0.8
