"""AXON — Cross-Peer Task Delegation Engine.

In neuroscience, an axon is the long projection of a neuron that carries
signals *away* from the cell body toward target neurons. It's the transmission
wire of the nervous system — fast, directed, and purpose-built for delivery.

For Pulse, AXON is the directed task delegation layer in a Pneuma constellation:
one Pulse instance can inject a drive spike or work task into a peer instance.
Where SYNAPSE handles weighted signal passing *within* a machine, and PNEUMA
handles peer discovery *between* machines, AXON handles actual *work* delegation:

  "Pulse A says: I need Pulse B to focus on GOALS with high urgency."
  "Pulse B receives the delegation, injects the drive spike, acknowledges."

Key concepts:
- Delegation: a structured task request from one peer to another
- Drive injection: receiver bumps a specific drive's pressure on receipt
- Payload: optional context/instructions delivered with the delegation
- Acknowledgment: receiver confirms receipt; sender tracks delivery state
- Expiry: unacknowledged tasks expire and can be re-delegated or dropped
- Priority: delegations carry priority levels (critical / high / normal / low)

Phase 2 API endpoints (observation_api.py):
  POST /axon/delegate      → send a delegation to a registered peer
  GET  /axon/inbox         → list pending delegations received by this instance
  POST /axon/ack           → acknowledge a received delegation
  GET  /axon/outbox        → list delegations sent, with delivery status
  DELETE /axon/delegation  → cancel a pending outbound delegation

Trust gate: only TRUST_TRUSTED or TRUST_LOCAL peers can inject delegations.
TRUST_GUEST peers are read-only (can receive status beacons but cannot delegate).
"""

import json
import time
import uuid
from pathlib import Path
from typing import Optional

from src import pneuma as _pneuma

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state" / "axon"
_DEFAULT_INBOX_FILE = _DEFAULT_STATE_DIR / "inbox.json"
_DEFAULT_OUTBOX_FILE = _DEFAULT_STATE_DIR / "outbox.json"

# Priority levels
PRIORITY_CRITICAL = "critical"   # Inject at full pressure, bypass throttle
PRIORITY_HIGH = "high"           # Inject at 0.8× pressure
PRIORITY_NORMAL = "normal"       # Inject at 0.5× pressure (default)
PRIORITY_LOW = "low"             # Inject at 0.25× pressure

ALL_PRIORITIES = (PRIORITY_CRITICAL, PRIORITY_HIGH, PRIORITY_NORMAL, PRIORITY_LOW)

PRIORITY_MULTIPLIERS = {
    PRIORITY_CRITICAL: 1.0,
    PRIORITY_HIGH: 0.8,
    PRIORITY_NORMAL: 0.5,
    PRIORITY_LOW: 0.25,
}

# Delivery states
STATE_PENDING = "pending"       # Sent, not yet acknowledged
STATE_ACKED = "acked"           # Target confirmed receipt
STATE_EXPIRED = "expired"       # Timed out without ack
STATE_FAILED = "failed"         # Delivery error
STATE_CANCELLED = "cancelled"   # Sender cancelled before delivery

# Timeouts
DEFAULT_TTL_SECS = 3600         # 1h — delegation expires if unacked
MAX_INBOX_SIZE = 100            # Drop oldest if inbox overflows
MAX_OUTBOX_SIZE = 200


# ── State helpers ──────────────────────────────────────────────────────────────

def _load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {"items": [], "updated_at": 0}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = time.time()
    path.write_text(json.dumps(data, indent=2))


# ── Delegation factory ─────────────────────────────────────────────────────────

def _new_delegation(
    sender_id: str,
    target_peer_id: str,
    drive: str,
    pressure: float,
    payload: Optional[dict] = None,
    priority: str = PRIORITY_NORMAL,
    ttl: int = DEFAULT_TTL_SECS,
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "sender_id": sender_id,
        "target_peer_id": target_peer_id,
        "drive": drive,
        "pressure": max(0.0, min(1.0, pressure)),
        "priority": priority if priority in ALL_PRIORITIES else PRIORITY_NORMAL,
        "payload": payload or {},
        "state": STATE_PENDING,
        "created_at": time.time(),
        "expires_at": time.time() + ttl,
        "acked_at": None,
    }


# ── Outbox: delegations sent by THIS instance ──────────────────────────────────

def send_delegation(
    drive: str,
    pressure: float,
    target_peer_id: str,
    payload: Optional[dict] = None,
    priority: str = PRIORITY_NORMAL,
    ttl: int = DEFAULT_TTL_SECS,
    state_dir: Path = _DEFAULT_STATE_DIR,
) -> dict:
    """Create a delegation and add it to the outbox for delivery to a peer.

    The actual HTTP delivery to the peer happens via the observation_api layer
    (POST /axon/delegate). This function only manages local outbox state.

    Returns the delegation dict (with id, state=pending, etc.).
    """
    outbox_path = state_dir / "outbox.json"
    data = _load(outbox_path)

    # Build sender identity from PNEUMA self-beacon
    beacon = _pneuma.build_self_beacon()
    sender_id = beacon.get("instance_id", "unknown")

    delegation = _new_delegation(
        sender_id=sender_id,
        target_peer_id=target_peer_id,
        drive=drive,
        pressure=pressure,
        payload=payload,
        priority=priority,
        ttl=ttl,
    )

    data["items"].append(delegation)

    # Trim outbox if too large (keep most recent)
    if len(data["items"]) > MAX_OUTBOX_SIZE:
        data["items"] = data["items"][-MAX_OUTBOX_SIZE:]

    _save(outbox_path, data)
    return delegation


def mark_outbox_acked(delegation_id: str, state_dir: Path = _DEFAULT_STATE_DIR) -> bool:
    """Mark an outbound delegation as acknowledged by the peer."""
    outbox_path = state_dir / "outbox.json"
    data = _load(outbox_path)
    for item in data["items"]:
        if item["id"] == delegation_id and item["state"] == STATE_PENDING:
            item["state"] = STATE_ACKED
            item["acked_at"] = time.time()
            _save(outbox_path, data)
            return True
    return False


def cancel_delegation(delegation_id: str, state_dir: Path = _DEFAULT_STATE_DIR) -> bool:
    """Cancel a pending outbound delegation before it's delivered."""
    outbox_path = state_dir / "outbox.json"
    data = _load(outbox_path)
    for item in data["items"]:
        if item["id"] == delegation_id and item["state"] == STATE_PENDING:
            item["state"] = STATE_CANCELLED
            _save(outbox_path, data)
            return True
    return False


def list_outbox(
    states: Optional[list] = None,
    state_dir: Path = _DEFAULT_STATE_DIR,
) -> list:
    """Return outbound delegations, optionally filtered by state list."""
    data = _load(state_dir / "outbox.json")
    items = data["items"]
    if states:
        items = [i for i in items if i["state"] in states]
    return items


def expire_stale_outbox(state_dir: Path = _DEFAULT_STATE_DIR) -> int:
    """Mark pending outbound delegations past their TTL as expired. Returns count."""
    outbox_path = state_dir / "outbox.json"
    data = _load(outbox_path)
    now = time.time()
    count = 0
    for item in data["items"]:
        if item["state"] == STATE_PENDING and now > item["expires_at"]:
            item["state"] = STATE_EXPIRED
            count += 1
    if count:
        _save(outbox_path, data)
    return count


# ── Inbox: delegations received FROM peers ─────────────────────────────────────

def receive_delegation(
    delegation: dict,
    state_dir: Path = _DEFAULT_STATE_DIR,
) -> tuple[bool, str]:
    """Accept an incoming delegation from a peer and add it to the inbox.

    Trust check: delegation must come from a TRUSTED or LOCAL peer (enforced
    at the HTTP layer in observation_api.py before calling this).

    Returns (accepted: bool, reason: str).
    """
    inbox_path = state_dir / "inbox.json"
    data = _load(inbox_path)

    # Validate required fields
    required = ("id", "sender_id", "drive", "pressure", "priority", "expires_at")
    for field in required:
        if field not in delegation:
            return False, f"missing field: {field}"

    # Reject if already expired
    if time.time() > delegation["expires_at"]:
        return False, "delegation already expired"

    # Idempotency: don't re-add if we already have it
    existing_ids = {item["id"] for item in data["items"]}
    if delegation["id"] in existing_ids:
        return True, "already received"

    # Stamp receipt time
    entry = dict(delegation)
    entry["received_at"] = time.time()
    entry["state"] = STATE_PENDING

    data["items"].append(entry)

    # Trim inbox if overflow (drop oldest)
    if len(data["items"]) > MAX_INBOX_SIZE:
        data["items"] = data["items"][-MAX_INBOX_SIZE:]

    _save(inbox_path, data)
    return True, "accepted"


def acknowledge_delegation(
    delegation_id: str,
    state_dir: Path = _DEFAULT_STATE_DIR,
) -> bool:
    """Mark a received delegation as acknowledged (we've processed it)."""
    inbox_path = state_dir / "inbox.json"
    data = _load(inbox_path)
    for item in data["items"]:
        if item["id"] == delegation_id and item["state"] == STATE_PENDING:
            item["state"] = STATE_ACKED
            item["acked_at"] = time.time()
            _save(inbox_path, data)
            return True
    return False


def list_inbox(
    states: Optional[list] = None,
    state_dir: Path = _DEFAULT_STATE_DIR,
) -> list:
    """Return received delegations, optionally filtered by state."""
    data = _load(state_dir / "inbox.json")
    items = data["items"]
    if states:
        items = [i for i in items if i["state"] in states]
    return items


def pop_pending_delegations(state_dir: Path = _DEFAULT_STATE_DIR) -> list:
    """Return pending inbox delegations and mark them as acked atomically.

    This is the primary consumption path: the CORTEX loop calls this each cycle,
    injects the delegated drive spikes, then they're marked consumed.
    """
    inbox_path = state_dir / "inbox.json"
    data = _load(inbox_path)
    now = time.time()
    pending = []
    for item in data["items"]:
        if item["state"] == STATE_PENDING:
            if now <= item["expires_at"]:
                item["state"] = STATE_ACKED
                item["acked_at"] = now
                pending.append(item)
            else:
                item["state"] = STATE_EXPIRED
    expired_found = any(i["state"] == STATE_EXPIRED for i in data["items"])
    if pending or expired_found:
        _save(inbox_path, data)
    return pending


# ── Drive injection helper ─────────────────────────────────────────────────────

def compute_injected_pressure(delegation: dict) -> float:
    """Return the effective pressure to inject into the local drive system.

    Applies the priority multiplier and clamps to [0.0, 1.0].
    """
    base = delegation.get("pressure", 0.5)
    multiplier = PRIORITY_MULTIPLIERS.get(delegation.get("priority", PRIORITY_NORMAL), 0.5)
    return max(0.0, min(1.0, base * multiplier))


# ── Summary ────────────────────────────────────────────────────────────────────

def summary(state_dir: Path = _DEFAULT_STATE_DIR) -> dict:
    """Return a brief status dict for logging / API exposure."""
    inbox = _load(state_dir / "inbox.json")
    outbox = _load(state_dir / "outbox.json")

    inbox_by_state = {}
    for item in inbox["items"]:
        inbox_by_state[item["state"]] = inbox_by_state.get(item["state"], 0) + 1

    outbox_by_state = {}
    for item in outbox["items"]:
        outbox_by_state[item["state"]] = outbox_by_state.get(item["state"], 0) + 1

    return {
        "inbox": inbox_by_state,
        "outbox": outbox_by_state,
        "inbox_total": len(inbox["items"]),
        "outbox_total": len(outbox["items"]),
    }
