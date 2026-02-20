"""Tests for SPINE — System Health Monitor."""
import json
from pathlib import Path

import pytest

from pulse.src import spine, thalamus


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(spine, "STATE_DIR", state_dir)
    monkeypatch.setattr(spine, "HEALTH_FILE", state_dir / "spine-health.json")
    monkeypatch.setattr(thalamus, "STATE_DIR", state_dir)
    monkeypatch.setattr(thalamus, "BROADCAST_FILE", state_dir / "broadcast.jsonl")


class TestTokenUsage:
    def test_green_under_threshold(self):
        result = spine.check_token_usage(10000, 10000, budget_1h=100000)
        assert result["level"] == "green"

    def test_yellow_at_70_pct(self):
        result = spine.check_token_usage(35000, 36000, budget_1h=100000)
        assert result["level"] == "yellow"

    def test_orange_at_85_pct(self):
        result = spine.check_token_usage(43000, 43000, budget_1h=100000)
        assert result["level"] == "orange"

    def test_red_at_95_pct(self):
        result = spine.check_token_usage(48000, 48000, budget_1h=100000)
        assert result["level"] == "red"

    def test_creates_alert(self):
        spine.check_token_usage(48000, 48000, budget_1h=100000)
        alerts = spine.get_alerts()
        assert any(a["source"] == "token_usage" for a in alerts)

    def test_clears_alert_when_green(self):
        spine.check_token_usage(48000, 48000, budget_1h=100000)
        spine.check_token_usage(1000, 1000, budget_1h=100000)
        alerts = spine.get_alerts()
        assert not any(a["source"] == "token_usage" for a in alerts)


class TestContextSize:
    def test_green(self):
        result = spine.check_context_size(50000, 200000)
        assert result["level"] == "green"

    def test_yellow_at_80_pct(self):
        result = spine.check_context_size(165000, 200000)
        assert result["level"] == "yellow"

    def test_orange_at_90_pct(self):
        result = spine.check_context_size(185000, 200000)
        assert result["level"] == "orange"

    def test_red_at_95_pct(self):
        result = spine.check_context_size(196000, 200000)
        assert result["level"] == "red"


class TestCronHealth:
    def test_all_success(self):
        jobs = [{"name": "j1", "success": True}, {"name": "j2", "success": True}]
        result = spine.check_cron_health(jobs)
        assert result["level"] == "green"
        assert result["success_rate"] == 1.0

    def test_empty_jobs(self):
        result = spine.check_cron_health([])
        assert result["level"] == "green"

    def test_yellow_error_rate(self):
        jobs = [{"name": f"j{i}", "success": i < 7} for i in range(10)]
        result = spine.check_cron_health(jobs)
        assert result["level"] == "yellow"

    def test_red_error_rate(self):
        jobs = [{"name": f"j{i}", "success": i < 4} for i in range(10)]
        result = spine.check_cron_health(jobs)
        assert result["level"] == "red"


class TestProviderHealth:
    def test_healthy_provider(self):
        result = spine.check_provider_health("anthropic", 200, True)
        assert result["level"] == "green"

    def test_slow_provider_orange(self):
        result = spine.check_provider_health("anthropic", 6000, True)
        assert result["level"] == "orange"

    def test_very_slow_provider_red(self):
        result = spine.check_provider_health("anthropic", 11000, True)
        assert result["level"] == "red"
        assert result["in_cooldown"] is True

    def test_failing_provider(self):
        # Multiple failures to drop success rate
        for _ in range(5):
            spine.check_provider_health("openai", 200, False)
        result = spine.check_provider_health("openai", 200, False)
        assert result["level"] == "red"
        assert result["in_cooldown"] is True

    def test_tracks_multiple_providers(self):
        spine.check_provider_health("anthropic", 200, True)
        spine.check_provider_health("openai", 300, True)
        state = spine._load()
        assert "anthropic" in state["metrics"]["provider_health"]
        assert "openai" in state["metrics"]["provider_health"]


class TestSelfCorrection:
    def test_orange_pauses_non_essential(self):
        spine.check_context_size(185000, 200000)  # orange
        health = spine.check_health()
        assert "weather_scan" in health["paused_crons"]
        assert "topic_monitor" in health["paused_crons"]

    def test_red_pauses_all(self):
        spine.check_token_usage(48000, 48000, budget_1h=100000)  # red
        health = spine.check_health()
        assert "ALL_EXCEPT_SPINE" in health["paused_crons"]

    def test_green_clears_paused(self):
        spine.check_context_size(185000, 200000)
        spine.check_health()  # pauses crons
        # Clear the alert
        spine.check_context_size(50000, 200000)
        health = spine.check_health()
        assert health["paused_crons"] == []


class TestMetricRecording:
    def test_record_and_read(self):
        spine.record_metric("custom_metric", 42.5)
        state = spine._load()
        assert state["metrics"]["custom_metric"] == 42.5

    def test_overwrite_metric(self):
        spine.record_metric("m", 1.0)
        spine.record_metric("m", 2.0)
        state = spine._load()
        assert state["metrics"]["m"] == 2.0


class TestHealthCheck:
    def test_basic_health_check(self):
        health = spine.check_health()
        assert health["status"] == "green"
        assert health["last_check"] > 0

    def test_history_appended(self):
        for _ in range(3):
            spine.check_health()
        state = spine._load()
        assert len(state["history"]) == 3

    def test_history_capped(self):
        for _ in range(30):
            spine.check_health()
        state = spine._load()
        assert len(state["history"]) <= spine.MAX_HISTORY

    def test_broadcasts_to_thalamus(self):
        spine.check_health()
        entries = thalamus.read_by_source("spine")
        assert len(entries) >= 1
        assert entries[-1]["type"] == "health"


class TestAlerts:
    def test_sorted_by_severity(self):
        spine.check_token_usage(35000, 36000, budget_1h=100000)  # yellow
        spine.check_context_size(196000, 200000)  # red
        alerts = spine.get_alerts()
        assert len(alerts) >= 2
        assert alerts[0]["level"] == "red"

    def test_empty_when_healthy(self):
        assert spine.get_alerts() == []
