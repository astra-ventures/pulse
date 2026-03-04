"""SYNAPSE — Signal Junction & Weighted Inter-Agent Transmission.

In neuroscience, a synapse is the junction between two neurons where signal
transmission occurs — with adjustable strength, direction, and modulation.
Repeated activation strengthens connections (potentiation); disuse weakens them
(depression); pruning removes connections that fall below a threshold.

For Pulse, SYNAPSE handles the *mechanics* of agent-to-agent signal passing
within a constellation. AURA does ambient broadcast; DENDRITE does the social
graph; SYNAPSE does the weighted, directional junction logic.

Key concepts:
- Each (source, target) pair has a synaptic weight [0.0–2.0]
- Signals are typed: excitatory (boosts target drives) or inhibitory (dampens)
- Short-term potentiation: firing a connection raises its weight slightly
- Short-term depression: idle connections decay toward baseline
- Pruning: weights below threshold get removed (synaptic pruning)
- Pending queue: signals buffered until target polls
"""

import json
import time
from pathlib import Path
from typing import Optional

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "synapse-state.json"

# Signal types
EXCITATORY = "excitatory"   # boosts target drive pressure
INHIBITORY = "inhibitory"   # dampens target drive pressure
MODULATORY = "modulatory"   # adjusts target thresholds

# Synaptic weight bounds
WEIGHT_MIN = 0.05
WEIGHT_MAX = 2.0
WEIGHT_BASELINE = 1.0

# Potentiation / depression rates
POTENTIATION_STEP = 0.05   # weight increase per firing
DEPRESSION_RATE = 0.02     # weight decrease per hour of idle
PRUNE_THRESHOLD = 0.1      # remove connections below this weight

# Max pending signals per target
MAX_PENDING = 50


def _default_state() -> dict:
    return {
        "connections": {},   # "source->target": {weight, signal_type, last_fired, fire_count}
        "pending": [],       # [{source, target, signal_type, strength, payload, ts}]
        "fired_total": 0,
        "pruned_total": 0,
    }


def _load_state() -> dict:
    if _DEFAULT_STATE_FILE.exists():
        try:
            return json.loads(_DEFAULT_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return _default_state()


def _save_state(state: dict):
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    _DEFAULT_STATE_FILE.write_text(json.dumps(state, indent=2))


def _conn_key(source: str, target: str) -> str:
    return f"{source}->{target}"


# ── Core transmission ──────────────────────────────────────────────────────────

def transmit(
    source: str,
    target: str,
    signal_type: str = EXCITATORY,
    strength: float = 1.0,
    payload: Optional[dict] = None,
) -> dict:
    """Fire a signal from source → target through the synapse.

    Applies potentiation to the connection weight, queues the signal for the
    target to receive, and returns the transmission record.

    Args:
        source: name of the sending agent/module
        target: name of the receiving agent/module
        signal_type: "excitatory", "inhibitory", or "modulatory"
        strength: 0.0–1.0 raw signal strength (scaled by synaptic weight)
        payload: optional structured data to pass with the signal

    Returns:
        The transmission record dict.
    """
    state = _load_state()
    now = time.time()
    key = _conn_key(source, target)

    # Ensure connection exists
    if key not in state["connections"]:
        state["connections"][key] = {
            "weight": WEIGHT_BASELINE,
            "signal_type": signal_type,
            "last_fired": None,
            "fire_count": 0,
        }

    conn = state["connections"][key]

    # Short-term potentiation
    conn["weight"] = min(WEIGHT_MAX, conn["weight"] + POTENTIATION_STEP)
    conn["last_fired"] = now
    conn["fire_count"] += 1
    conn["signal_type"] = signal_type  # update type on latest fire

    # Effective strength = raw strength × synaptic weight
    effective_strength = min(1.0, strength * conn["weight"])

    record = {
        "source": source,
        "target": target,
        "signal_type": signal_type,
        "strength": strength,
        "effective_strength": effective_strength,
        "payload": payload or {},
        "ts": now,
    }

    # Queue for target (cap pending queue)
    state["pending"] = [p for p in state["pending"] if p["target"] != target or
                        len([x for x in state["pending"] if x["target"] == target]) < MAX_PENDING]
    state["pending"].append(record)
    state["fired_total"] += 1

    _save_state(state)
    return record


def receive(target: str, clear: bool = True) -> list:
    """Collect all pending signals for a target agent.

    Args:
        target: the receiving agent name
        clear: if True, remove collected signals from queue (default)

    Returns:
        List of pending signal records for this target.
    """
    state = _load_state()
    signals = [p for p in state["pending"] if p["target"] == target]

    if clear and signals:
        state["pending"] = [p for p in state["pending"] if p["target"] != target]
        _save_state(state)

    return signals


def get_weight(source: str, target: str) -> float:
    """Return current synaptic weight for a source→target connection (0.0 if unknown)."""
    state = _load_state()
    conn = state["connections"].get(_conn_key(source, target))
    return conn["weight"] if conn else 0.0


# ── Modulation ─────────────────────────────────────────────────────────────────

def potentiate(source: str, target: str, amount: float = POTENTIATION_STEP) -> float:
    """Manually strengthen a connection. Returns new weight."""
    state = _load_state()
    key = _conn_key(source, target)
    if key not in state["connections"]:
        state["connections"][key] = {
            "weight": WEIGHT_BASELINE,
            "signal_type": EXCITATORY,
            "last_fired": None,
            "fire_count": 0,
        }
    conn = state["connections"][key]
    conn["weight"] = min(WEIGHT_MAX, conn["weight"] + amount)
    _save_state(state)
    return conn["weight"]


def depress(source: str, target: str, amount: float = DEPRESSION_RATE) -> float:
    """Manually weaken a connection. Returns new weight."""
    state = _load_state()
    key = _conn_key(source, target)
    conn = state["connections"].get(key)
    if not conn:
        return 0.0
    conn["weight"] = max(WEIGHT_MIN, conn["weight"] - amount)
    _save_state(state)
    return conn["weight"]


# ── Maintenance ────────────────────────────────────────────────────────────────

def tick(hours: float = 1.0):
    """Apply time-based synaptic depression to all connections.

    Connections that haven't fired recently lose weight toward baseline.
    Call this periodically (e.g., hourly cron) to prevent stale hyperconnection.
    """
    state = _load_state()
    now = time.time()

    for key, conn in state["connections"].items():
        last = conn.get("last_fired")
        if last is None:
            continue
        hours_idle = (now - last) / 3600.0
        if hours_idle > 0:
            decay = DEPRESSION_RATE * hours_idle
            conn["weight"] = max(WEIGHT_MIN, conn["weight"] - decay)

    _save_state(state)


def prune(threshold: float = PRUNE_THRESHOLD) -> int:
    """Remove connections whose weight has fallen below the pruning threshold.

    Returns the number of connections pruned.
    """
    state = _load_state()
    before = len(state["connections"])
    state["connections"] = {
        k: v for k, v in state["connections"].items()
        if v["weight"] >= threshold
    }
    pruned = before - len(state["connections"])
    state["pruned_total"] += pruned
    _save_state(state)
    return pruned


def get_weights() -> dict:
    """Return all current synaptic weights as {conn_key: weight}."""
    state = _load_state()
    return {k: v["weight"] for k, v in state["connections"].items()}


def get_connections() -> list:
    """Return all connections with full metadata."""
    state = _load_state()
    result = []
    for key, conn in state["connections"].items():
        source, target = key.split("->", 1)
        result.append({
            "source": source,
            "target": target,
            "weight": conn["weight"],
            "signal_type": conn["signal_type"],
            "last_fired": conn["last_fired"],
            "fire_count": conn["fire_count"],
        })
    return result


def get_stats() -> dict:
    """Return transmission statistics."""
    state = _load_state()
    return {
        "connection_count": len(state["connections"]),
        "pending_count": len(state["pending"]),
        "fired_total": state["fired_total"],
        "pruned_total": state["pruned_total"],
    }


def reset():
    """Clear all synaptic state. Used in tests / hard resets."""
    _save_state(_default_state())
