"""Tests for `pulse doctor`.

This command is intentionally read-only and should run without a live daemon.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src import cli


class Args:
    """Minimal argparse namespace for CLI tests."""

    pass


def test_doctor_runs_without_exception(tmp_path, monkeypatch):
    # Make pulse.yaml discoverable via CWD
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pulse.yaml").write_text(
        "openclaw:\n  webhook_url: 'http://127.0.0.1:18789/hooks/agent'\n"
    )

    state_dir = tmp_path / "state"
    logs_dir = tmp_path / "logs"
    state_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    with (
        patch.object(cli, "_DEFAULT_STATE_DIR", state_dir),
        patch.object(cli, "LOG_FILE", logs_dir / "pulse.log"),
        patch.object(cli, "STDOUT_LOG", logs_dir / "pulse-stdout.log"),
        patch.object(cli, "PID_FILE", tmp_path / "pulse.pid"),
        patch.object(cli, "PLIST", tmp_path / "ai.openclaw.pulse.plist"),
        patch.object(cli, "_is_running", return_value=(False, None)),
    ):
        # Should not raise
        cli.cmd_doctor(Args())


def test_runtime_paths_use_pulse_config_override(tmp_path, monkeypatch):
    state_dir = tmp_path / "custom-state"
    logs_dir = tmp_path / "custom-logs"
    cfg_path = tmp_path / "pulse-custom.yaml"
    cfg_path.write_text(
        "\n".join(
            [
                "state:",
                f"  dir: '{state_dir}'",
                "logging:",
                f"  file: '{logs_dir / 'pulse.log'}'",
                "daemon:",
                f"  pid_file: '{tmp_path / 'custom.pid'}'",
                "  health_port: 9821",
            ]
        )
    )
    monkeypatch.setenv("PULSE_CONFIG", str(cfg_path))

    runtime = cli._runtime_paths()

    assert runtime["config_path"] == cfg_path
    assert runtime["state_dir"] == state_dir
    assert runtime["log_file"] == logs_dir / "pulse.log"
    assert runtime["stdout_log"] == logs_dir / "pulse-stdout.log"
    assert runtime["pid_file"] == tmp_path / "custom.pid"
    assert runtime["health_port"] == 9821


def test_doctor_reports_configured_state_and_log_dirs(tmp_path, monkeypatch):
    state_dir = tmp_path / "doctor-state"
    logs_dir = tmp_path / "doctor-logs"
    state_dir.mkdir()
    logs_dir.mkdir()
    cfg_path = tmp_path / "pulse-doctor.yaml"
    cfg_path.write_text(
        "\n".join(
            [
                "openclaw:",
                "  webhook_url: 'http://127.0.0.1:18789/hooks/agent'",
                "state:",
                f"  dir: '{state_dir}'",
                "logging:",
                f"  file: '{logs_dir / 'pulse.log'}'",
            ]
        )
    )
    monkeypatch.setenv("PULSE_CONFIG", str(cfg_path))

    with (
        patch.object(cli, "PLIST", tmp_path / "ai.openclaw.pulse.plist"),
        patch.object(cli, "_is_running", return_value=(False, None)),
        cli.console.capture() as capture,
    ):
        cli.cmd_doctor(Args())

    output = capture.get()
    assert cfg_path.name in output
    assert state_dir.name in output
    assert logs_dir.name in output


def test_logs_reads_configured_stdout_log(tmp_path, monkeypatch, capsys):
    logs_dir = tmp_path / "runtime-logs"
    logs_dir.mkdir()
    cfg_path = tmp_path / "pulse-logs.yaml"
    cfg_path.write_text(
        "\n".join(
            [
                "logging:",
                f"  file: '{logs_dir / 'pulse.log'}'",
            ]
        )
    )
    (logs_dir / "pulse-stdout.log").write_text("alpha\nbeta\n")
    monkeypatch.setenv("PULSE_CONFIG", str(cfg_path))

    cli.cmd_logs(SimpleNamespace(count=10))

    output = capsys.readouterr().out
    assert "alpha" in output
    assert "beta" in output
