"""Tests for AURA — Ambient State Broadcast (local + inter-agent constellation)."""

import json
import time
from unittest.mock import patch, MagicMock
from urllib.error import URLError

import pytest

from pulse.src import aura, thalamus


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    bf = tmp_path / "thalamus.jsonl"
    sf = tmp_path / "aura.json"
    cf = tmp_path / "constellation.json"
    with patch.object(aura, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(aura, "_DEFAULT_STATE_FILE", sf), \
         patch.object(aura, "_DEFAULT_CONSTELLATION_FILE", cf), \
         patch.object(thalamus, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(thalamus, "_DEFAULT_BROADCAST_FILE", bf):
        yield tmp_path


# ─── Local emit tests ──────────────────────────────────────────────────────

class TestEmit:
    def test_emit_returns_aura(self):
        result = aura.emit()
        assert "mood" in result
        assert "energy" in result
        assert "available" in result
        assert "focus" in result

    def test_emit_broadcasts_ambient(self):
        aura.emit()
        entries = thalamus.read_by_source("aura")
        assert any(e["type"] == "ambient" for e in entries)

    def test_emit_updates_last_emit(self):
        before = time.time()
        result = aura.emit()
        assert result["last_emit"] >= before


class TestShouldEmit:
    def test_should_emit_initially(self):
        assert aura.should_emit() is True

    def test_should_not_emit_right_after(self):
        aura.emit()
        assert aura.should_emit() is False


class TestGetAura:
    def test_get_aura_keys(self):
        a = aura.get_aura()
        assert "mood" in a

    def test_get_aura_defaults(self):
        a = aura.get_aura()
        assert a["mood"] == "neutral"
        assert a["energy"] == 1.0


class TestStatus:
    def test_status_keys(self):
        status = aura.get_status()
        assert "mood" in status
        assert "energy" in status
        assert "available" in status
        assert "last_emit" in status


# ─── Constellation registry tests ─────────────────────────────────────────

class TestRegisterPeer:
    def test_register_basic(self):
        result = aura.register_peer("vera", "http://127.0.0.1:9722", token="tok123")
        assert result["url"] == "http://127.0.0.1:9722"
        assert result["token"] == "tok123"
        assert result["weight"] == 0.5  # default for vera

    def test_register_custom_weight(self):
        result = aura.register_peer("custom", "http://127.0.0.1:9799", weight=0.8)
        assert result["weight"] == 0.8

    def test_register_persists(self):
        aura.register_peer("sage", "http://127.0.0.1:9724", token="sagetoken")
        peers = aura.get_peers()
        assert "sage" in peers
        assert peers["sage"]["url"] == "http://127.0.0.1:9724"

    def test_register_multiple_peers(self):
        aura.register_peer("vera", "http://127.0.0.1:9722")
        aura.register_peer("mira", "http://127.0.0.1:9723")
        aura.register_peer("lyra", "http://127.0.0.1:9725")
        peers = aura.get_peers()
        assert len(peers) == 3

    def test_deregister_peer(self):
        aura.register_peer("vera", "http://127.0.0.1:9722")
        removed = aura.deregister_peer("vera")
        assert removed is True
        assert "vera" not in aura.get_peers()

    def test_deregister_nonexistent(self):
        removed = aura.deregister_peer("nobody")
        assert removed is False

    def test_set_own_name(self):
        aura.set_own_name("sage")
        state = aura.get_constellation_state()
        assert state["own"]["name"] == "sage"


# ─── Broadcast tests ───────────────────────────────────────────────────────

class TestBroadcastToPeers:
    def test_no_peers_returns_empty(self):
        result = aura.broadcast_to_peers()
        assert result == {}

    def test_broadcast_success(self):
        aura.register_peer("vera", "http://127.0.0.1:9722", token="tok")
        aura.emit()

        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            results = aura.broadcast_to_peers()

        assert "vera" in results
        assert results["vera"]["ok"] is True
        assert results["vera"]["error"] is None

    def test_broadcast_failure_handled_gracefully(self):
        aura.register_peer("mira", "http://127.0.0.1:9723")
        aura.emit()

        with patch("urllib.request.urlopen", side_effect=URLError("connection refused")):
            results = aura.broadcast_to_peers()

        assert "mira" in results
        assert results["mira"]["ok"] is False
        assert results["mira"]["error"] is not None

    def test_broadcast_logs_to_thalamus(self):
        aura.register_peer("lyra", "http://127.0.0.1:9725")
        aura.emit()

        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            aura.broadcast_to_peers()

        entries = thalamus.read_by_source("aura")
        broadcast_entries = [e for e in entries if e["type"] == "constellation_broadcast"]
        assert len(broadcast_entries) >= 1

    def test_broadcast_updates_last_ping_on_success(self):
        aura.register_peer("vera", "http://127.0.0.1:9722")
        before = time.time()

        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            aura.broadcast_to_peers()

        peers = aura.get_peers()
        assert peers["vera"]["last_ping"] >= before
        assert peers["vera"]["last_error"] is None

    def test_broadcast_records_error_on_failure(self):
        aura.register_peer("mira", "http://127.0.0.1:9723")

        with patch("urllib.request.urlopen", side_effect=URLError("refused")):
            aura.broadcast_to_peers()

        peers = aura.get_peers()
        assert peers["mira"]["last_error"] is not None


# ─── Receive tests ─────────────────────────────────────────────────────────

class TestReceiveFromPeer:
    def test_receive_neutral_no_contagion(self):
        payload = {
            "source_agent": "vera",
            "timestamp": time.time(),
            "aura": {"mood": "neutral", "energy": 1.0},
        }
        result = aura.receive_from_peer(payload)
        assert result["source"] == "vera"
        assert result["contagion_applied"] is False

    def test_receive_euphoric_applies_contagion(self):
        aura.register_peer("iris", "http://127.0.0.1:9720", weight=1.0)
        payload = {
            "source_agent": "iris",
            "timestamp": time.time(),
            "aura": {"mood": "euphoric", "energy": 1.0},
        }

        mock_limbic = MagicMock()
        mock_limbic.record_emotion.return_value = {"id": "test_afterimage"}
        with patch("pulse.src.limbic", mock_limbic, create=True):
            result = aura.receive_from_peer(payload)

        assert result["contagion_applied"] is True
        assert result["scaled_valence"] > 0
        mock_limbic.record_emotion.assert_called_once()

    def test_receive_burned_out_applies_negative_contagion(self):
        aura.register_peer("vera", "http://127.0.0.1:9722", weight=0.5)
        payload = {
            "source_agent": "vera",
            "timestamp": time.time(),
            "aura": {"mood": "burned_out", "energy": 0.8},
        }

        mock_limbic = MagicMock()
        mock_limbic.record_emotion.return_value = {"id": "test_afterimage"}
        with patch("pulse.src.limbic", mock_limbic, create=True):
            result = aura.receive_from_peer(payload)

        assert result["scaled_valence"] < 0
        assert result["contagion_applied"] is True

    def test_receive_low_energy_dampens_contagion(self):
        """A low-energy peer has reduced emotional impact."""
        aura.register_peer("vera", "http://127.0.0.1:9722", weight=0.5)
        payload_high_energy = {
            "source_agent": "vera",
            "timestamp": time.time(),
            "aura": {"mood": "euphoric", "energy": 1.0},
        }
        payload_low_energy = {
            "source_agent": "vera",
            "timestamp": time.time(),
            "aura": {"mood": "euphoric", "energy": 0.1},
        }

        r_high = aura.receive_from_peer(payload_high_energy)
        r_low = aura.receive_from_peer(payload_low_energy)
        assert r_high["scaled_intensity"] > r_low["scaled_intensity"]

    def test_receive_stores_last_aura(self):
        aura.register_peer("sage", "http://127.0.0.1:9724")
        payload = {
            "source_agent": "sage",
            "timestamp": time.time(),
            "aura": {"mood": "content", "energy": 0.9},
        }
        aura.receive_from_peer(payload)
        state = aura.get_constellation_state()
        assert "sage" in state["peers"]
        assert state["peers"]["sage"]["aura"]["mood"] == "content"

    def test_receive_broadcasts_to_thalamus(self):
        aura.register_peer("lyra", "http://127.0.0.1:9725", weight=0.7)
        payload = {
            "source_agent": "lyra",
            "timestamp": time.time(),
            "aura": {"mood": "bonded", "energy": 0.95},
        }
        with patch("pulse.src.limbic", MagicMock(), create=True):
            aura.receive_from_peer(payload)

        entries = thalamus.read_by_source("aura")
        receive_entries = [e for e in entries if e["type"] == "constellation_receive"]
        assert len(receive_entries) >= 1

    def test_receive_unknown_peer_uses_default_weight(self):
        """Unregistered peers still get processed with default weight."""
        payload = {
            "source_agent": "stranger",
            "timestamp": time.time(),
            "aura": {"mood": "euphoric", "energy": 1.0},
        }
        result = aura.receive_from_peer(payload)
        assert result["weight"] == 0.5  # default fallback


# ─── Constellation state tests ─────────────────────────────────────────────

class TestGetConstellationState:
    def test_constellation_state_own(self):
        aura.emit()
        state = aura.get_constellation_state()
        assert "own" in state
        assert "mood" in state["own"]["aura"]
        assert state["own"]["name"] == "iris"

    def test_constellation_state_empty_peers(self):
        state = aura.get_constellation_state()
        assert state["peers"] == {}

    def test_constellation_state_with_peers(self):
        aura.register_peer("vera", "http://127.0.0.1:9722", weight=0.5)
        aura.register_peer("mira", "http://127.0.0.1:9723", weight=0.5)
        state = aura.get_constellation_state()
        assert "vera" in state["peers"]
        assert "mira" in state["peers"]
        # No aura received yet — empty dict
        assert state["peers"]["vera"]["aura"] == {}
        assert state["peers"]["mira"]["aura"] == {}
