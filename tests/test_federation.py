"""Tests for FEDERATION — cross-machine peer discovery and beacon registry."""

import json
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Redirect all state I/O to a temp dir and stub thalamus."""
    fed_dir = tmp_path / "federation"
    fed_dir.mkdir()
    peers_file = fed_dir / "peers.json"

    monkeypatch.setattr("pulse.src.federation._DEFAULT_STATE_DIR", fed_dir)
    monkeypatch.setattr("pulse.src.federation._DEFAULT_PEERS_FILE", peers_file)
    monkeypatch.setattr("pulse.src.thalamus.append", lambda *a, **kw: None)
    return fed_dir


from pulse.src import federation


# ── Constants ──────────────────────────────────────────────────────────────────

class TestConstants:
    def test_trust_levels_defined(self):
        assert federation.TRUST_LOCAL == "local"
        assert federation.TRUST_TRUSTED == "trusted"
        assert federation.TRUST_GUEST == "guest"

    def test_all_trust_levels_tuple(self):
        assert len(federation.ALL_TRUST_LEVELS) == 3
        for level in (federation.TRUST_LOCAL, federation.TRUST_TRUSTED, federation.TRUST_GUEST):
            assert level in federation.ALL_TRUST_LEVELS

    def test_timeouts_positive(self):
        assert federation.STALE_TIMEOUT_SECS > 0
        assert federation.DEAD_TIMEOUT_SECS > federation.STALE_TIMEOUT_SECS

    def test_beacon_interval_positive(self):
        assert federation.BEACON_INTERVAL_SECS > 0

    def test_loop_interval_positive(self):
        assert federation.LOOP_INTERVAL > 0


# ── State helpers ──────────────────────────────────────────────────────────────

class TestStateHelpers:
    def test_load_state_returns_default_when_missing(self):
        state = federation._load_state()
        assert "peers" in state
        assert isinstance(state["peers"], dict)

    def test_save_and_reload(self):
        state = federation._load_state()
        state["beacons_sent"] = 42
        federation._save_state(state)
        reloaded = federation._load_state()
        assert reloaded["beacons_sent"] == 42

    def test_load_handles_corrupt_json(self, isolated_state):
        (isolated_state / "peers.json").write_text("{{corrupt")
        state = federation._load_state()
        assert "peers" in state  # falls back to default

    def test_save_creates_parent_dirs(self, tmp_path, monkeypatch):
        deep_dir = tmp_path / "a" / "b" / "federation"
        deep_file = deep_dir / "peers.json"
        monkeypatch.setattr("pulse.src.federation._DEFAULT_STATE_DIR", deep_dir)
        monkeypatch.setattr("pulse.src.federation._DEFAULT_PEERS_FILE", deep_file)
        federation._save_state(federation._default_state())
        assert deep_file.exists()


# ── register_peer ──────────────────────────────────────────────────────────────

class TestRegisterPeer:
    def test_register_basic(self):
        rec = federation.register_peer("scout", "http://192.168.1.5:9720")
        assert rec["peer_id"] == "scout"
        assert rec["endpoint"] == "http://192.168.1.5:9720"
        assert rec["trust_level"] == federation.TRUST_GUEST
        assert rec["status"] == "online"

    def test_register_trusted(self):
        rec = federation.register_peer("forge", "http://10.0.0.2:9720", trust_level=federation.TRUST_TRUSTED)
        assert rec["trust_level"] == federation.TRUST_TRUSTED

    def test_register_with_capabilities(self):
        rec = federation.register_peer("scout", "http://192.168.1.5:9720",
                                        capabilities=["web_search", "coding"])
        assert "web_search" in rec["capabilities"]
        assert "coding" in rec["capabilities"]

    def test_register_with_display_name(self):
        rec = federation.register_peer("s001", "http://10.0.0.3:9720", display_name="Scout Agent")
        assert rec["display_name"] == "Scout Agent"

    def test_register_invalid_trust_raises(self):
        with pytest.raises(ValueError, match="Invalid trust_level"):
            federation.register_peer("bad", "http://x.x.x.x:9720", trust_level="overlord")

    def test_register_idempotent(self):
        federation.register_peer("scout", "http://192.168.1.5:9720")
        rec2 = federation.register_peer("scout", "http://192.168.1.5:9721",
                                         trust_level=federation.TRUST_TRUSTED)
        # Should update, not duplicate
        assert rec2["endpoint"] == "http://192.168.1.5:9721"
        assert rec2["trust_level"] == federation.TRUST_TRUSTED
        assert len(federation.list_peers()) == 1

    def test_register_preserves_registered_at_on_update(self):
        rec1 = federation.register_peer("scout", "http://192.168.1.5:9720")
        t1 = rec1["registered_at"]
        time.sleep(0.01)
        rec2 = federation.register_peer("scout", "http://192.168.1.5:9720")
        assert rec2["registered_at"] == t1

    def test_register_increments_counter(self):
        federation.register_peer("a", "http://a:9720")
        federation.register_peer("b", "http://b:9720")
        status = federation.get_status()
        assert status["peers_registered"] == 2

    def test_register_emits_thalamus_event(self, monkeypatch):
        events = []
        monkeypatch.setattr("pulse.src.thalamus.append", lambda e: events.append(e))
        federation.register_peer("scout", "http://192.168.1.5:9720")
        assert any(e.get("event") == "peer_registered" for e in events)

    def test_reregister_does_not_emit_thalamus_again(self, monkeypatch):
        events = []
        monkeypatch.setattr("pulse.src.thalamus.append", lambda e: events.append(e))
        federation.register_peer("scout", "http://192.168.1.5:9720")
        federation.register_peer("scout", "http://192.168.1.5:9720")
        registered_events = [e for e in events if e.get("event") == "peer_registered"]
        assert len(registered_events) == 1


# ── deregister_peer ────────────────────────────────────────────────────────────

class TestDeregisterPeer:
    def test_deregister_existing(self):
        federation.register_peer("scout", "http://192.168.1.5:9720")
        ok = federation.deregister_peer("scout")
        assert ok is True
        assert federation.get_peer("scout") is None

    def test_deregister_nonexistent_returns_false(self):
        ok = federation.deregister_peer("nobody")
        assert ok is False

    def test_deregister_removes_from_list(self):
        federation.register_peer("a", "http://a:9720")
        federation.register_peer("b", "http://b:9720")
        federation.deregister_peer("a")
        peers = federation.list_peers()
        assert len(peers) == 1
        assert peers[0]["peer_id"] == "b"

    def test_deregister_emits_thalamus_event(self, monkeypatch):
        events = []
        monkeypatch.setattr("pulse.src.thalamus.append", lambda e: events.append(e))
        federation.register_peer("scout", "http://192.168.1.5:9720")
        federation.deregister_peer("scout")
        assert any(e.get("event") == "peer_deregistered" for e in events)


# ── get_peer / list_peers ──────────────────────────────────────────────────────

class TestQueryPeers:
    def test_get_peer_returns_record(self):
        federation.register_peer("scout", "http://192.168.1.5:9720")
        peer = federation.get_peer("scout")
        assert peer is not None
        assert peer["peer_id"] == "scout"

    def test_get_peer_returns_none_for_unknown(self):
        assert federation.get_peer("unknown") is None

    def test_list_peers_empty(self):
        assert federation.list_peers() == []

    def test_list_peers_all(self):
        federation.register_peer("a", "http://a:9720")
        federation.register_peer("b", "http://b:9720", trust_level=federation.TRUST_TRUSTED)
        peers = federation.list_peers()
        assert len(peers) == 2

    def test_list_peers_filter_by_trust(self):
        federation.register_peer("a", "http://a:9720", trust_level=federation.TRUST_TRUSTED)
        federation.register_peer("b", "http://b:9720", trust_level=federation.TRUST_GUEST)
        trusted = federation.list_peers(trust_level=federation.TRUST_TRUSTED)
        assert len(trusted) == 1
        assert trusted[0]["peer_id"] == "a"

    def test_list_peers_filter_by_status(self):
        federation.register_peer("a", "http://a:9720")
        state = federation._load_state()
        state["peers"]["a"]["status"] = "offline"
        federation._save_state(state)
        online = federation.list_peers(status="online")
        assert len(online) == 0
        offline = federation.list_peers(status="offline")
        assert len(offline) == 1


# ── Beacon handling ────────────────────────────────────────────────────────────

class TestBeacons:
    def test_build_self_beacon_has_required_fields(self):
        beacon = federation.build_self_beacon("iris-primary")
        for field in ("instance_id", "version", "hostname", "port", "drives",
                      "emotional_valence", "available", "capacity", "genome_hash",
                      "capabilities", "timestamp"):
            assert field in beacon, f"Missing field: {field}"

    def test_build_self_beacon_instance_id(self):
        beacon = federation.build_self_beacon("my-agent")
        assert beacon["instance_id"] == "my-agent"

    def test_build_self_beacon_drives_included(self):
        beacon = federation.build_self_beacon("iris", drives={"goals": 0.5, "curiosity": 0.3})
        assert beacon["drives"]["goals"] == 0.5

    def test_build_self_beacon_genome_hash_stable(self):
        b1 = federation.build_self_beacon("iris-primary")
        b2 = federation.build_self_beacon("iris-primary")
        assert b1["genome_hash"] == b2["genome_hash"]

    def test_build_self_beacon_different_ids_different_hashes(self):
        b1 = federation.build_self_beacon("iris")
        b2 = federation.build_self_beacon("scout")
        assert b1["genome_hash"] != b2["genome_hash"]

    def test_receive_beacon_known_peer(self):
        federation.register_peer("forge", "http://10.0.0.3:9720", federation.TRUST_TRUSTED)
        beacon = {"instance_id": "forge", "capabilities": ["coding"], "timestamp": time.time()}
        peer = federation.receive_beacon(beacon)
        assert peer["peer_id"] == "forge"
        assert peer["status"] == "online"
        assert peer["beacons_received"] >= 1

    def test_receive_beacon_unknown_peer_auto_registers_as_guest(self):
        beacon = {"instance_id": "stranger", "endpoint": "http://1.2.3.4:9720",
                  "capabilities": [], "timestamp": time.time()}
        peer = federation.receive_beacon(beacon)
        assert peer["trust_level"] == federation.TRUST_GUEST

    def test_receive_beacon_increments_global_counter(self):
        beacon = {"instance_id": "a", "timestamp": time.time()}
        federation.receive_beacon(beacon)
        federation.receive_beacon(beacon)
        status = federation.get_status()
        assert status["beacons_received"] == 2

    def test_receive_beacon_missing_instance_id_raises(self):
        with pytest.raises(ValueError, match="missing 'instance_id'"):
            federation.receive_beacon({"endpoint": "http://x:9720"})

    def test_receive_beacon_updates_capabilities(self):
        federation.register_peer("scout", "http://192.168.1.5:9720")
        beacon = {"instance_id": "scout", "capabilities": ["new_cap"], "timestamp": time.time()}
        peer = federation.receive_beacon(beacon)
        assert "new_cap" in peer["capabilities"]

    def test_redact_beacon_for_guest(self):
        full_beacon = federation.build_self_beacon(
            "iris", drives={"goals": 0.5}, emotional_valence=0.8
        )
        redacted = federation.redact_beacon_for_guest(full_beacon)
        assert "drives" not in redacted
        assert "emotional_valence" not in redacted
        assert "genome_hash" not in redacted
        assert "instance_id" in redacted
        assert "available" in redacted


# ── Staleness & pruning ────────────────────────────────────────────────────────

class TestStaleness:
    def test_mark_stale_peers_fresh_peer_stays_online(self):
        federation.register_peer("scout", "http://192.168.1.5:9720")
        newly_offline = federation.mark_stale_peers()
        assert "scout" not in newly_offline
        assert federation.get_peer("scout")["status"] == "online"

    def test_mark_stale_peers_old_peer_goes_offline(self):
        federation.register_peer("scout", "http://192.168.1.5:9720")
        # Manually age the last_seen
        state = federation._load_state()
        state["peers"]["scout"]["last_seen"] = time.time() - federation.STALE_TIMEOUT_SECS - 1
        federation._save_state(state)

        newly_offline = federation.mark_stale_peers()
        assert "scout" in newly_offline
        assert federation.get_peer("scout")["status"] == "offline"

    def test_mark_stale_already_offline_not_re_added(self):
        federation.register_peer("scout", "http://192.168.1.5:9720")
        state = federation._load_state()
        state["peers"]["scout"]["status"] = "offline"
        state["peers"]["scout"]["last_seen"] = time.time() - federation.STALE_TIMEOUT_SECS - 1
        federation._save_state(state)

        newly_offline = federation.mark_stale_peers()
        assert "scout" not in newly_offline  # already offline, not "newly" offline

    def test_prune_dead_peers_removes_very_old(self):
        federation.register_peer("ghost", "http://192.168.1.9:9720", federation.TRUST_GUEST)
        state = federation._load_state()
        state["peers"]["ghost"]["status"] = "offline"
        state["peers"]["ghost"]["last_seen"] = time.time() - federation.DEAD_TIMEOUT_SECS - 1
        federation._save_state(state)

        pruned = federation.prune_dead_peers()
        assert "ghost" in pruned
        assert federation.get_peer("ghost") is None

    def test_prune_dead_peers_spares_local_peers(self):
        federation.register_peer("local-agent", "http://localhost:9721", federation.TRUST_LOCAL)
        state = federation._load_state()
        state["peers"]["local-agent"]["status"] = "offline"
        state["peers"]["local-agent"]["last_seen"] = time.time() - federation.DEAD_TIMEOUT_SECS - 1
        federation._save_state(state)

        pruned = federation.prune_dead_peers()
        assert "local-agent" not in pruned  # Local peers are never auto-pruned

    def test_prune_dead_peers_spares_recent_offline(self):
        federation.register_peer("scout", "http://192.168.1.5:9720")
        state = federation._load_state()
        state["peers"]["scout"]["status"] = "offline"
        state["peers"]["scout"]["last_seen"] = time.time() - 60  # only 1 min ago
        federation._save_state(state)

        pruned = federation.prune_dead_peers()
        assert "scout" not in pruned


# ── Status & loop ──────────────────────────────────────────────────────────────

class TestStatusAndLoop:
    def test_get_status_empty(self):
        status = federation.get_status()
        assert status["total_peers"] == 0
        assert status["online_peers"] == 0
        assert status["trusted_peers"] == 0

    def test_get_status_counts(self):
        federation.register_peer("a", "http://a:9720", federation.TRUST_TRUSTED)
        federation.register_peer("b", "http://b:9720", federation.TRUST_GUEST)
        status = federation.get_status()
        assert status["total_peers"] == 2
        assert status["trusted_peers"] == 1
        assert status["online_peers"] == 2

    def test_should_run_false_at_zero(self):
        assert federation.should_run(0) is False

    def test_should_run_true_at_interval(self):
        assert federation.should_run(federation.LOOP_INTERVAL) is True

    def test_should_run_false_between_intervals(self):
        assert federation.should_run(federation.LOOP_INTERVAL - 1) is False

    def test_update_skips_when_not_interval(self):
        result = federation.update(1, "iris-primary")
        assert result is None

    def test_update_runs_at_interval(self):
        result = federation.update(federation.LOOP_INTERVAL, "iris-primary")
        assert result is not None
        assert "total_peers" in result

    def test_reconnect_event_emitted(self, monkeypatch):
        events = []
        monkeypatch.setattr("pulse.src.thalamus.append", lambda e: events.append(e))
        federation.register_peer("scout", "http://192.168.1.5:9720")
        # Mark offline
        state = federation._load_state()
        state["peers"]["scout"]["status"] = "offline"
        federation._save_state(state)
        # Receive fresh beacon → reconnect
        federation.receive_beacon({"instance_id": "scout", "timestamp": time.time()})
        assert any(e.get("event") == "peer_reconnected" for e in events)
