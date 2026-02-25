"""Tests for `pulse constellation` CLI commands.

Tests list, register, deregister, broadcast, and state — using temp dirs.
"""

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pulse.src import cli, aura


# ===========================================================================
# Helpers
# ===========================================================================


class ConstellationArgs:
    """Minimal argparse namespace for constellation CLI tests."""

    def __init__(
        self,
        constellation_cmd="list",
        name=None,
        url=None,
        token="",
        weight=None,
    ):
        self.constellation_cmd = constellation_cmd
        self.name = name
        self.url = url
        self.token = token
        self.weight = weight


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    """Redirect all aura state to temp dir."""
    aura_file = tmp_path / "aura.json"
    constellation_file = tmp_path / "constellation.json"
    with (
        patch.object(aura, "_DEFAULT_STATE_DIR", tmp_path),
        patch.object(aura, "_DEFAULT_STATE_FILE", aura_file),
        patch.object(aura, "_DEFAULT_CONSTELLATION_FILE", constellation_file),
    ):
        # Also patch thalamus to avoid state leaks
        from pulse.src import thalamus
        thalamus_file = tmp_path / "broadcast.jsonl"
        with (
            patch.object(thalamus, "_DEFAULT_STATE_DIR", tmp_path),
            patch.object(thalamus, "_DEFAULT_BROADCAST_FILE", thalamus_file),
        ):
            yield tmp_path


# ===========================================================================
# pulse constellation list
# ===========================================================================


class TestConstellationList:
    def test_list_no_peers(self, capsys):
        args = ConstellationArgs(constellation_cmd="list")
        cli.cmd_constellation(args)
        out = capsys.readouterr().out
        # Should show "No peers registered" and example register commands
        assert "No peers registered" in out or "Constellation" in out

    def test_list_shows_registered_peers(self, capsys):
        aura.register_peer("vera", "http://127.0.0.1:9722", token="tok1")
        aura.register_peer("mira", "http://127.0.0.1:9723")
        args = ConstellationArgs(constellation_cmd="list")
        cli.cmd_constellation(args)
        out = capsys.readouterr().out
        assert "vera" in out
        assert "mira" in out


# ===========================================================================
# pulse constellation register
# ===========================================================================


class TestConstellationRegister:
    def test_register_basic(self, capsys):
        args = ConstellationArgs(constellation_cmd="register", name="vera", url="http://127.0.0.1:9722")
        cli.cmd_constellation(args)
        out = capsys.readouterr().out
        assert "vera" in out
        peers = aura.get_peers()
        assert "vera" in peers
        assert peers["vera"]["url"] == "http://127.0.0.1:9722"

    def test_register_with_token(self, capsys):
        args = ConstellationArgs(
            constellation_cmd="register",
            name="sage",
            url="http://127.0.0.1:9724",
            token="secret-tok",
        )
        cli.cmd_constellation(args)
        peers = aura.get_peers()
        assert peers["sage"]["token"] == "secret-tok"

    def test_register_with_weight(self, capsys):
        args = ConstellationArgs(
            constellation_cmd="register",
            name="lyra",
            url="http://127.0.0.1:9725",
            weight=0.9,
        )
        cli.cmd_constellation(args)
        peers = aura.get_peers()
        assert peers["lyra"]["weight"] == pytest.approx(0.9)

    def test_register_default_weight_from_contagion_table(self, capsys):
        """Iris gets weight=1.0 from the contagion table by default."""
        args = ConstellationArgs(
            constellation_cmd="register",
            name="iris",
            url="http://127.0.0.1:9720",
        )
        cli.cmd_constellation(args)
        peers = aura.get_peers()
        assert peers["iris"]["weight"] == pytest.approx(1.0)

    def test_register_missing_name_prints_error(self, capsys):
        args = ConstellationArgs(constellation_cmd="register", name="", url="http://127.0.0.1:9722")
        cli.cmd_constellation(args)
        out = capsys.readouterr().out
        assert "Usage" in out or "✗" in out

    def test_register_missing_url_prints_error(self, capsys):
        args = ConstellationArgs(constellation_cmd="register", name="vera", url="")
        cli.cmd_constellation(args)
        out = capsys.readouterr().out
        assert "Usage" in out or "✗" in out

    def test_register_all_five_agents(self, capsys):
        for name, port in [("vera", 9722), ("mira", 9723), ("sage", 9724), ("lyra", 9725), ("iris", 9720)]:
            args = ConstellationArgs(
                constellation_cmd="register",
                name=name,
                url=f"http://127.0.0.1:{port}",
            )
            cli.cmd_constellation(args)
        peers = aura.get_peers()
        assert len(peers) == 5
        for name in ("vera", "mira", "sage", "lyra", "iris"):
            assert name in peers


# ===========================================================================
# pulse constellation deregister
# ===========================================================================


class TestConstellationDeregister:
    def test_deregister_existing_peer(self, capsys):
        aura.register_peer("vera", "http://127.0.0.1:9722")
        args = ConstellationArgs(constellation_cmd="deregister", name="vera")
        cli.cmd_constellation(args)
        out = capsys.readouterr().out
        assert "vera" in out
        peers = aura.get_peers()
        assert "vera" not in peers

    def test_deregister_nonexistent_peer(self, capsys):
        args = ConstellationArgs(constellation_cmd="deregister", name="nobody")
        cli.cmd_constellation(args)
        out = capsys.readouterr().out
        # Should say not found, not crash
        assert "nobody" in out or "not found" in out.lower() or "○" in out

    def test_deregister_missing_name(self, capsys):
        args = ConstellationArgs(constellation_cmd="deregister", name="")
        cli.cmd_constellation(args)
        out = capsys.readouterr().out
        assert "Usage" in out or "✗" in out


# ===========================================================================
# pulse constellation broadcast
# ===========================================================================


class TestConstellationBroadcast:
    def test_broadcast_no_peers(self, capsys):
        args = ConstellationArgs(constellation_cmd="broadcast")
        cli.cmd_constellation(args)
        out = capsys.readouterr().out
        assert "No peers" in out or "○" in out

    def test_broadcast_with_unreachable_peers(self, capsys):
        """Broadcast to unreachable peers shows error, doesn't crash."""
        aura.register_peer("vera", "http://127.0.0.1:19999")  # port nobody listens on
        args = ConstellationArgs(constellation_cmd="broadcast")
        cli.cmd_constellation(args)
        out = capsys.readouterr().out
        # Should show error indicator for vera, not crash
        assert "vera" in out

    def test_broadcast_with_mocked_success(self, capsys):
        """Broadcast to mocked peers reports success."""
        aura.register_peer("vera", "http://127.0.0.1:9722")
        aura.register_peer("mira", "http://127.0.0.1:9723")

        mock_response = MagicMock()
        mock_response.read.return_value = b'{"ok": true}'
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        import urllib.request
        with patch.object(urllib.request, "urlopen", return_value=mock_response):
            args = ConstellationArgs(constellation_cmd="broadcast")
            cli.cmd_constellation(args)

        out = capsys.readouterr().out
        assert "vera" in out
        assert "mira" in out
        assert "2/2" in out or "Reached" in out


# ===========================================================================
# pulse constellation state
# ===========================================================================


class TestConstellationState:
    def test_state_no_peers(self, capsys):
        args = ConstellationArgs(constellation_cmd="state")
        cli.cmd_constellation(args)
        out = capsys.readouterr().out
        assert "Iris" in out or "iris" in out
        assert "No peers" in out or "register" in out

    def test_state_shows_own_aura(self, capsys):
        # Seed an aura state
        from pulse.src import aura as aura_module
        aura_module._save_state({
            "mood": "energized",
            "focus": 0.8,
            "available": True,
            "energy": 0.9,
            "social_battery": 0.7,
            "last_emit": time.time(),
        })
        args = ConstellationArgs(constellation_cmd="state")
        cli.cmd_constellation(args)
        out = capsys.readouterr().out
        assert "energized" in out

    def test_state_shows_registered_peers(self, capsys):
        aura.register_peer("vera", "http://127.0.0.1:9722")
        # Simulate receiving aura from vera
        aura.receive_from_peer({
            "source_agent": "vera",
            "timestamp": time.time(),
            "aura": {"mood": "content", "energy": 0.9, "focus": 0.8, "available": True},
        })
        args = ConstellationArgs(constellation_cmd="state")
        cli.cmd_constellation(args)
        out = capsys.readouterr().out
        assert "vera" in out
        assert "content" in out

    def test_state_default_invocation(self, capsys):
        """Default cmd (no subcommand) falls through to list."""
        args = ConstellationArgs(constellation_cmd=None)
        cli.cmd_constellation(args)
        out = capsys.readouterr().out
        # Should not crash, should show constellation info
        assert "Constellation" in out or "No peers" in out
