"""OXIMETER — External Perception Tracker for Pulse.

Track engagement metrics (followers, likes, sentiment).
Compare self-perception vs external. Detect gaps.
"""

import copy
import json
import time
from pathlib import Path

from pulse.src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "oximeter-state.json"

_DEFAULT_STATE = {
    "metrics": {
        "followers": 0,
        "likes": 0,
        "replies": 0,
        "sentiment": 0.5,  # 0=negative, 1=positive
    },
    "self_perception": {
        "impact": 0.5,
        "reception": 0.5,
    },
    "perception_gap": 0.0,
    "history": [],
    "last_update": 0,
}


def _load_state() -> dict:
    if _DEFAULT_STATE_FILE.exists():
        try:
            raw = json.loads(_DEFAULT_STATE_FILE.read_text())
            # Migrate old schema — inject any missing top-level keys
            for key, val in _DEFAULT_STATE.items():
                if key not in raw:
                    raw[key] = copy.deepcopy(val)
            # Migrate old metrics — inject missing metric fields
            for key, val in _DEFAULT_STATE["metrics"].items():
                if key not in raw.get("metrics", {}):
                    raw.setdefault("metrics", {})[key] = val
            return raw
        except (json.JSONDecodeError, OSError):
            pass
    return copy.deepcopy(_DEFAULT_STATE)


def _save_state(state: dict):
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    _DEFAULT_STATE_FILE.write_text(json.dumps(state, indent=2))


def update_metrics(followers: int = None, likes: int = None, replies: int = None, sentiment: float = None) -> dict:
    """Update external metrics."""
    state = _load_state()
    m = state["metrics"]
    if followers is not None:
        m["followers"] = followers
    if likes is not None:
        m["likes"] = likes
    if replies is not None:
        m["replies"] = replies
    if sentiment is not None:
        m["sentiment"] = max(0.0, min(1.0, sentiment))
    state["last_update"] = time.time()
    _save_state(state)
    return dict(m)


def update_self_perception(impact: float = None, reception: float = None) -> dict:
    """Update self-perception scores."""
    state = _load_state()
    sp = state["self_perception"]
    if impact is not None:
        sp["impact"] = max(0.0, min(1.0, impact))
    if reception is not None:
        sp["reception"] = max(0.0, min(1.0, reception))
    state["last_update"] = time.time()
    _save_state(state)
    return dict(sp)


def detect_gap() -> dict:
    """Compare self-perception vs external reality. Returns gap analysis."""
    state = _load_state()
    m = state["metrics"]
    sp = state["self_perception"]
    
    # Normalize external metrics to 0-1 scale
    ext_impact = min(1.0, m["followers"] / 10000) if m["followers"] else 0.0
    ext_reception = m["sentiment"]
    
    impact_gap = abs(sp["impact"] - ext_impact)
    reception_gap = abs(sp["reception"] - ext_reception)
    overall_gap = (impact_gap + reception_gap) / 2
    
    state["perception_gap"] = overall_gap
    state["history"].append({"ts": time.time(), "gap": overall_gap})
    state["history"] = state["history"][-100:]
    _save_state(state)
    
    result = {
        "impact_gap": round(impact_gap, 3),
        "reception_gap": round(reception_gap, 3),
        "overall_gap": round(overall_gap, 3),
        "self_overestimates": sp["impact"] > ext_impact,
    }
    
    if overall_gap > 0.3:
        thalamus.append({
            "source": "oximeter",
            "type": "perception_gap",
            "salience": 0.5,
            "data": result,
        })
    
    return result


def get_status() -> dict:
    """Return oximeter status."""
    state = _load_state()
    return {
        "metrics": state["metrics"],
        "self_perception": state["self_perception"],
        "perception_gap": state["perception_gap"],
    }
