"""Tests for PINEAL — Nightly Restoration / Synthesis."""

import json
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src import pineal


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    sf = tmp_path / "pineal-state.json"
    synth_dir = tmp_path / "daily-synthesis"
    with patch.object(pineal, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(pineal, "_DEFAULT_STATE_FILE", sf), \
         patch.object(pineal, "_DAILY_SYNTH_DIR", synth_dir):
        yield tmp_path


class TestShouldRun:
    def test_not_deep_night(self):
        assert pineal.should_run("morning", 300) is False

    def test_wrong_loop_count(self):
        assert pineal.should_run("deep_night", 301) is False

    def test_deep_night_correct_loop_no_history(self):
        # No history → last_run=0 → always eligible
        assert pineal.should_run("deep_night", 300) is True

    def test_too_recent(self, tmp_path):
        # Manually set last_run to 1 hour ago → not eligible (needs >6h)
        sf = tmp_path / "pineal-state.json"
        sf.write_text(json.dumps({"last_run": time.time() - 3600, "run_count": 1}))
        assert pineal.should_run("deep_night", 300) is False

    def test_old_enough(self, tmp_path):
        # last_run 8 hours ago → eligible
        sf = tmp_path / "pineal-state.json"
        sf.write_text(json.dumps({"last_run": time.time() - 28800, "run_count": 1}))
        assert pineal.should_run("deep_night", 300) is True


class TestRunRestoration:
    def test_returns_dict(self):
        result = pineal.run_restoration()
        assert isinstance(result, dict)
        assert "date" in result
        assert "shipped_count" in result
        assert "peak_emotion" in result

    def test_updates_state(self, tmp_path):
        pineal.run_restoration()
        sf = tmp_path / "pineal-state.json"
        state = json.loads(sf.read_text())
        assert state["run_count"] == 1
        assert state["last_run"] > 0

    def test_creates_synthesis_file(self, tmp_path):
        result = pineal.run_restoration()
        assert result.get("synthesis_file") is not None
        synth_path = Path(result["synthesis_file"])
        assert synth_path.exists()
        data = json.loads(synth_path.read_text())
        assert "date" in data
        assert "synthesis_text" in data

    def test_calls_endocrine_decay(self):
        mock_endo = MagicMock()
        pineal.run_restoration(endocrine_mod=mock_endo)
        mock_endo.tick.assert_called_once_with(hours=1.0)

    def test_rem_success_fired_on_meaningful_events(self, tmp_path):
        # Inject a hippocampus mod that returns many shipped entries
        mock_hippocampus = MagicMock()
        mock_hippocampus.query_by_date.return_value = [
            {"type": "trigger", "data": {"summary": "shipped something great"}, "time": "01:00:00"},
            {"type": "trigger", "data": {"summary": "deployed new feature"}, "time": "02:00:00"},
            {"type": "trigger", "data": {"summary": "committed and pushed"}, "time": "03:00:00"},
            {"type": "trigger", "data": {"summary": "completed the task"}, "time": "04:00:00"},
        ]
        mock_endo = MagicMock()
        result = pineal.run_restoration(hippocampus_mod=mock_hippocampus, endocrine_mod=mock_endo)
        assert result["meaningful_event_count"] > 3
        mock_endo.apply_event.assert_called_with("rem_success")

    def test_no_rem_success_on_quiet_day(self, tmp_path):
        mock_hippocampus = MagicMock()
        mock_hippocampus.query_by_date.return_value = []
        mock_endo = MagicMock()
        # Use empty tmp_path so real daily memory file doesn't inflate event count
        result = pineal.run_restoration(
            hippocampus_mod=mock_hippocampus,
            endocrine_mod=mock_endo,
            memory_dir=tmp_path,
        )
        assert result["rem_success_fired"] is False

    def test_reads_memory_file(self, tmp_path):
        today = datetime.now().strftime("%Y-%m-%d")
        mem_file = tmp_path / f"{today}.md"
        mem_file.write_text("Today I shipped a great feature and deployed it successfully.")
        result = pineal.run_restoration(memory_dir=tmp_path)
        assert result["shipped_count"] > 0

    def test_graceful_without_modules(self):
        # Should complete without error even with no modules
        result = pineal.run_restoration(
            hippocampus_mod=None,
            engram_mod=None,
            endocrine_mod=None,
        )
        assert result["date"] == datetime.now().strftime("%Y-%m-%d")


class TestGetLastSynthesis:
    def test_empty_when_no_files(self):
        result = pineal.get_last_synthesis()
        assert result == {}

    def test_returns_most_recent(self, tmp_path):
        synth_dir = tmp_path / "daily-synthesis"
        synth_dir.mkdir()
        today = datetime.now().strftime("%Y-%m-%d")
        synth_file = synth_dir / f"{today}.json"
        synth_file.write_text(json.dumps({"date": today, "synthesis_text": "test"}))
        result = pineal.get_last_synthesis()
        assert result.get("date") == today


class TestGetStatus:
    def test_status_fields(self):
        status = pineal.get_status()
        assert "last_run" in status
        assert "hours_since_last_run" in status
        assert "run_count" in status
        assert "ready" in status

    def test_ready_when_never_run(self):
        status = pineal.get_status()
        assert status["ready"] is True
        assert status["run_count"] == 0
