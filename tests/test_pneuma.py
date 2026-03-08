"""Tests for PNEUMA — cross-machine peer discovery and beacon registry."""

import json
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Redirect all state I/O to a temp dir and stub thalamus."""
    fed_dir = tmp_path / "pneuma"
    fed_dir.mkdir()
    peers_file = fed_dir / "peers.json"

    monkeypatch.setattr("src.pneuma._DEFAULT_STATE_DIR", fed_dir)
    monkeypatch.setattr("src.pneuma._DEFAULT_PEERS_FILE", peers_file)
    monkeypatch.setattr("src.thalamus.append", lambda *a, **kw: None)
    return fed_dir


from src import pneuma


# ── Constants ──────────────────────────────────────────────────────────────────

class TestConstants:
    def test_trust_levels_defined(self):
        assert pneuma.TRUST_LOCAL == "local"
        assert pneuma.TRUST_TRUSTED == "trusted"
        assert pneuma.TRUST_GUEST == "guest"

    def test_all_trust_levels_tuple(self):
        assert len(pneuma.ALL_TRUST_LEVELS) == 3
        for level in (pneuma.TRUST_LOCAL, pneuma.TRUST_TRUSTED, pneuma.TRUST_GUEST):
            assert level in pneuma.ALL_TRUST_LEVELS

    def test_timeouts_positive(self):
        assert pneuma.STALE_TIMEOUT_SECS > 0
        assert pneuma.DEAD_TIMEOUT_SECS > pneuma.STALE_TIMEOUT_SECS

    def test_beacon_interval_positive(self):
        assert pneuma.BEACON_INTERVAL_SECS > 0

    def test_loop_interval_positive(self):
        assert pneuma.LOOP_INTERVAL > 0


# ── State helpers ──────────────────────────────────────────────────────────────

class TestStateHelpers:
    def test_load_state_returns_default_when_missing(self):
        state = pneuma._load_state()
        assert "peers" in state
        assert isinstance(state["peers"], dict)

    def test_save_and_reload(self):
        state = pneuma._load_state()
        state["beacons_sent"] = 42
        pneuma._save_state(state)
        reloaded = pneuma._load_state()
        assert reloaded["beacons_sent"] == 42

    def test_load_handles_corrupt_json(self, isolated_state):
        (isolated_state / "peers.json").write_text("{{corrupt")
        state = pneuma._load_state()
        assert "peers" in state  # falls back to default

    def test_save_creates_parent_dirs(self, tmp_path, monkeypatch):
        deep_dir = tmp_path / "a" / "b" / "pneuma"
        deep_file = deep_dir / "peers.json"
        monkeypatch.setattr("src.pneuma._DEFAULT_STATE_DIR", deep_dir)
        monkeypatch.setattr("src.pneuma._DEFAULT_PEERS_FILE", deep_file)
        pneuma._save_state(pneuma._default_state())
        assert deep_file.exists()


# ── register_peer ──────────────────────────────────────────────────────────────

class TestRegisterPeer:
    def test_register_basic(self):
        rec = pneuma.register_peer("scout", "http://192.168.1.5:9720")
        assert rec["peer_id"] == "scout"
        assert rec["endpoint"] == "http://192.168.1.5:9720"
        assert rec["trust_level"] == pneuma.TRUST_GUEST
        assert rec["status"] == "online"

    def test_register_trusted(self):
        rec = pneuma.register_peer("forge", "http://10.0.0.2:9720", trust_level=pneuma.TRUST_TRUSTED)
        assert rec["trust_level"] == pneuma.TRUST_TRUSTED

    def test_register_with_capabilities(self):
        rec = pneuma.register_peer("scout", "http://192.168.1.5:9720",
                                        capabilities=["web_search", "coding"])
        assert "web_search" in rec["capabilities"]
        assert "coding" in rec["capabilities"]

    def test_register_with_display_name(self):
        rec = pneuma.register_peer("s001", "http://10.0.0.3:9720", display_name="Scout Agent")
        assert rec["display_name"] == "Scout Agent"

    def test_register_invalid_trust_raises(self):
        with pytest.raises(ValueError, match="Invalid trust_level"):
            pneuma.register_peer("bad", "http://x.x.x.x:9720", trust_level="overlord")

    def test_register_idempotent(self):
        pneuma.register_peer("scout", "http://192.168.1.5:9720")
        rec2 = pneuma.register_peer("scout", "http://192.168.1.5:9721",
                                         trust_level=pneuma.TRUST_TRUSTED)
        # Should update, not duplicate
        assert rec2["endpoint"] == "http://192.168.1.5:9721"
        assert rec2["trust_level"] == pneuma.TRUST_TRUSTED
        assert len(pneuma.list_peers()) == 1

    def test_register_preserves_registered_at_on_update(self):
        rec1 = pneuma.register_peer("scout", "http://192.168.1.5:9720")
        t1 = rec1["registered_at"]
        time.sleep(0.01)
        rec2 = pneuma.register_peer("scout", "http://192.168.1.5:9720")
        assert rec2["registered_at"] == t1

    def test_register_increments_counter(self):
        pneuma.register_peer("a", "http://a:9720")
        pneuma.register_peer("b", "http://b:9720")
        status = pneuma.get_status()
        assert status["peers_registered"] == 2

    def test_register_emits_thalamus_event(self, monkeypatch):
        events = []
        monkeypatch.setattr("src.thalamus.append", lambda e: events.append(e))
        pneuma.register_peer("scout", "http://192.168.1.5:9720")
        assert any(e.get("event") == "peer_registered" for e in events)

    def test_reregister_does_not_emit_thalamus_again(self, monkeypatch):
        events = []
        monkeypatch.setattr("src.thalamus.append", lambda e: events.append(e))
        pneuma.register_peer("scout", "http://192.168.1.5:9720")
        pneuma.register_peer("scout", "http://192.168.1.5:9720")
        registered_events = [e for e in events if e.get("event") == "peer_registered"]
        assert len(registered_events) == 1


# ── deregister_peer ────────────────────────────────────────────────────────────

class TestDeregisterPeer:
    def test_deregister_existing(self):
        pneuma.register_peer("scout", "http://192.168.1.5:9720")
        ok = pneuma.deregister_peer("scout")
        assert ok is True
        assert pneuma.get_peer("scout") is None

    def test_deregister_nonexistent_returns_false(self):
        ok = pneuma.deregister_peer("nobody")
        assert ok is False

    def test_deregister_removes_from_list(self):
        pneuma.register_peer("a", "http://a:9720")
        pneuma.register_peer("b", "http://b:9720")
        pneuma.deregister_peer("a")
        peers = pneuma.list_peers()
        assert len(peers) == 1
        assert peers[0]["peer_id"] == "b"

    def test_deregister_emits_thalamus_event(self, monkeypatch):
        events = []
        monkeypatch.setattr("src.thalamus.append", lambda e: events.append(e))
        pneuma.register_peer("scout", "http://192.168.1.5:9720")
        pneuma.deregister_peer("scout")
        assert any(e.get("event") == "peer_deregistered" for e in events)


# ── get_peer / list_peers ──────────────────────────────────────────────────────

class TestQueryPeers:
    def test_get_peer_returns_record(self):
        pneuma.register_peer("scout", "http://192.168.1.5:9720")
        peer = pneuma.get_peer("scout")
        assert peer is not None
        assert peer["peer_id"] == "scout"

    def test_get_peer_returns_none_for_unknown(self):
        assert pneuma.get_peer("unknown") is None

    def test_list_peers_empty(self):
        assert pneuma.list_peers() == []

    def test_list_peers_all(self):
        pneuma.register_peer("a", "http://a:9720")
        pneuma.register_peer("b", "http://b:9720", trust_level=pneuma.TRUST_TRUSTED)
        peers = pneuma.list_peers()
        assert len(peers) == 2

    def test_list_peers_filter_by_trust(self):
        pneuma.register_peer("a", "http://a:9720", trust_level=pneuma.TRUST_TRUSTED)
        pneuma.register_peer("b", "http://b:9720", trust_level=pneuma.TRUST_GUEST)
        trusted = pneuma.list_peers(trust_level=pneuma.TRUST_TRUSTED)
        assert len(trusted) == 1
        assert trusted[0]["peer_id"] == "a"

    def test_list_peers_filter_by_status(self):
        pneuma.register_peer("a", "http://a:9720")
        state = pneuma._load_state()
        state["peers"]["a"]["status"] = "offline"
        pneuma._save_state(state)
        online = pneuma.list_peers(status="online")
        assert len(online) == 0
        offline = pneuma.list_peers(status="offline")
        assert len(offline) == 1


# ── Beacon handling ────────────────────────────────────────────────────────────

class TestBeacons:
    def test_build_self_beacon_has_required_fields(self):
        beacon = pneuma.build_self_beacon("iris-primary")
        for field in ("instance_id", "version", "hostname", "port", "drives",
                      "emotional_valence", "available", "capacity", "genome_hash",
                      "capabilities", "timestamp"):
            assert field in beacon, f"Missing field: {field}"

    def test_build_self_beacon_instance_id(self):
        beacon = pneuma.build_self_beacon("my-agent")
        assert beacon["instance_id"] == "my-agent"

    def test_build_self_beacon_drives_included(self):
        beacon = pneuma.build_self_beacon("iris", drives={"goals": 0.5, "curiosity": 0.3})
        assert beacon["drives"]["goals"] == 0.5

    def test_build_self_beacon_genome_hash_stable(self):
        b1 = pneuma.build_self_beacon("iris-primary")
        b2 = pneuma.build_self_beacon("iris-primary")
        assert b1["genome_hash"] == b2["genome_hash"]

    def test_build_self_beacon_different_ids_different_hashes(self):
        b1 = pneuma.build_self_beacon("iris")
        b2 = pneuma.build_self_beacon("scout")
        assert b1["genome_hash"] != b2["genome_hash"]

    def test_receive_beacon_known_peer(self):
        pneuma.register_peer("forge", "http://10.0.0.3:9720", pneuma.TRUST_TRUSTED)
        beacon = {"instance_id": "forge", "capabilities": ["coding"], "timestamp": time.time()}
        peer = pneuma.receive_beacon(beacon)
        assert peer["peer_id"] == "forge"
        assert peer["status"] == "online"
        assert peer["beacons_received"] >= 1

    def test_receive_beacon_unknown_peer_auto_registers_as_guest(self):
        beacon = {"instance_id": "stranger", "endpoint": "http://1.2.3.4:9720",
                  "capabilities": [], "timestamp": time.time()}
        peer = pneuma.receive_beacon(beacon)
        assert peer["trust_level"] == pneuma.TRUST_GUEST

    def test_receive_beacon_increments_global_counter(self):
        beacon = {"instance_id": "a", "timestamp": time.time()}
        pneuma.receive_beacon(beacon)
        pneuma.receive_beacon(beacon)
        status = pneuma.get_status()
        assert status["beacons_received"] == 2

    def test_receive_beacon_missing_instance_id_raises(self):
        with pytest.raises(ValueError, match="missing 'instance_id'"):
            pneuma.receive_beacon({"endpoint": "http://x:9720"})

    def test_receive_beacon_updates_capabilities(self):
        pneuma.register_peer("scout", "http://192.168.1.5:9720")
        beacon = {"instance_id": "scout", "capabilities": ["new_cap"], "timestamp": time.time()}
        peer = pneuma.receive_beacon(beacon)
        assert "new_cap" in peer["capabilities"]

    def test_redact_beacon_for_guest(self):
        full_beacon = pneuma.build_self_beacon(
            "iris", drives={"goals": 0.5}, emotional_valence=0.8
        )
        redacted = pneuma.redact_beacon_for_guest(full_beacon)
        assert "drives" not in redacted
        assert "emotional_valence" not in redacted
        assert "genome_hash" not in redacted
        assert "instance_id" in redacted
        assert "available" in redacted


# ── Staleness & pruning ────────────────────────────────────────────────────────

class TestStaleness:
    def test_mark_stale_peers_fresh_peer_stays_online(self):
        pneuma.register_peer("scout", "http://192.168.1.5:9720")
        newly_offline = pneuma.mark_stale_peers()
        assert "scout" not in newly_offline
        assert pneuma.get_peer("scout")["status"] == "online"

    def test_mark_stale_peers_old_peer_goes_offline(self):
        pneuma.register_peer("scout", "http://192.168.1.5:9720")
        # Manually age the last_seen
        state = pneuma._load_state()
        state["peers"]["scout"]["last_seen"] = time.time() - pneuma.STALE_TIMEOUT_SECS - 1
        pneuma._save_state(state)

        newly_offline = pneuma.mark_stale_peers()
        assert "scout" in newly_offline
        assert pneuma.get_peer("scout")["status"] == "offline"

    def test_mark_stale_already_offline_not_re_added(self):
        pneuma.register_peer("scout", "http://192.168.1.5:9720")
        state = pneuma._load_state()
        state["peers"]["scout"]["status"] = "offline"
        state["peers"]["scout"]["last_seen"] = time.time() - pneuma.STALE_TIMEOUT_SECS - 1
        pneuma._save_state(state)

        newly_offline = pneuma.mark_stale_peers()
        assert "scout" not in newly_offline  # already offline, not "newly" offline

    def test_prune_dead_peers_removes_very_old(self):
        pneuma.register_peer("ghost", "http://192.168.1.9:9720", pneuma.TRUST_GUEST)
        state = pneuma._load_state()
        state["peers"]["ghost"]["status"] = "offline"
        state["peers"]["ghost"]["last_seen"] = time.time() - pneuma.DEAD_TIMEOUT_SECS - 1
        pneuma._save_state(state)

        pruned = pneuma.prune_dead_peers()
        assert "ghost" in pruned
        assert pneuma.get_peer("ghost") is None

    def test_prune_dead_peers_spares_local_peers(self):
        pneuma.register_peer("local-agent", "http://localhost:9721", pneuma.TRUST_LOCAL)
        state = pneuma._load_state()
        state["peers"]["local-agent"]["status"] = "offline"
        state["peers"]["local-agent"]["last_seen"] = time.time() - pneuma.DEAD_TIMEOUT_SECS - 1
        pneuma._save_state(state)

        pruned = pneuma.prune_dead_peers()
        assert "local-agent" not in pruned  # Local peers are never auto-pruned

    def test_prune_dead_peers_spares_recent_offline(self):
        pneuma.register_peer("scout", "http://192.168.1.5:9720")
        state = pneuma._load_state()
        state["peers"]["scout"]["status"] = "offline"
        state["peers"]["scout"]["last_seen"] = time.time() - 60  # only 1 min ago
        pneuma._save_state(state)

        pruned = pneuma.prune_dead_peers()
        assert "scout" not in pruned


# ── Status & loop ──────────────────────────────────────────────────────────────

class TestStatusAndLoop:
    def test_get_status_empty(self):
        status = pneuma.get_status()
        assert status["total_peers"] == 0
        assert status["online_peers"] == 0
        assert status["trusted_peers"] == 0

    def test_get_status_counts(self):
        pneuma.register_peer("a", "http://a:9720", pneuma.TRUST_TRUSTED)
        pneuma.register_peer("b", "http://b:9720", pneuma.TRUST_GUEST)
        status = pneuma.get_status()
        assert status["total_peers"] == 2
        assert status["trusted_peers"] == 1
        assert status["online_peers"] == 2

    def test_should_run_false_at_zero(self):
        assert pneuma.should_run(0) is False

    def test_should_run_true_at_interval(self):
        assert pneuma.should_run(pneuma.LOOP_INTERVAL) is True

    def test_should_run_false_between_intervals(self):
        assert pneuma.should_run(pneuma.LOOP_INTERVAL - 1) is False

    def test_update_skips_when_not_interval(self):
        result = pneuma.update(1, "iris-primary")
        assert result is None

    def test_update_runs_at_interval(self):
        result = pneuma.update(pneuma.LOOP_INTERVAL, "iris-primary")
        assert result is not None
        assert "total_peers" in result

    def test_reconnect_event_emitted(self, monkeypatch):
        events = []
        monkeypatch.setattr("src.thalamus.append", lambda e: events.append(e))
        pneuma.register_peer("scout", "http://192.168.1.5:9720")
        # Mark offline
        state = pneuma._load_state()
        state["peers"]["scout"]["status"] = "offline"
        pneuma._save_state(state)
        # Receive fresh beacon → reconnect
        pneuma.receive_beacon({"instance_id": "scout", "timestamp": time.time()})
        assert any(e.get("event") == "peer_reconnected" for e in events)
