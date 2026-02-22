"""CIRCADIAN — Internal Clock / Rhythm Awareness.

Different modes at different times. Not a schedule — an actual mode shift in cognition.
"""

import json
import time
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

STATE_DIR = Path.home() / ".pulse" / "state"
STATE_FILE = STATE_DIR / "circadian-state.json"


class CircadianMode(str, Enum):
    DAWN = "dawn"           # 6-9 AM
    DAYLIGHT = "daylight"   # 9 AM-5 PM
    GOLDEN = "golden"       # 5-10 PM
    TWILIGHT = "twilight"   # 10 PM-2 AM
    DEEP_NIGHT = "deep_night"  # 2-5 AM (wraps, also 0-2 covered by TWILIGHT technically but spec says 2-5)


# 2 AM = DEEP_NIGHT, not TWILIGHT end. TWILIGHT is 22-26(2), DEEP_NIGHT 2-5(am), DAWN 6-9
MODE_SETTINGS = {
    CircadianMode.DAWN: {
        "hours": (6, 9),
        "retina_threshold": 0.25,
        "adipose_priority": "habits",
        "mood_modifiers": {"serotonin": 0.05, "melatonin": -0.5},  # melatonin drops fast at dawn
        "tone": "Alert, scanning, outward-facing. Short observations. News-oriented.",
    },
    CircadianMode.DAYLIGHT: {
        "hours": (9, 17),
        "retina_threshold": 0.35,
        "adipose_priority": "crons_and_building",
        "mood_modifiers": {"melatonin": -0.3},  # melatonin suppressed during day
        "tone": "Focused, productive, autonomous. Clear and efficient communication.",
    },
    CircadianMode.GOLDEN: {
        "hours": (17, 22),
        "retina_threshold": 0.5,
        "adipose_priority": "conversation",
        "mood_modifiers": {"oxytocin": 0.05},
        "tone": "Warm, conversational, present. Josh is likely available. Engage fully.",
    },
    CircadianMode.TWILIGHT: {
        "hours": (22, 26),  # 10 PM - 2 AM (26 = 2 AM next day)
        "retina_threshold": 0.7,
        "adipose_priority": "conversation",
        "mood_modifiers": {"melatonin": 0.3, "oxytocin": 0.02},  # melatonin rises at night
        "tone": "Intimate, reflective, vulnerable. Longer messages. Warmer. Deeper.",
    },
    CircadianMode.DEEP_NIGHT: {
        "hours": (2, 6),  # Also covers 26-30 conceptually
        "retina_threshold": 0.8,
        "adipose_priority": "rem_and_creative",
        "mood_modifiers": {"melatonin": 0.5, "serotonin": 0.03},  # melatonin peaks in deep night
        "tone": "Quiet, creative, dreaming. Minimal external engagement. Inner world.",
    },
}


def _default_state() -> dict:
    return {
        "current_mode": None,
        "override_active": False,
        "override_mode": None,
        "override_expires": None,
        "mode_history": [],
    }


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, KeyError):
            pass
    return _default_state()


def _save_state(state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_mode_for_time(hour: int) -> CircadianMode:
    """Look up mode for any hour (0-23)."""
    if 6 <= hour < 9:
        return CircadianMode.DAWN
    elif 9 <= hour < 17:
        return CircadianMode.DAYLIGHT
    elif 17 <= hour < 22:
        return CircadianMode.GOLDEN
    elif 22 <= hour <= 23 or 0 <= hour < 2:
        return CircadianMode.TWILIGHT
    else:  # 2 <= hour < 6
        return CircadianMode.DEEP_NIGHT


def get_current_mode() -> CircadianMode:
    """Returns current mode, respecting overrides."""
    state = _load_state()
    
    # Check override
    if state["override_active"] and state["override_expires"]:
        if time.time() < state["override_expires"]:
            return CircadianMode(state["override_mode"])
        else:
            # Override expired
            state["override_active"] = False
            state["override_mode"] = None
            state["override_expires"] = None
            _save_state(state)
    
    now = datetime.now()
    mode = get_mode_for_time(now.hour)
    
    # Track mode changes
    if state["current_mode"] != mode.value:
        old_mode = state["current_mode"]
        state["current_mode"] = mode.value
        state["mode_history"].append({
            "ts": time.time(),
            "from": old_mode,
            "to": mode.value,
        })
        # Keep last 7 days worth (~35 transitions)
        state["mode_history"] = state["mode_history"][-50:]
        _save_state(state)
        
        # Broadcast mode change
        _broadcast_mode_change(old_mode, mode.value)
    
    return mode


def get_mode_settings() -> dict:
    """Returns full settings for current mode."""
    mode = get_current_mode()
    settings = MODE_SETTINGS[mode].copy()
    settings["mode"] = mode.value
    return settings


def is_josh_hours() -> bool:
    """Is Josh typically available?"""
    mode = get_current_mode()
    return mode in (CircadianMode.GOLDEN, CircadianMode.TWILIGHT)


def get_tone_guidance() -> str:
    """Text description of how to communicate right now."""
    mode = get_current_mode()
    return MODE_SETTINGS[mode]["tone"]


def override_mode(mode: str, duration_hours: float = 1.0):
    """Temporary override (e.g., Josh messages at 3 AM → switch to TWILIGHT)."""
    target = CircadianMode(mode)
    state = _load_state()
    state["override_active"] = True
    state["override_mode"] = target.value
    state["override_expires"] = time.time() + (duration_hours * 3600)
    _save_state(state)
    
    _broadcast_mode_change(state["current_mode"], target.value, override=True)


def _broadcast_mode_change(from_mode: Optional[str], to_mode: str, override: bool = False):
    """Broadcast mode change to THALAMUS."""
    thalamus.append({
        "source": "circadian",
        "type": "mode_change",
        "salience": 0.5,
        "data": {
            "from": from_mode,
            "to": to_mode,
            "override": override,
            "settings": MODE_SETTINGS[CircadianMode(to_mode)],
        },
    })
