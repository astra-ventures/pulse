"""OXIMETER — External Perception Tracker for Pulse.

Track engagement metrics (followers, likes, sentiment).
Compare self-perception vs external. Detect gaps.
"""

import json
import time
from pathlib import Path

from pulse.src import thalamus

STATE_DIR = Path.home() / ".pulse" / "state"
STATE_FILE = STATE_DIR / "oximeter-state.json"


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
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


def _save_state(state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


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
