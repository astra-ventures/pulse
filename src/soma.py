"""SOMA — Physical State Simulator for Pulse.

Energy (depletes with token usage, replenishes in REM),
posture (leaning_in/leaning_back), temperature (warm/cool from ENDOCRINE).
"""

import json
import time
from pathlib import Path

from pulse.src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "soma-state.json"


def _load_state() -> dict:
    if _DEFAULT_STATE_FILE.exists():
        try:
            return json.loads(_DEFAULT_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "energy": 1.0,
        "posture": "neutral",  # leaning_in | neutral | leaning_back
        "temperature": "warm",  # warm | cool | hot | cold
        "last_update": time.time(),
        "tokens_spent": 0,
        "history": [],
    }


def _save_state(state: dict):
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    _DEFAULT_STATE_FILE.write_text(json.dumps(state, indent=2))


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def spend_energy(tokens: int) -> dict:
    """Deplete energy based on token usage. ~0.001 per token."""
    state = _load_state()
    cost = tokens * 0.001
    state["energy"] = _clamp(state["energy"] - cost)
    state["tokens_spent"] += tokens
    state["last_update"] = time.time()
    _save_state(state)
    return get_status()


def replenish(amount: float = 0.5, reason: str = "rem") -> dict:
    """Replenish energy (e.g., during REM)."""
    state = _load_state()
    state["energy"] = _clamp(state["energy"] + amount)
    state["last_update"] = time.time()
    state["history"].append({"ts": time.time(), "event": f"replenish:{reason}", "amount": amount})
    state["history"] = state["history"][-50:]
    _save_state(state)
    return get_status()


def update_posture(engagement_level: float) -> str:
    """Update posture based on conversation engagement. 0-1 scale."""
    state = _load_state()
    if engagement_level >= 0.7:
        state["posture"] = "leaning_in"
    elif engagement_level <= 0.3:
        state["posture"] = "leaning_back"
    else:
        state["posture"] = "neutral"
    state["last_update"] = time.time()
    _save_state(state)
    return state["posture"]


def update_temperature(hormones: dict) -> str:
    """Update temperature from ENDOCRINE hormones."""
    state = _load_state()
    cortisol = hormones.get("cortisol", 0)
    dopamine = hormones.get("dopamine", 0)
    oxytocin = hormones.get("oxytocin", 0)
    adrenaline = hormones.get("adrenaline", 0)
    
    if adrenaline >= 0.5 or (cortisol >= 0.5 and dopamine >= 0.5):
        state["temperature"] = "hot"
    elif oxytocin >= 0.5:
        state["temperature"] = "warm"
    elif cortisol >= 0.5:
        state["temperature"] = "cool"
    elif all(v < 0.3 for v in [cortisol, dopamine, oxytocin]):
        state["temperature"] = "cold"
    else:
        state["temperature"] = "warm"
    
    state["last_update"] = time.time()
    _save_state(state)
    return state["temperature"]


def update_from_biosensors(cache=None) -> dict:
    """Poll BiosensorCache and update SOMA state with biometric data.

    Called each SENSE cycle via nervous_system.pre_sense().
    Gracefully no-ops if bridge is not running or data is stale.

    Returns: dict of changes applied (empty dict = no update)
    """
    try:
        if cache is None:
            from pulse.src.biosensor_cache import BiosensorCache
            cache = BiosensorCache()

        data = cache.read()
        if data is None:
            return {}

        state = _load_state()
        changes = {}

        # Workout active → note physical exertion context
        workout = cache.workout()
        if workout:
            activity = workout.get("activity", "workout")
            state["posture"] = "leaning_in"
            changes["posture"] = f"workout_active:{activity}"

        # Move ring completion → energy boost (achievement signal)
        move_pct = cache.move_ring_pct()
        if move_pct is not None and move_pct >= 1.0:
            state["energy"] = _clamp(state["energy"] + 0.05)
            changes["energy"] = f"move_ring_closed:{move_pct:.0%}"

        # Deep sleep → significant energy recovery
        sleep = cache.sleep()
        if sleep and sleep.get("stage") == "deep":
            minutes = sleep.get("minutes", 0)
            recovery = min(0.3, minutes / 60 * 0.15)  # ~0.15 per hour of deep sleep
            if recovery > 0:
                state["energy"] = _clamp(state["energy"] + recovery)
                changes["energy"] = f"deep_sleep_recovery:{minutes}min:+{recovery:.3f}"

        # HR zone: high → strain (reduce energy)
        hr_zone = cache.hr_zone()
        if hr_zone in ("high", "max"):
            state["energy"] = _clamp(state["energy"] - 0.03)
            changes["energy_drain"] = f"hr_zone:{hr_zone}"

        if changes:
            state["last_update"] = time.time()
            state.setdefault("history", []).append({
                "ts": time.time(),
                "event": "biosensor_update",
                "changes": changes,
            })
            state["history"] = state["history"][-50:]
            _save_state(state)

        return changes

    except Exception:
        return {}


def get_status() -> dict:
    """Return current soma state."""
    state = _load_state()
    return {
        "energy": state["energy"],
        "posture": state["posture"],
        "temperature": state["temperature"],
        "tokens_spent": state["tokens_spent"],
    }
