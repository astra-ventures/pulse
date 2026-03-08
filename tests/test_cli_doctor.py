"""Tests for `pulse doctor`.

This command is intentionally read-only and should run without a live daemon.
"""

from pathlib import Path
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

    with patch.object(cli, "_DEFAULT_STATE_DIR", state_dir), \
         patch.object(cli, "LOG_FILE", logs_dir / "pulse.log"), \
         patch.object(cli, "STDOUT_LOG", logs_dir / "pulse-stdout.log"), \
         patch.object(cli, "PID_FILE", tmp_path / "pulse.pid"), \
         patch.object(cli, "PLIST", tmp_path / "ai.openclaw.pulse.plist"), \
         patch.object(cli, "_is_running", return_value=(False, None)):
        # Should not raise
        cli.cmd_doctor(Args())
