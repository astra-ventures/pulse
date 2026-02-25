"""Tests for PARIETAL — World Model Module."""

import asyncio
import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pulse.src.parietal import (
    Parietal,
    HealthSignal,
    GoalCondition,
    Project,
    Deployment,
    WorldModel,
    SignalResult,
    _eval_condition,
)


@pytest.fixture
def state_dir(tmp_path):
    sd = tmp_path / "state"
    sd.mkdir()
    return sd


@pytest.fixture
def parietal(state_dir):
    return Parietal(state_dir=state_dir)


@pytest.fixture
def workspace(tmp_path):
    """Build a mock workspace with several project types."""
    ws = tmp_path / "workspace"
    ws.mkdir()

    # Python project with logs
    proj_a = ws / "my-bot"
    proj_a.mkdir()
    (proj_a / "pyproject.toml").write_text("[tool.poetry]\nname = 'my-bot'\n")
    logs_a = proj_a / "logs"
    logs_a.mkdir()
    (logs_a / "app.log").write_text("INFO: started\n")
    (proj_a / "README.md").write_text("# My Bot\nA helpful bot.\n")
    (proj_a / "tests").mkdir()

    # Trading bot project
    proj_b = ws / "weather-edge"
    proj_b.mkdir()
    (proj_b / "requirements.txt").write_text("requests\n")
    (proj_b / "README.md").write_text("# Weather Edge\nPolymarket weather prediction trading system.\n")
    logs_b = proj_b / "logs"
    logs_b.mkdir()
    (logs_b / "live-trades.jsonl").write_text('{"trade": "buy"}\n')
    (logs_b / "error.log").write_text("ERROR: timeout\n")

    # Node project
    proj_c = ws / "web-app"
    proj_c.mkdir()
    (proj_c / "package.json").write_text('{"name": "web-app", "description": "A web application"}\n')

    # Cloudflare worker
    proj_d = ws / "api-worker"
    proj_d.mkdir()
    (proj_d / "wrangler.toml").write_text('name = "api-worker"\nroute = "api.example.com/*"\n')
    (proj_d / "package.json").write_text('{"name": "api-worker"}\n')

    # Fly.io app
    proj_e = ws / "voice-agent"
    proj_e.mkdir()
    (proj_e / "fly.toml").write_text('app = "voice-agent"\n[http_service]\n  internal_port = 8080\n')
    (proj_e / "Dockerfile").write_text("FROM node:18\n")

    # Project with goals
    proj_f = ws / "companion"
    proj_f.mkdir()
    (proj_f / "pyproject.toml").write_text("[project]\nname = 'companion'\n")
    (proj_f / "PROJECTS.md").write_text("# Goals\n- [ ] Deploy to production\n- [x] Write tests\n- [ ] Add auth\n")

    # Empty dir — not a project
    (ws / "random-dir").mkdir()

    return ws


# ─── Discovery Tests ──────────────────────────────────────────

class TestDiscovery:
    def test_scan_detects_projects(self, parietal, workspace):
        model = parietal.scan(str(workspace))
        project_names = {p.name for p in model.projects}
        assert "my-bot" in project_names
        assert "weather-edge" in project_names
        assert "web-app" in project_names

    def test_scan_detects_trading_bot(self, parietal, workspace):
        model = parietal.scan(str(workspace))
        trading = [p for p in model.projects if p.type == "trading_bot"]
        assert len(trading) >= 1
        assert trading[0].name == "weather-edge"

    def test_scan_detects_cloudflare_worker(self, parietal, workspace):
        model = parietal.scan(str(workspace))
        cf = [p for p in model.projects if p.type == "cloudflare_worker"]
        assert len(cf) == 1
        assert cf[0].name == "api-worker"

    def test_scan_detects_fly_app(self, parietal, workspace):
        model = parietal.scan(str(workspace))
        fly = [p for p in model.projects if p.type == "fly_app"]
        assert len(fly) == 1
        assert fly[0].name == "voice-agent"

    def test_scan_skips_non_projects(self, parietal, workspace):
        model = parietal.scan(str(workspace))
        names = {p.name for p in model.projects}
        assert "random-dir" not in names

    def test_scan_reads_description(self, parietal, workspace):
        model = parietal.scan(str(workspace))
        bot = [p for p in model.projects if p.name == "my-bot"][0]
        assert "helpful bot" in bot.description.lower()

    def test_scan_increments_discovery_count(self, parietal, workspace):
        assert parietal.discovery_count == 0
        parietal.scan(str(workspace))
        assert parietal.discovery_count == 1
        parietal.scan(str(workspace))
        assert parietal.discovery_count == 2

    def test_scan_nonexistent_workspace(self, parietal, tmp_path):
        model = parietal.scan(str(tmp_path / "does-not-exist"))
        assert len(model.projects) == 0


# ─── Signal Inference Tests ───────────────────────────────────

class TestSignalInference:
    def test_log_file_watchers_generated(self, parietal, workspace):
        model = parietal.scan(str(workspace))
        bot = [p for p in model.projects if p.name == "my-bot"][0]
        log_signals = [s for s in bot.health_signals if s.type == "file_age" and "log" in s.id]
        assert len(log_signals) >= 1

    def test_trading_bot_trade_signals(self, parietal, workspace):
        model = parietal.scan(str(workspace))
        trading = [p for p in model.projects if p.name == "weather-edge"][0]
        trade_signals = [s for s in trading.health_signals if "_trades_" in s.id]
        assert len(trade_signals) >= 1
        assert trade_signals[0].drive_impact == "goals"

    def test_cloudflare_health_endpoint(self, parietal, workspace):
        model = parietal.scan(str(workspace))
        cf = [p for p in model.projects if p.name == "api-worker"][0]
        http_signals = [s for s in cf.health_signals if s.type == "http_health"]
        assert len(http_signals) >= 1
        assert "health" in http_signals[0].target

    def test_fly_health_endpoint(self, parietal, workspace):
        model = parietal.scan(str(workspace))
        fly = [p for p in model.projects if p.name == "voice-agent"][0]
        http_signals = [s for s in fly.health_signals if s.type == "http_health"]
        assert len(http_signals) >= 1
        assert "voice-agent.fly.dev" in http_signals[0].target

    def test_max_sensors_per_project_respected(self, state_dir, workspace):
        p = Parietal(state_dir=state_dir, max_sensors_per_project=2)
        model = p.scan(str(workspace))
        for proj in model.projects:
            assert len(proj.health_signals) <= 2


# ─── File Age Sensor Tests ────────────────────────────────────

class TestFileAgeSensor:
    def test_healthy_recent_file(self, parietal, tmp_path):
        f = tmp_path / "test.log"
        f.write_text("data")
        signal = HealthSignal(
            id="test_log", type="file_age", target=str(f),
            healthy_if="age_hours < 24",
        )
        result = parietal._check_file_age(signal)
        assert result.healthy is True
        assert result.details["age_hours"] < 1

    def test_unhealthy_old_file(self, parietal, tmp_path):
        f = tmp_path / "old.log"
        f.write_text("data")
        # Set mtime to 48 hours ago
        old_time = time.time() - (48 * 3600)
        os.utime(f, (old_time, old_time))
        signal = HealthSignal(
            id="old_log", type="file_age", target=str(f),
            healthy_if="age_hours < 24",
        )
        result = parietal._check_file_age(signal)
        assert result.healthy is False
        assert result.details["age_hours"] > 40

    def test_missing_file(self, parietal):
        signal = HealthSignal(
            id="missing", type="file_age", target="/nonexistent/file.log",
            healthy_if="age_hours < 24",
        )
        result = parietal._check_file_age(signal)
        assert result.healthy is False
        assert result.details["status"] == "missing"


# ─── Git Sensor Tests ────────────────────────────────────────

class TestGitSensor:
    def test_clean_repo(self, parietal, tmp_path):
        signal = HealthSignal(
            id="git_test", type="git_status", target=str(tmp_path),
            healthy_if="no_uncommitted",
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            result = parietal._check_git_status(signal)
            assert result.healthy is True
            assert result.details["has_uncommitted"] is False

    def test_dirty_repo(self, parietal, tmp_path):
        signal = HealthSignal(
            id="git_test", type="git_status", target=str(tmp_path),
            healthy_if="no_uncommitted",
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=" M src/main.py\n", returncode=0)
            result = parietal._check_git_status(signal)
            assert result.healthy is False
            assert result.details["has_uncommitted"] is True


# ─── Weight Update Tests (PLASTICITY feedback) ───────────────

class TestWeightUpdates:
    def test_actionable_increases_weight(self, parietal, workspace):
        parietal.scan(str(workspace))
        # Get first signal
        first_proj = parietal.world_model.projects[0]
        if not first_proj.health_signals:
            pytest.skip("No signals to test")
        sig = first_proj.health_signals[0]
        old_weight = sig.weight
        parietal.update_signal_weight(sig.id, "actionable")
        assert sig.weight == pytest.approx(old_weight + 0.05, abs=0.001)

    def test_noise_decreases_weight(self, parietal, workspace):
        parietal.scan(str(workspace))
        first_proj = parietal.world_model.projects[0]
        if not first_proj.health_signals:
            pytest.skip("No signals to test")
        sig = first_proj.health_signals[0]
        old_weight = sig.weight
        parietal.update_signal_weight(sig.id, "noise")
        assert sig.weight == pytest.approx(old_weight - 0.03, abs=0.001)

    def test_weight_clamps_max(self, parietal, workspace):
        parietal.scan(str(workspace))
        first_proj = parietal.world_model.projects[0]
        if not first_proj.health_signals:
            pytest.skip("No signals to test")
        sig = first_proj.health_signals[0]
        sig.weight = 0.99
        parietal.update_signal_weight(sig.id, "actionable")
        assert sig.weight <= 1.0

    def test_weight_clamps_min(self, parietal, workspace):
        parietal.scan(str(workspace))
        first_proj = parietal.world_model.projects[0]
        if not first_proj.health_signals:
            pytest.skip("No signals to test")
        sig = first_proj.health_signals[0]
        sig.weight = 0.11
        parietal.update_signal_weight(sig.id, "noise")
        assert sig.weight >= 0.1

    def test_weights_persist_to_state(self, state_dir, workspace):
        p1 = Parietal(state_dir=state_dir)
        p1.scan(str(workspace))
        first_proj = p1.world_model.projects[0]
        if not first_proj.health_signals:
            pytest.skip("No signals to test")
        sig = first_proj.health_signals[0]
        p1.update_signal_weight(sig.id, "actionable")
        expected = sig.weight

        # Reload from disk
        p2 = Parietal(state_dir=state_dir)
        assert p2.world_model.signal_weights.get(sig.id) == pytest.approx(expected, abs=0.001)


# ─── Context Output Tests ────────────────────────────────────

class TestContext:
    def test_get_context_structure(self, parietal, workspace):
        parietal.scan(str(workspace))
        ctx = parietal.get_context()
        assert "systems_monitored" in ctx
        assert "unhealthy" in ctx
        assert "healthy" in ctx
        assert "goal_conditions_pending" in ctx
        assert "last_scan" in ctx
        assert isinstance(ctx["systems_monitored"], int)
        assert isinstance(ctx["unhealthy"], list)
        assert isinstance(ctx["healthy"], list)

    def test_get_context_shows_pending_goals(self, parietal, workspace):
        parietal.scan(str(workspace))
        ctx = parietal.get_context()
        # companion project has pending goals
        pending = ctx["goal_conditions_pending"]
        assert any("Deploy" in g or "auth" in g.lower() for g in pending)


# ─── Re-scan Tests ────────────────────────────────────────────

class TestRescan:
    def test_rescan_does_not_duplicate_sensors(self, parietal, workspace):
        parietal.scan(str(workspace))
        sensor_mgr = MagicMock()
        sensor_mgr.add_sensor = MagicMock()
        count1 = parietal.register_sensors(sensor_mgr)
        count2 = parietal.register_sensors(sensor_mgr)
        # Second registration should add 0 since IDs already registered
        assert count2 == 0
        assert count1 > 0

    def test_rescan_updates_world_model(self, parietal, workspace):
        parietal.scan(str(workspace))
        count1 = len(parietal.world_model.projects)
        # Add another project
        new_proj = workspace / "new-thing"
        new_proj.mkdir()
        (new_proj / "pyproject.toml").write_text("[project]\nname = 'new-thing'\n")
        parietal.scan(str(workspace))
        assert len(parietal.world_model.projects) >= count1


# ─── State Isolation Tests ────────────────────────────────────

class TestStateIsolation:
    def test_two_instances_independent(self, tmp_path, workspace):
        sd1 = tmp_path / "state1"
        sd1.mkdir()
        sd2 = tmp_path / "state2"
        sd2.mkdir()

        p1 = Parietal(state_dir=sd1)
        p2 = Parietal(state_dir=sd2)

        p1.scan(str(workspace))
        assert p1.discovery_count == 1
        assert p2.discovery_count == 0
        assert len(p1.world_model.projects) > 0
        assert len(p2.world_model.projects) == 0

    def test_state_files_in_correct_dir(self, state_dir, workspace):
        p = Parietal(state_dir=state_dir)
        p.scan(str(workspace))
        assert (state_dir / "parietal-state.json").exists()


# ─── Goal Condition Tests ─────────────────────────────────────

class TestGoalConditions:
    def test_extract_pending_goals(self, parietal, workspace):
        parietal.scan(str(workspace))
        companion = [p for p in parietal.world_model.projects if p.name == "companion"]
        assert len(companion) == 1
        pending = [g for g in companion[0].goal_conditions if g.status == "pending"]
        assert len(pending) >= 1

    def test_extract_completed_goals(self, parietal, workspace):
        parietal.scan(str(workspace))
        companion = [p for p in parietal.world_model.projects if p.name == "companion"]
        assert len(companion) == 1
        met = [g for g in companion[0].goal_conditions if g.status == "met"]
        assert len(met) >= 1


# ─── Condition Evaluation Tests ───────────────────────────────

class TestEvalCondition:
    def test_less_than(self):
        assert _eval_condition("age_hours < 24", {"age_hours": 12}) is True
        assert _eval_condition("age_hours < 24", {"age_hours": 30}) is False

    def test_greater_than(self):
        assert _eval_condition("age_hours > 10", {"age_hours": 12}) is True

    def test_equals(self):
        assert _eval_condition("status == 200", {"status": 200}) is True
        assert _eval_condition("status == 200", {"status": 500}) is False

    def test_not_equals(self):
        assert _eval_condition("status != 500", {"status": 200}) is True

    def test_missing_variable(self):
        assert _eval_condition("age_hours < 24", {}) is False

    def test_no_uncommitted_special(self):
        assert _eval_condition("no_uncommitted", {"has_uncommitted": False}) is True
        assert _eval_condition("no_uncommitted", {"has_uncommitted": True}) is False


# ─── Serialization Tests ─────────────────────────────────────

class TestSerialization:
    def test_health_signal_roundtrip(self):
        sig = HealthSignal(
            id="test", type="file_age", target="/tmp/test.log",
            healthy_if="age_hours < 24", drive_impact="goals", weight=0.8,
        )
        d = sig.to_dict()
        sig2 = HealthSignal.from_dict(d)
        assert sig2.id == sig.id
        assert sig2.weight == sig.weight

    def test_world_model_roundtrip(self):
        wm = WorldModel(
            projects=[Project(name="test", path="/tmp/test", type="python_project")],
            deployments=[Deployment(name="dep", url="https://example.com/health")],
        )
        d = wm.to_dict()
        wm2 = WorldModel.from_dict(d)
        assert len(wm2.projects) == 1
        assert wm2.projects[0].name == "test"
        assert len(wm2.deployments) == 1


# ─── Sensor Registration Tests ───────────────────────────────

class TestSensorRegistration:
    def test_register_sensors_returns_count(self, parietal, workspace):
        parietal.scan(str(workspace))
        sensor_mgr = MagicMock()
        sensor_mgr.add_sensor = MagicMock()
        count = parietal.register_sensors(sensor_mgr)
        assert count > 0
        assert sensor_mgr.add_sensor.call_count == count

    def test_register_creates_correct_sensor_types(self, parietal, workspace):
        parietal.scan(str(workspace))
        sensor_mgr = MagicMock()
        sensors_added = []
        sensor_mgr.add_sensor = lambda s: sensors_added.append(s)
        parietal.register_sensors(sensor_mgr)

        sensor_names = [s.name for s in sensors_added]
        # Should have file sensors from log watchers
        assert any("parietal.file." in n for n in sensor_names)


# ─── HTTP Sensor Async Tests ─────────────────────────────────

class TestHttpSensor:
    def test_http_sensor_success(self):
        from pulse.src.sensors.parietal_sensors import ParietalHttpSensor
        signal = HealthSignal(
            id="http_test", type="http_health",
            target="https://example.com/health",
            healthy_if="status == 200",
        )
        sensor = ParietalHttpSensor(signal)
        assert sensor.name == "parietal.http.http_test"

    def test_http_sensor_read_error(self):
        from pulse.src.sensors.parietal_sensors import ParietalHttpSensor
        signal = HealthSignal(
            id="http_fail", type="http_health",
            target="https://doesnotexist.invalid/health",
            healthy_if="status == 200",
        )
        sensor = ParietalHttpSensor(signal)
        # Run async read — should return error gracefully
        result = asyncio.run(sensor.read())
        assert result["healthy"] is False
        assert "error" in result


# ─── Max Projects Cap Test ────────────────────────────────────

class TestCaps:
    def test_max_projects_respected(self, tmp_path):
        sd = tmp_path / "state"
        sd.mkdir()
        ws = tmp_path / "workspace"
        ws.mkdir()
        # Create 10 projects
        for i in range(10):
            proj = ws / f"proj-{i}"
            proj.mkdir()
            (proj / "pyproject.toml").write_text(f"[project]\nname = 'proj-{i}'\n")

        p = Parietal(state_dir=sd, max_projects=3)
        model = p.scan(str(ws))
        assert len(model.projects) <= 3


# ─── Get Status Test ──────────────────────────────────────────

class TestGetStatus:
    def test_status_structure(self, parietal, workspace):
        parietal.scan(str(workspace))
        status = parietal.get_status()
        assert "projects" in status
        assert "deployments" in status
        assert "signals" in status
        assert "discovery_count" in status
        assert status["projects"] > 0
        assert status["discovery_count"] == 1
