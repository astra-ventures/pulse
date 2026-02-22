"""HYPOTHALAMUS — Meta-Drive Layer for Pulse.

Listens to THALAMUS bus for recurring need_signal events.
3+ signals from different modules → births new drive at weight 1.0.
Drives at weight floor for 30 days → retired.
"""

import json
import time
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

STATE_DIR = Path.home() / ".pulse" / "state"
STATE_FILE = STATE_DIR / "hypothalamus-state.json"

SIGNAL_THRESHOLD = 3  # signals from different modules needed to birth a drive
RETIREMENT_DAYS = 30
WEIGHT_FLOOR = 0.1

# Needs that are harder to observe across many modules get a lower birth threshold.
# "connection" may only be signaled by 1-2 modules (e.g. social sensor + emotions)
# even after a full day of absence, so requiring 3 is too conservative.
REDUCED_THRESHOLD_NEEDS = {"connection", "social", "belonging", "companionship"}


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "pending_signals": {},  # need_name → {modules: set-as-list, first_seen, last_seen, count}
        "active_drives": {},    # drive_name → {weight, born_ts, last_active_ts, source_modules}
        "retired_drives": [],
        "last_scan": 0,
    }


def _save_state(state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def record_need_signal(need_name: str, source_module: str) -> dict:
    """Record a need signal from a module. May birth a drive."""
    state = _load_state()
    now = time.time()
    
    if need_name not in state["pending_signals"]:
        state["pending_signals"][need_name] = {
            "modules": [],
            "first_seen": now,
            "last_seen": now,
            "count": 0,
        }
    
    pending = state["pending_signals"][need_name]
    if source_module not in pending["modules"]:
        pending["modules"].append(source_module)
    pending["last_seen"] = now
    pending["count"] += 1
    
    result = {"need": need_name, "module_count": len(pending["modules"]), "birthed": False}

    # Check if threshold met and not already an active drive
    threshold = 2 if need_name in REDUCED_THRESHOLD_NEEDS else SIGNAL_THRESHOLD
    if len(pending["modules"]) >= threshold and need_name not in state["active_drives"]:
        state["active_drives"][need_name] = {
            "weight": 1.0,
            "born_ts": now,
            "last_active_ts": now,
            "source_modules": pending["modules"][:],
            "at_floor_since": None,
        }
        del state["pending_signals"][need_name]
        result["birthed"] = True
        
        thalamus.append({
            "source": "hypothalamus",
            "type": "drive_born",
            "salience": 0.7,
            "data": {"drive": need_name, "source_modules": result.get("source_modules", pending["modules"])},
        })
    
    _save_state(state)
    return result


def scan_drives() -> dict:
    """Periodic scan: decay weights, retire stale drives."""
    state = _load_state()
    now = time.time()
    retired = []
    
    for name, drive in list(state["active_drives"].items()):
        # Natural weight decay
        age_days = (now - drive["born_ts"]) / 86400
        if age_days > 7:  # start decaying after 1 week
            drive["weight"] = max(WEIGHT_FLOOR, drive["weight"] - 0.01)
        
        # Track time at floor
        if drive["weight"] <= WEIGHT_FLOOR:
            if drive["at_floor_since"] is None:
                drive["at_floor_since"] = now
            elif (now - drive["at_floor_since"]) / 86400 >= RETIREMENT_DAYS:
                retired.append(name)
        else:
            drive["at_floor_since"] = None
    
    for name in retired:
        drive = state["active_drives"].pop(name)
        state["retired_drives"].append({
            "name": name,
            "retired_ts": now,
            "lifespan_days": (now - drive["born_ts"]) / 86400,
        })
        state["retired_drives"] = state["retired_drives"][-50:]
        
        thalamus.append({
            "source": "hypothalamus",
            "type": "drive_retired",
            "salience": 0.4,
            "data": {"drive": name},
        })
    
    state["last_scan"] = now
    _save_state(state)
    
    return {
        "active_drives": len(state["active_drives"]),
        "retired": retired,
        "pending_signals": len(state["pending_signals"]),
    }


def reinforce_drive(drive_name: str, amount: float = 0.1):
    """Reinforce an active drive's weight."""
    state = _load_state()
    if drive_name in state["active_drives"]:
        drive = state["active_drives"][drive_name]
        drive["weight"] = min(1.0, drive["weight"] + amount)
        drive["last_active_ts"] = time.time()
        drive["at_floor_since"] = None
        _save_state(state)


def get_active_drives() -> dict:
    """Return all active drives."""
    state = _load_state()
    return dict(state["active_drives"])


def get_status() -> dict:
    """Return hypothalamus status."""
    state = _load_state()
    return {
        "active_drives": len(state["active_drives"]),
        "pending_signals": len(state["pending_signals"]),
        "retired_total": len(state["retired_drives"]),
        "drives": {k: v["weight"] for k, v in state["active_drives"].items()},
    }
