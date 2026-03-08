"""Tests for ECHO — Josh Sentiment Feedback Loop."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from src import echo


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    sf = tmp_path / "echo-state.json"
    with patch.object(echo, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(echo, "_DEFAULT_STATE_FILE", sf):
        yield tmp_path


class TestRecordFeedback:
    def test_record_positive(self):
        event = echo.record_feedback(valence=0.8, intensity=0.7, text="great job")
        assert event["valence"] == 0.8
        assert event["intensity"] == 0.7
        assert event["text"] == "great job"
        assert event["source"] == "josh"

    def test_record_negative(self):
        event = echo.record_feedback(valence=-0.4, intensity=0.6, text="fix this")
        assert event["valence"] == -0.4
        assert event["source"] == "josh"

    def test_record_custom_source(self):
        event = echo.record_feedback(valence=0.5, intensity=0.5, text="ok", source="system")
        assert event["source"] == "system"

    def test_persists_to_state(self, tmp_path):
        echo.record_feedback(valence=0.9, intensity=0.8, text="perfect")
        sf = tmp_path / "echo-state.json"
        state = json.loads(sf.read_text())
        assert len(state["events"]) == 1
        assert state["events"][0]["valence"] == 0.9

    def test_trend_updated_after_positive(self):
        echo.record_feedback(valence=0.9, intensity=0.8, text="amazing")
        echo.record_feedback(valence=0.8, intensity=0.7, text="love it")
        status = echo.get_status()
        assert status["trend"] == "improving"

    def test_trend_updated_after_negative(self):
        echo.record_feedback(valence=-0.6, intensity=0.8, text="wrong")
        echo.record_feedback(valence=-0.5, intensity=0.7, text="bad")
        status = echo.get_status()
        assert status["trend"] == "declining"

    def test_text_truncated(self):
        long_text = "x" * 300
        event = echo.record_feedback(valence=0.5, intensity=0.5, text=long_text)
        assert len(event["text"]) <= 200

    def test_fires_endocrine_on_high_praise(self):
        mock_endo = MagicMock()
        echo.record_feedback(valence=0.8, intensity=0.7, text="amazing", endocrine_mod=mock_endo)
        mock_endo.apply_event.assert_any_call("josh_affirming")
        mock_endo.apply_event.assert_any_call("good_conversation_josh")

    def test_fires_cortisol_on_criticism(self):
        mock_endo = MagicMock()
        echo.record_feedback(valence=-0.4, intensity=0.6, text="fix this", endocrine_mod=mock_endo)
        mock_endo.update_hormone.assert_called_once_with("cortisol", 0.2, "josh_critical")

    def test_no_endocrine_call_without_module(self):
        # Should not raise even without endocrine module
        event = echo.record_feedback(valence=0.8, intensity=0.7, text="great", endocrine_mod=None)
        assert event is not None


class TestGetFeedbackTrend:
    def test_empty_returns_baseline(self):
        trend = echo.get_feedback_trend(hours=24)
        assert trend["event_count"] == 0
        assert trend["hours"] == 24
        assert "avg_valence" in trend
        assert "trend" in trend

    def test_trend_with_events(self):
        echo.record_feedback(valence=0.7, intensity=0.8, text="good")
        echo.record_feedback(valence=0.9, intensity=0.9, text="great")
        trend = echo.get_feedback_trend(hours=24)
        assert trend["event_count"] == 2
        assert trend["avg_valence"] > 0.5

    def test_trend_direction_improving(self):
        # Recent events more positive than earlier ones
        echo.record_feedback(valence=0.3, intensity=0.5, text="ok")
        echo.record_feedback(valence=0.9, intensity=0.9, text="excellent")
        trend = echo.get_feedback_trend(hours=24)
        assert trend["trend"] in ("improving", "stable")

    def test_custom_hours_window(self):
        trend = echo.get_feedback_trend(hours=1)
        assert trend["hours"] == 1


class TestGetReinforcementSignal:
    def test_signal_in_range(self):
        sig = echo.get_reinforcement_signal()
        assert -1.0 <= sig <= 1.0

    def test_positive_after_praise(self):
        echo.record_feedback(valence=0.9, intensity=0.9, text="perfect")
        echo.record_feedback(valence=0.8, intensity=0.8, text="love it")
        sig = echo.get_reinforcement_signal()
        assert sig > 0.0

    def test_negative_after_criticism(self):
        echo.record_feedback(valence=-0.8, intensity=0.9, text="wrong")
        echo.record_feedback(valence=-0.6, intensity=0.7, text="bad")
        sig = echo.get_reinforcement_signal()
        assert sig < 0.0


class TestGetStatus:
    def test_status_fields(self):
        status = echo.get_status()
        assert "total_events" in status
        assert "baseline" in status
        assert "trend" in status
        assert "reinforcement_signal" in status

    def test_status_counts(self):
        echo.record_feedback(valence=0.5, intensity=0.5, text="ok")
        echo.record_feedback(valence=0.6, intensity=0.6, text="nice")
        status = echo.get_status()
        assert status["total_events"] == 2
        assert status["events_24h"] == 2
