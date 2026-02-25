"""Tests for CEREBELLUM — Habit Automation."""

import json
import time
from pathlib import Path

import pytest

from pulse.src.cerebellum import Cerebellum


@pytest.fixture
def cerebellum(tmp_path, monkeypatch):
    monkeypatch.setattr("pulse.src.cerebellum._DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr("pulse.src.cerebellum._DEFAULT_STATE_FILE", tmp_path / "cerebellum-state.json")
    monkeypatch.setattr("pulse.src.thalamus._DEFAULT_BROADCAST_FILE", tmp_path / "broadcast.jsonl")
    monkeypatch.setattr("pulse.src.thalamus._DEFAULT_STATE_DIR", tmp_path)
    return Cerebellum()


class TestTracking:
    def test_track_execution(self, cerebellum):
        cerebellum.track_execution("weather_check", "abc", "Sunny, 72F", 500)
        assert "weather_check" in cerebellum.state["task_history"]
        assert len(cerebellum.state["task_history"]["weather_check"]) == 1

    def test_history_capped(self, cerebellum):
        for i in range(15):
            cerebellum.track_execution("task", f"h{i}", f"output {i}", 100)
        assert len(cerebellum.state["task_history"]["task"]) == 10


class TestHabitDetection:
    def _add_repetitive(self, cerebellum, task="weather", n=6):
        for i in range(n):
            cerebellum.track_execution(task, f"h{i}", "Sunny, 72F, clear skies", 500)

    def test_detect_with_enough_reps(self, cerebellum):
        self._add_repetitive(cerebellum, n=6)
        habits = cerebellum.detect_habits(min_repetitions=5)
        assert len(habits) == 1
        assert habits[0]["task_name"] == "weather"
        assert habits[0]["similarity"] > 0.85

    def test_no_detect_too_few_reps(self, cerebellum):
        self._add_repetitive(cerebellum, n=3)
        habits = cerebellum.detect_habits(min_repetitions=5)
        assert len(habits) == 0

    def test_no_detect_dissimilar(self, cerebellum):
        outputs = ["Rain 45F fog", "Sunny 90F clear", "Snow -5F blizzard", "Hail 60F wind", "Cloudy 72F humid", "Thunder 55F storm"]
        for i, out in enumerate(outputs):
            cerebellum.track_execution("varied", f"h{i}", out, 500)
        habits = cerebellum.detect_habits(min_repetitions=5)
        assert len(habits) == 0

    def test_auto_graduate_flag(self, cerebellum):
        self._add_repetitive(cerebellum, n=6)
        # Need 3 detect calls to trigger ready_to_graduate
        cerebellum.detect_habits()
        cerebellum.detect_habits()
        habits = cerebellum.detect_habits()
        assert any(h.get("ready_to_graduate") for h in habits)


class TestGraduation:
    def test_graduate_and_check(self, cerebellum):
        path = cerebellum.graduate_task("weather", "#!/bin/bash\necho 'Sunny'")
        assert Path(path).exists()
        use, sp = cerebellum.should_use_habit("weather")
        assert use is True
        assert sp == path

    def test_not_graduated(self, cerebellum):
        use, sp = cerebellum.should_use_habit("nonexistent")
        assert use is False
        assert sp is None


class TestEscalation:
    def test_escalate_removes_graduation(self, cerebellum):
        cerebellum.graduate_task("weather", "#!/bin/bash\necho 'Sunny'")
        cerebellum.escalate("weather", "Unexpected storm")
        use, _ = cerebellum.should_use_habit("weather")
        assert use is False
        assert len(cerebellum.state["escalation_log"]) == 1

    def test_escalate_logs(self, cerebellum):
        cerebellum.escalate("task", "Error occurred")
        assert cerebellum.state["escalation_log"][-1]["reason"] == "Error occurred"


class TestSavings:
    def test_record_and_report(self, cerebellum):
        cerebellum.record_savings(1000)
        cerebellum.record_savings(500)
        report = cerebellum.get_savings_report()
        assert report["tokens_saved_total"] == 1500
        assert report["tokens_saved_today"] == 1500


class TestThalamusIntegration:
    def test_graduation_broadcasts(self, cerebellum, tmp_path):
        cerebellum.graduate_task("weather", "#!/bin/bash\necho 'Sunny'")
        broadcast = tmp_path / "broadcast.jsonl"
        lines = broadcast.read_text().strip().split("\n")
        entry = json.loads(lines[-1])
        assert entry["source"] == "cerebellum"
        assert entry["type"] == "habit_graduated"

    def test_escalation_broadcasts(self, cerebellum, tmp_path):
        cerebellum.escalate("weather", "Unexpected")
        broadcast = tmp_path / "broadcast.jsonl"
        lines = broadcast.read_text().strip().split("\n")
        entry = json.loads(lines[-1])
        assert entry["source"] == "cerebellum"
        assert entry["type"] == "habit_escalated"
