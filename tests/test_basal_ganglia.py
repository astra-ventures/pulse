"""Tests for BASAL_GANGLIA — Live Goal Signal Monitor."""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pulse.src import basal_ganglia


def _make_goals_file(tmp_path, goals: list) -> Path:
    gf = tmp_path if str(tmp_path).endswith("goals.json") else tmp_path / "goals.json"
    gf.parent.mkdir(parents=True, exist_ok=True)
    gf.write_text(json.dumps({"goals": goals}))
    return gf


def _days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    sf = tmp_path / "basal_ganglia-state.json"
    gf = tmp_path / "goals.json"
    with patch.object(basal_ganglia, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(basal_ganglia, "_DEFAULT_STATE_FILE", sf), \
         patch.object(basal_ganglia, "GOALS_FILE", gf):
        yield tmp_path


class TestScanGoals:
    def test_empty_goals_file(self):
        result = basal_ganglia.scan_goals()
        assert result["total"] == 0
        assert result["stale"] == 0

    def test_fresh_goals_not_stale(self, tmp_path):
        _make_goals_file(tmp_path, [
            {"id": "g1", "title": "Build something", "priority": 1,
             "status": "active", "last_updated": datetime.now().strftime("%Y-%m-%d")},
        ])
        result = basal_ganglia.scan_goals()
        assert result["total"] == 1
        assert result["stale"] == 0
        assert result["priority1_stale"] == 0

    def test_p1_goal_stale_emits_signal(self, tmp_path):
        _make_goals_file(tmp_path, [
            {"id": "g1", "title": "Ship revenue", "priority": 1,
             "status": "active", "last_updated": _days_ago(5)},
        ])
        mock_hypo = MagicMock()
        mock_endo = MagicMock()
        result = basal_ganglia.scan_goals(hypothalamus_mod=mock_hypo, endocrine_mod=mock_endo)
        assert result["priority1_stale"] == 1
        mock_hypo.record_need_signal.assert_called_with("goals", "goals_sensor")
        mock_endo.update_hormone.assert_called()


    def test_scan_goals_uses_workspace_root(self, tmp_path):
        workspace = tmp_path / "workspace"
        goals_path = workspace / "memory" / "self" / "goals.json"
        _make_goals_file(goals_path, [
            {"id": "g1", "title": "Workspace goal", "priority": 1,
             "status": "active", "last_updated": _days_ago(5)},
        ])
        result = basal_ganglia.scan_goals(
            hypothalamus_mod=None,
            endocrine_mod=None,
            workspace_root=str(workspace),
        )
        assert result["total"] == 1
        assert result["priority1_stale"] == 1

    def test_general_stale_emits_ship_something(self, tmp_path):
        _make_goals_file(tmp_path, [
            {"id": "g1", "title": "Research project", "priority": 2,
             "status": "active", "last_updated": _days_ago(10)},
        ])
        mock_hypo = MagicMock()
        result = basal_ganglia.scan_goals(hypothalamus_mod=mock_hypo)
        assert result["stale"] == 1
        mock_hypo.record_need_signal.assert_called_with("ship_something", "goals_sensor")

    def test_inactive_goals_ignored(self, tmp_path):
        _make_goals_file(tmp_path, [
            {"id": "g1", "title": "Done thing", "priority": 1,
             "status": "completed", "last_updated": _days_ago(30)},
        ])
        result = basal_ganglia.scan_goals()
        assert result["total"] == 0

    def test_most_urgent_is_stalest_p1(self, tmp_path):
        _make_goals_file(tmp_path, [
            {"id": "g1", "title": "Revenue floor", "priority": 1,
             "status": "active", "last_updated": _days_ago(8)},
            {"id": "g2", "title": "Companion app", "priority": 1,
             "status": "active", "last_updated": _days_ago(4)},
        ])
        result = basal_ganglia.scan_goals()
        assert result["most_urgent"] == "Revenue floor"

    def test_persists_last_scan(self, tmp_path):
        basal_ganglia.scan_goals()
        sf = tmp_path / "basal_ganglia-state.json"
        state = json.loads(sf.read_text())
        assert state["last_scan"] > 0
        assert "last_scan_result" in state

    def test_no_modules_ok(self, tmp_path):
        _make_goals_file(tmp_path, [
            {"id": "g1", "title": "Test goal", "priority": 1,
             "status": "active", "last_updated": _days_ago(5)},
        ])
        # Should not raise without modules
        result = basal_ganglia.scan_goals(hypothalamus_mod=None, endocrine_mod=None)
        assert "total" in result


class TestMarkProgress:
    def test_mark_progress_appends_note(self, tmp_path):
        _make_goals_file(tmp_path, [
            {"id": "goal_001", "title": "Revenue", "priority": 1,
             "status": "active", "last_updated": _days_ago(3), "progress": []},
        ])
        result = basal_ganglia.mark_progress("goal_001", "New trading system deployed")
        assert result is True
        goals = basal_ganglia._load_goals()
        progress = goals[0]["progress"]
        assert len(progress) == 1
        assert "New trading system deployed" in progress[0]

    def test_mark_progress_updates_last_updated(self, tmp_path):
        today = datetime.now().strftime("%Y-%m-%d")
        _make_goals_file(tmp_path, [
            {"id": "goal_001", "title": "Revenue", "priority": 1,
             "status": "active", "last_updated": _days_ago(5), "progress": []},
        ])
        basal_ganglia.mark_progress("goal_001", "Milestone hit")
        goals = basal_ganglia._load_goals()
        assert goals[0]["last_updated"] == today

    def test_mark_progress_unknown_goal(self, tmp_path):
        _make_goals_file(tmp_path, [])
        result = basal_ganglia.mark_progress("nonexistent", "note")
        assert result is False


class TestGetActiveGoals:
    def test_returns_active_only(self, tmp_path):
        _make_goals_file(tmp_path, [
            {"id": "g1", "title": "Active one", "priority": 1,
             "status": "active", "last_updated": datetime.now().strftime("%Y-%m-%d")},
            {"id": "g2", "title": "Done one", "priority": 1,
             "status": "completed", "last_updated": datetime.now().strftime("%Y-%m-%d")},
        ])
        goals = basal_ganglia.get_active_goals()
        assert len(goals) == 1
        assert goals[0]["id"] == "g1"

    def test_filter_by_priority(self, tmp_path):
        _make_goals_file(tmp_path, [
            {"id": "g1", "title": "P1 goal", "priority": 1,
             "status": "active", "last_updated": datetime.now().strftime("%Y-%m-%d")},
            {"id": "g2", "title": "P2 goal", "priority": 2,
             "status": "active", "last_updated": datetime.now().strftime("%Y-%m-%d")},
        ])
        p1_goals = basal_ganglia.get_active_goals(priority=1)
        assert len(p1_goals) == 1
        assert p1_goals[0]["priority"] == 1

    def test_includes_staleness(self, tmp_path):
        _make_goals_file(tmp_path, [
            {"id": "g1", "title": "Old goal", "priority": 1,
             "status": "active", "last_updated": _days_ago(5)},
        ])
        goals = basal_ganglia.get_active_goals()
        assert goals[0]["staleness_days"] >= 5.0

    def test_empty_when_no_goals(self):
        goals = basal_ganglia.get_active_goals()
        assert goals == []


class TestShouldRun:
    def test_runs_at_100(self):
        assert basal_ganglia.should_run(100) is True
        assert basal_ganglia.should_run(200) is True
        assert basal_ganglia.should_run(300) is True

    def test_not_between_100s(self):
        assert basal_ganglia.should_run(50) is False
        assert basal_ganglia.should_run(99) is False
        assert basal_ganglia.should_run(101) is False


class TestGetStatus:
    def test_status_fields(self):
        status = basal_ganglia.get_status()
        assert "last_scan" in status
        assert "hours_since_scan" in status
        assert "last_result" in status
        assert "goals_file_exists" in status

    def test_goals_file_exists_reflects_reality(self, tmp_path):
        status = basal_ganglia.get_status()
        # goals.json was patched to tmp_path/goals.json — doesn't exist yet
        assert status["goals_file_exists"] is False
        _make_goals_file(tmp_path, [])
        status2 = basal_ganglia.get_status()
        assert status2["goals_file_exists"] is True


    def test_status_uses_workspace_root(self, tmp_path):
        workspace = tmp_path / "workspace"
        status = basal_ganglia.get_status(workspace_root=str(workspace))
        assert status["goals_file_exists"] is False
        goals_path = workspace / "memory" / "self" / "goals.json"
        _make_goals_file(goals_path, [])
        status2 = basal_ganglia.get_status(workspace_root=str(workspace))
        assert status2["goals_file_exists"] is True
