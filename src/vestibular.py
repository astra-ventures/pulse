"""VESTIBULAR — Balance Monitor for Pulse.

Tracks ratios: building/shipping, working/reflecting, autonomy/collaboration.
Imbalance → THALAMUS need_signal for HYPOTHALAMUS.
"""

import json
import time
from pathlib import Path

from pulse.src import thalamus

STATE_DIR = Path.home() / ".pulse" / "state"
STATE_FILE = STATE_DIR / "vestibular-state.json"

# Healthy ranges for each ratio (min, max)
HEALTHY_RANGES = {
    "building_shipping": (0.3, 0.7),       # 30-70% building vs shipping
    "working_reflecting": (0.4, 0.8),       # 40-80% working vs reflecting
    "autonomy_collaboration": (0.3, 0.7),   # 30-70% autonomy vs collaboration
}


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "counters": {
            "building": 0, "shipping": 0,
            "working": 0, "reflecting": 0,
            "autonomy": 0, "collaboration": 0,
        },
        "imbalances": [],
        "last_check": 0,
    }


def _save_state(state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def record_activity(activity_type: str, count: int = 1):
    """Record an activity. Valid types: building, shipping, working, reflecting, autonomy, collaboration."""
    state = _load_state()
    if activity_type not in state["counters"]:
        raise ValueError(f"Unknown activity type: {activity_type}")
    state["counters"][activity_type] += count
    _save_state(state)


def check_balance() -> dict:
    """Check all balance ratios. Returns status with any imbalances."""
    state = _load_state()
    c = state["counters"]
    
    ratios = {}
    imbalances = []
    
    pairs = [
        ("building_shipping", "building", "shipping"),
        ("working_reflecting", "working", "reflecting"),
        ("autonomy_collaboration", "autonomy", "collaboration"),
    ]
    
    for name, a, b in pairs:
        total = c[a] + c[b]
        if total == 0:
            ratios[name] = 0.5
            continue
        ratio = c[a] / total
        ratios[name] = round(ratio, 3)
        
        lo, hi = HEALTHY_RANGES[name]
        if ratio < lo or ratio > hi:
            direction = f"too much {b}" if ratio < lo else f"too much {a}"
            imbalances.append({"ratio": name, "value": ratio, "direction": direction})
    
    state["imbalances"] = imbalances
    state["last_check"] = time.time()
    _save_state(state)
    
    # Signal imbalances to THALAMUS for HYPOTHALAMUS
    for imb in imbalances:
        thalamus.append({
            "source": "vestibular",
            "type": "need_signal",
            "salience": 0.5,
            "data": {"need": f"rebalance_{imb['ratio']}", "direction": imb["direction"]},
        })
    
    return {"ratios": ratios, "imbalances": imbalances, "healthy": len(imbalances) == 0}


def emit_need_signals() -> dict:
    """Check balance ratios and emit HYPOTHALAMUS need signals for imbalances."""
    try:
        state = _load_state()
    except Exception:
        return {}

    c = state.get("counters", {})
    signals = {}

    # build_ship_ratio: building / shipping > 3.0 means building way more than shipping
    shipping = c.get("shipping", 0)
    building = c.get("building", 0)
    if shipping > 0 and building / shipping > 3.0:
        from pulse.src import hypothalamus
        hypothalamus.record_need_signal("ship_something", "vestibular")
        signals["ship_something"] = building / shipping

    # work_reflect_ratio: working / reflecting > 5.0 means working without reflecting
    reflecting = c.get("reflecting", 0)
    working = c.get("working", 0)
    if reflecting > 0 and working / reflecting > 5.0:
        from pulse.src import hypothalamus
        hypothalamus.record_need_signal("reflect", "vestibular")
        signals["reflect"] = working / reflecting

    return signals


def get_status() -> dict:
    """Return vestibular status."""
    state = _load_state()
    return {
        "counters": state["counters"],
        "imbalances": state["imbalances"],
    }
