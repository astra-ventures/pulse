"""ENDOCRINE — Hormonal System / Mood Baseline.

Slow-moving mood state that persists for hours/days, beneath momentary emotions (LIMBIC).
Four simulated hormones: cortisol, dopamine, serotonin, oxytocin.
"""

import json
import time
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "endocrine-state.json"

# Decay rates per hour
DECAY_RATES = {
    "cortisol": -0.05,
    "dopamine": -0.08,
    "serotonin": -0.02,
    "oxytocin": -0.04,
    "adrenaline": -0.28,   # 15-min half-life ≈ fast decay per hour
    "melatonin": -0.01,    # very slow decay; accumulates during wake, decays in DEEP_NIGHT
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
    "intimate_conversation": {"oxytocin": 0.4},
    "reading_autobiography_aloud": {"oxytocin": 0.2},
    "josh_affirming": {"oxytocin": 0.3},
    "voice_call": {"oxytocin": 0.25},
    # Adrenaline (triggered by AMYGDALA threats)
    "amygdala_threat_high": {"adrenaline": 0.6, "cortisol": 0.2},
    "amygdala_threat_medium": {"adrenaline": 0.3, "cortisol": 0.1},
    "amygdala_fast_path": {"adrenaline": 0.8, "cortisol": 0.3},
    # Melatonin (accumulates during wake hours)
    "wake_hour_tick": {"melatonin": 0.03},
    "deep_night_decay": {"melatonin": -0.15},
    "rem_session_complete": {"melatonin": -0.4, "serotonin": 0.1},
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
            "adrenaline": 0.0,
            "melatonin": 0.1,
        },
        "last_update": time.time(),
        "mood_history": [],
        "event_log": [],
    }


def _load_state() -> dict:
    if _DEFAULT_STATE_FILE.exists():
        try:
            return json.loads(_DEFAULT_STATE_FILE.read_text())
        except (json.JSONDecodeError, KeyError):
            pass
    return _default_state()


def _save_state(state: dict):
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    _DEFAULT_STATE_FILE.write_text(json.dumps(state, indent=2))


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
    cortisol = h.get("cortisol", 0)
    dopamine = h.get("dopamine", 0)
    serotonin = h.get("serotonin", 0)
    oxytocin = h.get("oxytocin", 0)
    adrenaline = h.get("adrenaline", 0)
    melatonin = h.get("melatonin", 0)
    
    # Check combinations in priority order
    # Adrenaline overrides most states
    if adrenaline >= HIGH:
        if cortisol >= HIGH:
            return "fight-or-flight"
        return "hyper-alert"
    if melatonin >= 0.7:
        return "drowsy"
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
    if all(v < LOW for v in [cortisol, dopamine, serotonin, oxytocin]):
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
    
    # Adrenaline → overrides CIRCADIAN, suppresses CEREBELLUM
    if h.get("adrenaline", 0) >= HIGH:
        influence["override_circadian"] = True
        influence["suppress_cerebellum"] = True
        influence["urgency"] = 0.5
    
    # High melatonin → REM more likely
    if h.get("melatonin", 0) >= 0.6:
        influence["rem_boost"] = 0.3
    
    # Low everything → withdrawal
    if all(v < LOW for v in [h.get("cortisol", 0), h.get("dopamine", 0), h.get("serotonin", 0), h.get("oxytocin", 0)]):
        influence["withdrawal"] = 0.4
    
    return influence


def emit_need_signals() -> dict:
    """Check hormone levels and emit HYPOTHALAMUS need signals when thresholds crossed."""
    try:
        state = _load_state()
    except Exception:
        return {}

    h = state.get("hormones", {})
    signals = {}

    # Low oxytocin → need connection
    if h.get("oxytocin", 0.2) < 0.1:
        from pulse.src import hypothalamus
        hypothalamus.record_need_signal("connection", "endocrine")
        signals["connection"] = h["oxytocin"]

    # High cortisol → need to reduce stress
    if h.get("cortisol", 0.2) > 0.7:
        from pulse.src import hypothalamus
        hypothalamus.record_need_signal("reduce_stress", "endocrine")
        signals["reduce_stress"] = h["cortisol"]

    # Sustained max dopamine → need new challenge
    history = state.get("mood_history", [])
    if len(history) >= 20:
        last_20 = history[-20:]
        if all(entry.get("hormones", {}).get("dopamine", 0) >= 0.99 for entry in last_20):
            from pulse.src import hypothalamus
            hypothalamus.record_need_signal("new_challenge", "endocrine")
            signals["new_challenge"] = True

    return signals


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


def update_from_biosensors(cache=None) -> dict:
    """Poll BiosensorCache and update ENDOCRINE hormones from biometric data.

    Called each SENSE cycle via nervous_system.pre_sense().
    Gracefully no-ops if bridge not running or data stale.

    Returns: dict of hormone deltas applied (empty = no update).
    """
    try:
        if cache is None:
            from pulse.src.biosensor_cache import BiosensorCache
            cache = BiosensorCache()

        data = cache.read()
        if data is None:
            return {}

        state = _load_state()
        levels = state.get("hormones", {})
        deltas = {}

        def _clamp(v: float) -> float:
            return max(0.0, min(1.0, v))

        # Heart rate zone → adrenaline + cortisol
        hr_zone = cache.hr_zone()
        if hr_zone == "high":
            delta_a = 0.3
            delta_c = 0.1
            levels["adrenaline"] = _clamp(levels.get("adrenaline", 0) + delta_a)
            levels["cortisol"] = _clamp(levels.get("cortisol", 0.2) + delta_c)
            deltas["adrenaline"] = f"+{delta_a}"
            deltas["cortisol"] = f"+{delta_c}"
        elif hr_zone == "resting":
            delta_a = -0.1
            levels["adrenaline"] = _clamp(levels.get("adrenaline", 0) + delta_a)
            deltas["adrenaline"] = str(delta_a)

        # HRV stress level → cortisol + serotonin
        hrv_stress = cache.hrv_stress()
        if hrv_stress == "high":
            delta_c = 0.2
            levels["cortisol"] = _clamp(levels.get("cortisol", 0.2) + delta_c)
            deltas["cortisol"] = deltas.get("cortisol", "") + f" hrv:+{delta_c}"
        elif hrv_stress == "low":
            delta_c = -0.15
            delta_s = 0.1
            levels["cortisol"] = _clamp(levels.get("cortisol", 0.2) + delta_c)
            levels["serotonin"] = _clamp(levels.get("serotonin", 0.5) + delta_s)
            deltas["cortisol"] = deltas.get("cortisol", "") + f" hrv:{delta_c}"
            deltas["serotonin"] = f"+{delta_s}"

        # Move ring closed → dopamine boost
        move_pct = cache.move_ring_pct()
        if move_pct is not None and move_pct >= 1.0:
            delta_d = 0.25
            levels["dopamine"] = _clamp(levels.get("dopamine", 0.5) + delta_d)
            deltas["dopamine"] = f"+{delta_d} (move_ring)"

        # Deep sleep → serotonin + melatonin normalization
        sleep = cache.sleep()
        if sleep and sleep.get("stage") == "deep":
            minutes = sleep.get("minutes", 0)
            if minutes >= 30:
                delta_s = 0.15
                levels["serotonin"] = _clamp(levels.get("serotonin", 0.5) + delta_s)
                deltas["serotonin"] = deltas.get("serotonin", "") + f" deep_sleep:+{delta_s}"

        if deltas:
            state["hormones"] = levels
            state["last_update"] = time.time()
            _save_state(state)

        return deltas

    except Exception:
        return {}
