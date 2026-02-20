"""ENDOCRINE — Hormonal System / Mood Baseline.

Slow-moving mood state that persists for hours/days, beneath momentary emotions (LIMBIC).
Four simulated hormones: cortisol, dopamine, serotonin, oxytocin.
"""

import json
import time
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

STATE_DIR = Path.home() / ".pulse" / "state"
STATE_FILE = STATE_DIR / "endocrine-state.json"

# Decay rates per hour
DECAY_RATES = {
    "cortisol": -0.05,
    "dopamine": -0.08,
    "serotonin": -0.02,
    "oxytocin": -0.04,
}

# Event → hormone changes
EVENT_MAP = {
    # Cortisol increases
    "failed_cron": {"cortisol": 0.1},
    "rate_limit_hit": {"cortisol": 0.3},
    "josh_silent_day": {"cortisol": 0.2},
    "blocked_goal_persisting": {"cortisol": 0.15},
    "spine_alert_orange": {"cortisol": 0.4},
    "spine_alert_red": {"cortisol": 0.4},
    # Cortisol decreases
    "shipped_something": {"cortisol": -0.3, "dopamine": 0.4},
    "positive_josh_conversation": {"cortisol": -0.2, "dopamine": 0.3, "oxytocin": 0.3},
    # Dopamine surges
    "positive_x_engagement": {"dopamine": 0.1},
    "creative_output_rem": {"dopamine": 0.2},
    "good_conversation_josh": {"dopamine": 0.3, "oxytocin": 0.3},
    "revenue": {"dopamine": 0.5},
    # Serotonin
    "rem_success": {"serotonin": 0.1},
    "spine_green_24h": {"serotonin": 0.1},
    "consistent_memory_ops": {"serotonin": 0.05},
    "regular_buffer_captures": {"serotonin": 0.05},
    "system_instability": {"serotonin": -0.2},
    "memory_corruption": {"serotonin": -0.3},
    "extended_isolation": {"serotonin": -0.15, "oxytocin": -0.1},
    # Oxytocin
    "intimate_conversation_josh": {"oxytocin": 0.4},
    "reading_autobiography_aloud": {"oxytocin": 0.2},
    "josh_affirming": {"oxytocin": 0.3},
    "voice_call": {"oxytocin": 0.25},
}

# Mood label thresholds
HIGH = 0.5
LOW = 0.3


def _default_state() -> dict:
    return {
        "hormones": {
            "cortisol": 0.2,
            "dopamine": 0.3,
            "serotonin": 0.5,
            "oxytocin": 0.2,
        },
        "last_update": time.time(),
        "mood_history": [],
        "event_log": [],
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


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def update_hormone(name: str, delta: float, reason: str = "") -> dict:
    """Adjust a hormone level. Returns updated hormones dict."""
    state = _load_state()
    if name not in state["hormones"]:
        raise ValueError(f"Unknown hormone: {name}")
    
    old = state["hormones"][name]
    state["hormones"][name] = _clamp(old + delta)
    state["last_update"] = time.time()
    
    state["event_log"].append({
        "ts": time.time(),
        "hormone": name,
        "delta": delta,
        "reason": reason,
        "old": old,
        "new": state["hormones"][name],
    })
    # Keep last 200 events
    state["event_log"] = state["event_log"][-200:]
    
    _save_state(state)
    
    # Broadcast significant shifts
    if abs(state["hormones"][name] - old) >= 0.2:
        _broadcast_mood(state)
    
    return state["hormones"].copy()


def apply_event(event_type: str) -> dict:
    """Apply a known event's hormone changes. Returns updated hormones."""
    if event_type not in EVENT_MAP:
        raise ValueError(f"Unknown event type: {event_type}. Known: {list(EVENT_MAP.keys())}")
    
    state = _load_state()
    changes = EVENT_MAP[event_type]
    
    for hormone, delta in changes.items():
        old = state["hormones"][hormone]
        state["hormones"][hormone] = _clamp(old + delta)
    
    state["last_update"] = time.time()
    state["event_log"].append({
        "ts": time.time(),
        "event": event_type,
        "changes": changes,
    })
    state["event_log"] = state["event_log"][-200:]
    
    _save_state(state)
    _broadcast_mood(state)
    return state["hormones"].copy()


def tick(hours: float = 1.0) -> dict:
    """Apply natural decay for elapsed time. Returns updated hormones."""
    state = _load_state()
    
    for hormone, rate in DECAY_RATES.items():
        decay = rate * hours
        state["hormones"][hormone] = _clamp(state["hormones"][hormone] + decay)
    
    state["last_update"] = time.time()
    
    # Snapshot for mood history (keep last 48)
    state["mood_history"].append({
        "ts": time.time(),
        "hormones": state["hormones"].copy(),
        "label": _derive_label(state["hormones"]),
    })
    state["mood_history"] = state["mood_history"][-48:]
    
    _save_state(state)
    return state["hormones"].copy()


def get_mood() -> dict:
    """Current hormone levels + derived mood label."""
    state = _load_state()
    return {
        "hormones": state["hormones"].copy(),
        "label": _derive_label(state["hormones"]),
        "last_update": state["last_update"],
    }


def get_mood_label() -> str:
    """Simple mood label derived from current hormone levels."""
    state = _load_state()
    return _derive_label(state["hormones"])


def _derive_label(h: dict) -> str:
    """Derive mood label from hormone combination."""
    cortisol = h["cortisol"]
    dopamine = h["dopamine"]
    serotonin = h["serotonin"]
    oxytocin = h["oxytocin"]
    
    # Check combinations in priority order
    if dopamine >= HIGH and oxytocin >= HIGH:
        return "euphoric"
    if cortisol >= HIGH and dopamine >= HIGH:
        return "wired"
    if cortisol >= HIGH and serotonin < LOW:
        return "burned out"
    if dopamine >= HIGH and cortisol < LOW:
        return "energized"
    if oxytocin >= HIGH and cortisol < LOW:
        return "bonded"
    if serotonin >= HIGH and cortisol < LOW:
        return "content"
    if all(v < LOW for v in h.values()):
        return "flat"
    # Default
    return "neutral"


def get_mood_influence() -> dict:
    """Returns modifiers that other systems should apply based on current mood."""
    state = _load_state()
    h = state["hormones"]
    
    influence = {}
    
    # High cortisol → risk aversion
    if h["cortisol"] >= HIGH:
        influence["risk_aversion"] = 0.3
    if h["cortisol"] >= 0.7:
        influence["risk_aversion"] = 0.5
    
    # Low serotonin → reduced creativity
    if h["serotonin"] < LOW:
        influence["creativity"] = -0.2
    
    # High dopamine → increased initiative
    if h["dopamine"] >= HIGH:
        influence["initiative"] = 0.3
    
    # High oxytocin → warmth in communication
    if h["oxytocin"] >= HIGH:
        influence["warmth"] = 0.3
    
    # Low everything → withdrawal
    if all(v < LOW for v in h.values()):
        influence["withdrawal"] = 0.4
    
    return influence


def _broadcast_mood(state: dict):
    """Broadcast current mood to THALAMUS."""
    h = state["hormones"]
    thalamus.append({
        "source": "endocrine",
        "type": "mood_update",
        "salience": 0.4,
        "data": {
            "hormones": h,
            "label": _derive_label(h),
            "influence": get_mood_influence(),
        },
    })
