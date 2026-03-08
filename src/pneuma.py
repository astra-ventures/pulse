"""PNEUMA — Cross-Machine Peer Discovery & Beacon Registry.

In Phase 1, SYNAPSE handled intra-machine agent-to-agent signals inside a
Constellation. PNEUMA is the Phase 2 layer that operates at network scale:
Pulse instances on different machines can discover each other, exchange state
beacons, and coordinate across trust boundaries.

Architecture (per PHASE2-ARCHITECTURE.md):

  ┌──────────┐   beacon    ┌──────────┐
  │  Pulse A │◀──────────▶│  Pulse B │
  │  (local) │             │ (remote) │
  └────┬─────┘             └────┬─────┘
       │                         │
       └─────────── PNEUMA ──┘
                  (this module)

Key concepts:
- Beacon: a periodic JSON heartbeat that each Pulse broadcasts
- Peer registry: list of known remote instances with last-seen, endpoint, trust
- Trust levels: local > trusted > guest (controls what each peer can see/do)
- Stale pruning: peers not seen in STALE_TIMEOUT seconds are marked offline
- Self-beacon: what THIS instance broadcasts when asked

This module is stateless daemon-callable — call update_beacon() every N loops,
prune_stale_peers() periodically, and build_self_beacon() when responding to
incoming beacon requests.

Pneuma endpoints (added to observation_api.py in Phase 2):
  POST /pneuma/register   → register a new peer
  GET  /pneuma/peers      → list known peers with status
  POST /pneuma/beacon     → receive a beacon from a peer
  GET  /pneuma/beacon     → return this instance's current beacon
  POST /pneuma/deregister → remove a peer

This module handles the state layer. HTTP routing lives in observation_api.py.
"""

import json
import time
import hashlib
from pathlib import Path
from typing import Optional

from src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state" / "pneuma"
_DEFAULT_PEERS_FILE = _DEFAULT_STATE_DIR / "peers.json"

# Trust levels — governs what a peer can see / do
TRUST_LOCAL = "local"       # Same machine, full trust
TRUST_TRUSTED = "trusted"   # Different machine, manually verified, same owner
TRUST_GUEST = "guest"       # Unknown / unverified, read-only beacon visibility

ALL_TRUST_LEVELS = (TRUST_LOCAL, TRUST_TRUSTED, TRUST_GUEST)

# Timeout thresholds
STALE_TIMEOUT_SECS = 300      # Mark peer offline if no beacon for 5 min
DEAD_TIMEOUT_SECS = 86400     # Prune entirely after 24 h offline

# Beacon interval (how often this instance should broadcast)
BEACON_INTERVAL_SECS = 60

# Loop interval for pneuma duties (every N daemon loops)
LOOP_INTERVAL = 60   # ~30 min at 30s loop cadence


def _default_state() -> dict:
    return {
        "peers": {},          # peer_id → peer record
        "last_beacon_sent": 0,
        "beacons_sent": 0,
        "beacons_received": 0,
        "peers_registered": 0,
        "peers_pruned": 0,
    }


def _load_state() -> dict:
    if _DEFAULT_PEERS_FILE.exists():
        try:
            return json.loads(_DEFAULT_PEERS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return _default_state()


def _save_state(state: dict):
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    _DEFAULT_PEERS_FILE.write_text(json.dumps(state, indent=2))


# ── Peer management ────────────────────────────────────────────────────────────

def register_peer(
    peer_id: str,
    endpoint: str,
    trust_level: str = TRUST_GUEST,
    capabilities: Optional[list] = None,
    display_name: Optional[str] = None,
) -> dict:
    """Register or update a known peer.

    Returns the peer record after registration.
    Emits THALAMUS event on first registration.
    """
    if trust_level not in ALL_TRUST_LEVELS:
        raise ValueError(f"Invalid trust_level '{trust_level}'. Must be one of {ALL_TRUST_LEVELS}")

    state = _load_state()
    now = time.time()
    is_new = peer_id not in state["peers"]

    state["peers"][peer_id] = {
        "peer_id": peer_id,
        "display_name": display_name or peer_id,
        "endpoint": endpoint,
        "trust_level": trust_level,
        "capabilities": capabilities or [],
        "registered_at": state["peers"].get(peer_id, {}).get("registered_at", now),
        "last_seen": now,
        "last_beacon": None,
        "status": "online",
        "beacons_received": state["peers"].get(peer_id, {}).get("beacons_received", 0),
    }

    if is_new:
        state["peers_registered"] = state.get("peers_registered", 0) + 1
        thalamus.append({
            "source": "PNEUMA",
            "event": "peer_registered",
            "peer_id": peer_id,
            "display_name": display_name or peer_id,
            "trust_level": trust_level,
            "endpoint": endpoint,
        })

    _save_state(state)
    return state["peers"][peer_id]


def deregister_peer(peer_id: str) -> bool:
    """Remove a peer from the registry. Returns True if found and removed."""
    state = _load_state()
    if peer_id not in state["peers"]:
        return False

    del state["peers"][peer_id]
    thalamus.append({
        "source": "PNEUMA",
        "event": "peer_deregistered",
        "peer_id": peer_id,
    })
    _save_state(state)
    return True


def get_peer(peer_id: str) -> Optional[dict]:
    """Return a single peer record, or None if not found."""
    state = _load_state()
    return state["peers"].get(peer_id)


def list_peers(
    trust_level: Optional[str] = None,
    status: Optional[str] = None,
) -> list:
    """Return all peers, optionally filtered by trust_level or status."""
    state = _load_state()
    peers = list(state["peers"].values())
    if trust_level:
        peers = [p for p in peers if p["trust_level"] == trust_level]
    if status:
        peers = [p for p in peers if p.get("status") == status]
    return peers


# ── Beacon handling ────────────────────────────────────────────────────────────

def receive_beacon(beacon: dict) -> dict:
    """Process an incoming beacon from a peer.

    Updates the peer's last_seen, status, and last_beacon payload.
    Registers the peer as guest if not already known.
    Returns the updated peer record.
    """
    peer_id = beacon.get("instance_id")
    if not peer_id:
        raise ValueError("Beacon missing 'instance_id'")

    state = _load_state()
    now = time.time()

    if peer_id not in state["peers"]:
        # Auto-register as guest
        state["peers"][peer_id] = {
            "peer_id": peer_id,
            "display_name": peer_id,
            "endpoint": beacon.get("endpoint", ""),
            "trust_level": TRUST_GUEST,
            "capabilities": beacon.get("capabilities", []),
            "registered_at": now,
            "last_seen": now,
            "last_beacon": None,
            "status": "online",
            "beacons_received": 0,
        }
        state["peers_registered"] = state.get("peers_registered", 0) + 1
        thalamus.append({
            "source": "PNEUMA",
            "event": "peer_discovered",
            "peer_id": peer_id,
            "trust_level": TRUST_GUEST,
        })

    peer = state["peers"][peer_id]
    was_offline = peer.get("status") == "offline"

    peer["last_seen"] = now
    peer["last_beacon"] = beacon
    peer["status"] = "online"
    peer["beacons_received"] = peer.get("beacons_received", 0) + 1

    # Update capabilities if provided
    if "capabilities" in beacon:
        peer["capabilities"] = beacon["capabilities"]

    state["beacons_received"] = state.get("beacons_received", 0) + 1

    if was_offline:
        thalamus.append({
            "source": "PNEUMA",
            "event": "peer_reconnected",
            "peer_id": peer_id,
        })

    _save_state(state)
    return peer


def build_self_beacon(
    instance_id: str,
    port: int = 9720,
    drives: Optional[dict] = None,
    emotional_valence: float = 0.5,
    available: bool = True,
    capacity: float = 1.0,
    capabilities: Optional[list] = None,
    version: str = "0.4.0",
) -> dict:
    """Build this instance's current beacon payload for broadcasting.

    The beacon is what we send to peers so they know our state.
    Redacts sensitive fields for guest trust contexts.
    """
    import socket
    hostname = socket.gethostname()

    # Stable genome hash from instance_id (not real genome, just identity fingerprint)
    genome_hash = hashlib.sha256(instance_id.encode()).hexdigest()[:8]

    beacon = {
        "instance_id": instance_id,
        "version": version,
        "hostname": hostname,
        "port": port,
        "drives": drives or {},
        "emotional_valence": round(emotional_valence, 3),
        "available": available,
        "capacity": round(capacity, 2),
        "genome_hash": genome_hash,
        "capabilities": capabilities or [],
        "timestamp": time.time(),
    }
    return beacon


def redact_beacon_for_guest(beacon: dict) -> dict:
    """Return a guest-safe version of a beacon (no drives, no valence, no genome hash)."""
    return {
        "instance_id": beacon.get("instance_id"),
        "version": beacon.get("version"),
        "available": beacon.get("available"),
        "capabilities": beacon.get("capabilities", []),
        "timestamp": beacon.get("timestamp"),
    }


# ── Staleness & pruning ────────────────────────────────────────────────────────

def mark_stale_peers() -> list:
    """Mark peers as offline if they haven't sent a beacon recently.

    Returns list of peer_ids that were marked offline.
    """
    state = _load_state()
    now = time.time()
    newly_offline = []

    for peer_id, peer in state["peers"].items():
        if peer.get("status") == "online":
            idle = now - peer.get("last_seen", 0)
            if idle > STALE_TIMEOUT_SECS:
                peer["status"] = "offline"
                newly_offline.append(peer_id)
                thalamus.append({
                    "source": "PNEUMA",
                    "event": "peer_went_offline",
                    "peer_id": peer_id,
                    "idle_seconds": round(idle),
                })

    if newly_offline:
        _save_state(state)

    return newly_offline


def prune_dead_peers() -> list:
    """Remove peers that have been offline for longer than DEAD_TIMEOUT_SECS.

    Returns list of pruned peer_ids.
    """
    state = _load_state()
    now = time.time()
    pruned = []

    to_remove = []
    for peer_id, peer in state["peers"].items():
        if peer.get("trust_level") == TRUST_LOCAL:
            continue  # Never auto-prune local peers
        if peer.get("status") == "offline":
            idle = now - peer.get("last_seen", 0)
            if idle > DEAD_TIMEOUT_SECS:
                to_remove.append(peer_id)

    for peer_id in to_remove:
        del state["peers"][peer_id]
        pruned.append(peer_id)
        state["peers_pruned"] = state.get("peers_pruned", 0) + 1
        thalamus.append({
            "source": "PNEUMA",
            "event": "peer_pruned",
            "peer_id": peer_id,
        })

    if pruned:
        _save_state(state)

    return pruned


# ── Status & loop hooks ────────────────────────────────────────────────────────

def get_status() -> dict:
    """Return a summary of pneuma state for THALAMUS / observation API."""
    state = _load_state()
    peers = state.get("peers", {})
    online = [p for p in peers.values() if p.get("status") == "online"]
    trusted = [p for p in peers.values() if p.get("trust_level") == TRUST_TRUSTED]

    return {
        "total_peers": len(peers),
        "online_peers": len(online),
        "trusted_peers": len(trusted),
        "beacons_sent": state.get("beacons_sent", 0),
        "beacons_received": state.get("beacons_received", 0),
        "peers_registered": state.get("peers_registered", 0),
        "peers_pruned": state.get("peers_pruned", 0),
        "last_beacon_sent": state.get("last_beacon_sent", 0),
    }


def should_run(loop_count: int) -> bool:
    """Return True if it's time to run pneuma housekeeping this loop."""
    return loop_count > 0 and loop_count % LOOP_INTERVAL == 0


def update(loop_count: int, instance_id: str = "iris-primary") -> Optional[dict]:
    """Called from nervous_system.post_loop(). Runs housekeeping on schedule.

    Marks stale peers, prunes dead peers, emits status to THALAMUS.
    Returns status dict if ran, None if skipped.
    """
    if not should_run(loop_count):
        return None

    newly_offline = mark_stale_peers()
    pruned = prune_dead_peers()
    status = get_status()

    if status["total_peers"] > 0 or newly_offline or pruned:
        thalamus.append({
            "source": "PNEUMA",
            "event": "housekeeping",
            "loop_count": loop_count,
            **status,
        })

    return status


# ── Self-test ──────────────────────────────────────────────────────────────────

def _run_tests():
    """Quick smoke test — not a substitute for pytest."""
    import tempfile, os

    # Patch state dir to temp
    global _DEFAULT_STATE_DIR, _DEFAULT_PEERS_FILE
    with tempfile.TemporaryDirectory() as tmp:
        orig_dir = _DEFAULT_STATE_DIR
        orig_file = _DEFAULT_PEERS_FILE
        _DEFAULT_STATE_DIR = Path(tmp) / "pneuma"
        _DEFAULT_PEERS_FILE = _DEFAULT_STATE_DIR / "peers.json"

        try:
            # Register a peer
            rec = register_peer("scout", "http://192.168.1.5:9720", TRUST_TRUSTED, ["web_search"])
            assert rec["peer_id"] == "scout"
            assert rec["trust_level"] == TRUST_TRUSTED
            assert rec["status"] == "online"

            # List peers
            peers = list_peers()
            assert len(peers) == 1

            # Build beacon
            beacon = build_self_beacon("iris-primary", drives={"goals": 0.45})
            assert "instance_id" in beacon
            assert beacon["drives"]["goals"] == 0.45

            # Receive beacon
            beacon["instance_id"] = "forge"
            beacon["endpoint"] = "http://192.168.1.6:9720"
            peer = receive_beacon(beacon)
            assert peer["peer_id"] == "forge"
            assert peer["trust_level"] == TRUST_GUEST  # auto-registered as guest

            # Status
            status = get_status()
            assert status["total_peers"] == 2
            assert status["online_peers"] == 2

            # Deregister
            ok = deregister_peer("scout")
            assert ok
            assert len(list_peers()) == 1

            print("PNEUMA smoke tests passed ✓")

        finally:
            _DEFAULT_STATE_DIR = orig_dir
            _DEFAULT_PEERS_FILE = orig_file


if __name__ == "__main__":
    _run_tests()
