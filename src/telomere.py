"""TELOMERE — Identity Integrity Tracker for Pulse.

Tracks session count, uptime, SOUL.md hash vs monthly snapshots.
Identity drift score 0-1. Memory completeness %. Flags drift >0.3 as AMYGDALA threat.
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "telomere-state.json"
_DEFAULT_SNAPSHOT_DIR = _DEFAULT_STATE_DIR / "telomere" / "snapshots"
SOUL_PATH = Path.home() / ".openclaw" / "workspace" / "SOUL.md"
MEMORY_DIR = Path.home() / ".openclaw" / "workspace" / "memory"
DRIFT_THRESHOLD = 0.3


def _load_state() -> dict:
    if _DEFAULT_STATE_FILE.exists():
        try:
            return json.loads(_DEFAULT_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "session_count": 0,
        "total_uptime_seconds": 0,
        "current_soul_hash": "",
        "snapshots": [],
        "drift_score": 0.0,
        "memory_completeness": 0.0,
        "last_check": 0,
        "session_start": time.time(),
    }


def _save_state(state: dict):
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    _DEFAULT_STATE_FILE.write_text(json.dumps(state, indent=2))


def _hash_file(path: Path) -> str:
    if path.exists():
        return hashlib.sha256(path.read_text().encode()).hexdigest()[:16]
    return ""


def _compute_memory_completeness() -> float:
    """Estimate memory completeness based on daily files existing."""
    if not MEMORY_DIR.exists():
        return 0.0
    files = list(MEMORY_DIR.glob("*.md"))
    # Simple heuristic: more files = more complete, cap at 30 days
    return min(1.0, len(files) / 30.0)


def _compute_drift(current_hash: str, snapshots: list) -> float:
    """Compute identity drift score 0-1 based on hash changes over time."""
    if not snapshots or not current_hash:
        return 0.0
    # Count how many snapshots differ from current
    different = sum(1 for s in snapshots if s.get("hash", "") != current_hash)
    return min(1.0, different / max(len(snapshots), 1))


def start_session() -> dict:
    """Called at session start. Increments session count."""
    state = _load_state()
    state["session_count"] += 1
    state["session_start"] = time.time()
    _save_state(state)
    return state


def check_identity() -> dict:
    """Run identity integrity check. Returns status dict."""
    state = _load_state()
    
    current_hash = _hash_file(SOUL_PATH)
    state["current_soul_hash"] = current_hash
    
    # Compute drift
    drift = _compute_drift(current_hash, state["snapshots"])
    state["drift_score"] = drift
    
    # Memory completeness
    state["memory_completeness"] = _compute_memory_completeness()
    
    # Update uptime
    if state.get("session_start"):
        state["total_uptime_seconds"] += time.time() - state["session_start"]
        state["session_start"] = time.time()
    
    state["last_check"] = time.time()
    _save_state(state)
    
    result = {
        "session_count": state["session_count"],
        "drift_score": drift,
        "memory_completeness": state["memory_completeness"],
        "soul_hash": current_hash,
        "uptime_hours": state["total_uptime_seconds"] / 3600,
    }
    
    # Flag high drift as AMYGDALA threat
    if drift > DRIFT_THRESHOLD:
        thalamus.append({
            "source": "telomere",
            "type": "identity_drift_alert",
            "salience": 0.8,
            "data": {
                "drift_score": drift,
                "threshold": DRIFT_THRESHOLD,
                "action": "amygdala_threat",
            },
        })
    
    thalamus.append({
        "source": "telomere",
        "type": "identity_check",
        "salience": 0.3,
        "data": result,
    })
    
    return result


def take_snapshot() -> dict:
    """Take a monthly snapshot of SOUL.md hash."""
    _DEFAULT_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    
    current_hash = _hash_file(SOUL_PATH)
    snapshot = {
        "ts": time.time(),
        "hash": current_hash,
        "month": time.strftime("%Y-%m"),
    }
    
    # Save snapshot file
    snap_file = _DEFAULT_SNAPSHOT_DIR / f"{snapshot['month']}.json"
    snap_file.write_text(json.dumps(snapshot, indent=2))
    
    # Update state
    state = _load_state()
    state["snapshots"].append(snapshot)
    state["snapshots"] = state["snapshots"][-12:]  # keep last 12 months
    _save_state(state)
    
    return snapshot


def emit_need_signals() -> dict:
    """Check identity drift and emit HYPOTHALAMUS need signals."""
    try:
        state = _load_state()
    except Exception:
        return {}

    signals = {}
    drift = state.get("drift_score", 0.0)

    if drift > 0.3:
        from pulse.src import hypothalamus
        hypothalamus.record_need_signal("realign_identity", "telomere")
        signals["realign_identity"] = drift

    return signals


def get_status() -> dict:
    """Return current telomere status."""
    state = _load_state()
    return {
        "session_count": state["session_count"],
        "drift_score": state["drift_score"],
        "memory_completeness": state["memory_completeness"],
        "soul_hash": state["current_soul_hash"],
        "total_uptime_hours": state["total_uptime_seconds"] / 3600,
        "snapshots_count": len(state["snapshots"]),
    }
