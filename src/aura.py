"""AURA — Ambient State Broadcast for Pulse.

Compact JSON every 60s: {mood, focus, available, energy, social_battery}.
Reads from ENDOCRINE/CIRCADIAN/SOMA/ADIPOSE/BUFFER.
"""

import json
import time
from pathlib import Path

from pulse.src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "aura.json"

EMIT_INTERVAL = 60  # seconds


def _load_state() -> dict:
    if _DEFAULT_STATE_FILE.exists():
        try:
            return json.loads(_DEFAULT_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "mood": "neutral",
        "focus": 0.5,
        "available": True,
        "energy": 1.0,
        "social_battery": 0.8,
        "last_emit": 0,
    }


def _save_state(state: dict):
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    _DEFAULT_STATE_FILE.write_text(json.dumps(state, indent=2))


def emit() -> dict:
    """Compute and emit current aura from all sources."""
    aura = _load_state()
    
    # Read ENDOCRINE mood
    try:
        from pulse.src import endocrine
        mood = endocrine.get_mood()
        aura["mood"] = mood.get("label", "neutral")
    except Exception:
        pass
    
    # Read CIRCADIAN mode for focus
    try:
        from pulse.src import circadian
        mode = circadian.get_current_mode()
        mode_val = mode.value if hasattr(mode, 'value') else str(mode)
        focus_map = {"dawn": 0.6, "daylight": 0.8, "golden": 0.7, "twilight": 0.4, "deep_night": 0.2}
        aura["focus"] = focus_map.get(mode_val, 0.5)
        aura["available"] = mode_val not in ("deep_night",)
    except Exception:
        pass
    
    # Read SOMA energy
    try:
        from pulse.src import soma
        status = soma.get_status()
        aura["energy"] = status.get("energy", 1.0)
    except Exception:
        pass
    
    # Read ADIPOSE for social battery proxy
    try:
        from pulse.src import adipose
        report = adipose.get_budget_report()
        conv = report.get("categories", {}).get("conversation", {})
        pct_used = conv.get("percent_used", 0)
        aura["social_battery"] = max(0.0, 1.0 - pct_used / 100.0)
    except Exception:
        pass
    
    aura["last_emit"] = time.time()
    _save_state(aura)
    
    # Broadcast to THALAMUS
    thalamus.append({
        "source": "aura",
        "type": "ambient",
        "salience": 0.2,
        "data": {k: v for k, v in aura.items() if k != "last_emit"},
    })
    
    return aura


def should_emit() -> bool:
    """Check if enough time has passed since last emit."""
    state = _load_state()
    return (time.time() - state.get("last_emit", 0)) >= EMIT_INTERVAL


def get_aura() -> dict:
    """Return current aura without re-computing."""
    return _load_state()


def get_status() -> dict:
    """Return aura status."""
    state = _load_state()
    return {
        "mood": state["mood"],
        "energy": state["energy"],
        "available": state["available"],
        "last_emit": state["last_emit"],
    }
