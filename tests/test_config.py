"""Tests for Pulse configuration loading and defaults."""

import os
import tempfile
from pathlib import Path

import yaml

# Adjust import path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config import (
    PulseConfig,
    OpenClawConfig,
    WorkspaceConfig,
    DrivesConfig,
    DriveCategory,
    EvaluatorConfig,
    DaemonConfig,
    StateConfig,
)


class TestConfigDefaults:
    """Verify sane defaults when no config file exists."""

    def test_default_config_creates_without_error(self):
        config = PulseConfig()
        assert config is not None

    def test_default_webhook_url(self):
        config = PulseConfig()
        assert config.openclaw.webhook_url == "http://127.0.0.1:18789/hooks/agent"

    def test_default_workspace_root(self):
        config = PulseConfig()
        assert config.workspace.root == "~/.openclaw/workspace"

    def test_default_drives_threshold(self):
        config = PulseConfig()
        assert config.drives.trigger_threshold == 0.7

    def test_default_evaluator_mode(self):
        config = PulseConfig()
        assert config.evaluator.mode == "rules"

    def test_default_session_mode_is_isolated(self):
        config = PulseConfig()
        assert config.openclaw.session_mode == "isolated"

    def test_default_health_port(self):
        config = PulseConfig()
        assert config.daemon.health_port == 9720

    def test_default_loop_interval(self):
        config = PulseConfig()
        assert config.daemon.loop_interval_seconds == 30

    def test_default_max_turns_per_hour(self):
        config = PulseConfig()
        assert config.openclaw.max_turns_per_hour == 10


class TestConfigFromYaml:
    """Test loading config from YAML."""

    def _write_yaml(self, data: dict) -> str:
        fd, path = tempfile.mkstemp(suffix=".yaml")
        os.write(fd, yaml.dump(data).encode())
        os.close(fd)
        return path

    def test_load_minimal_yaml(self):
        path = self._write_yaml({"openclaw": {"webhook_token": "test123"}})
        try:
            config = PulseConfig.load(path)
            assert config.openclaw.webhook_token == "test123"
        finally:
            os.unlink(path)

    def test_custom_drives_threshold(self):
        path = self._write_yaml({
            "drives": {"trigger_threshold": 1.5}
        })
        try:
            config = PulseConfig.load(path)
            assert config.drives.trigger_threshold == 1.5
        finally:
            os.unlink(path)

    def test_custom_loop_interval(self):
        path = self._write_yaml({
            "daemon": {"loop_interval_seconds": 60}
        })
        try:
            config = PulseConfig.load(path)
            assert config.daemon.loop_interval_seconds == 60
        finally:
            os.unlink(path)

    def test_evaluator_model_mode(self):
        path = self._write_yaml({
            "evaluator": {"mode": "model", "model": {"model": "llama3:8b"}}
        })
        try:
            config = PulseConfig.load(path)
            assert config.evaluator.mode == "model"
            assert config.evaluator.model.model == "llama3:8b"
        finally:
            os.unlink(path)

    def test_nonexistent_file_returns_defaults(self):
        config = PulseConfig.load("/nonexistent/path/pulse.yaml")
        assert config.openclaw.webhook_url == "http://127.0.0.1:18789/hooks/agent"


class TestWorkspacePathResolution:
    """Test workspace path resolution."""

    def test_resolve_goals_path(self):
        config = PulseConfig()
        config.workspace.root = "/tmp/test-workspace"
        path = config.workspace.resolve_path("goals")
        assert path == Path("/tmp/test-workspace/scripts/goals.py")

    def test_resolve_with_tilde(self):
        config = PulseConfig()
        path = config.workspace.resolve_path("daily_notes")
        assert "~" not in str(path)  # tilde should be expanded


class TestEnvVarSubstitution:
    """Test ${ENV_VAR} substitution in config values."""

    def test_env_var_in_token(self):
        os.environ["_PULSE_TEST_TOKEN"] = "secret-token-123"
        path = self._write_yaml({
            "openclaw": {"webhook_token": "${_PULSE_TEST_TOKEN}"}
        })
        try:
            config = PulseConfig.load(path)
            assert config.openclaw.webhook_token == "secret-token-123"
        finally:
            os.unlink(path)
            del os.environ["_PULSE_TEST_TOKEN"]

    def _write_yaml(self, data: dict) -> str:
        fd, path = tempfile.mkstemp(suffix=".yaml")
        os.write(fd, yaml.dump(data).encode())
        os.close(fd)
        return path
