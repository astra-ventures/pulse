"""Emotional Afterimage — High-intensity emotions leave decaying residue.

When intensity > 7 or |valence| > 2, an afterimage is created that decays
exponentially with a 4-hour half-life.
"""

import json
import math
import time
from pathlib import Path
from typing import Optional

from . import thalamus

STATE_DIR = Path.home() / ".pulse" / "state"
STATE_FILE = STATE_DIR / "afterimage.json"
DEFAULT_HALF_LIFE_MS = 14_400_000  # 4 hours
DECAY_THRESHOLD = 0.5  # Remove afterimages below this


def _load_state() -> list[dict]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, KeyError):
            return []
    return []


def _save_state(afterimages: list[dict]):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(afterimages, indent=2))


def _valence_to_emotion(valence: float, intensity: float) -> str:
    """Map valence/intensity to an emotion label."""
    if valence > 1.5:
        return "elation" if intensity > 8 else "joy"
    elif valence > 0:
        return "excitement" if intensity > 7 else "warmth"
    elif valence > -1:
        return "unease" if intensity > 7 else "melancholy"
    else:
        return "anguish" if intensity > 8 else "frustration"


def _decayed_intensity(afterimage: dict, now_ms: Optional[int] = None) -> float:
    """Calculate current intensity after exponential decay."""
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    elapsed = now_ms - afterimage["created_at"]
    if elapsed <= 0:
        return afterimage["intensity"]
    half_life = afterimage.get("half_life_ms", DEFAULT_HALF_LIFE_MS)
    return afterimage["intensity"] * math.pow(0.5, elapsed / half_life)


def record_emotion(valence: float, intensity: float, context: str) -> Optional[dict]:
    """Record an emotion. Creates afterimage if intensity > 7 or |valence| > 2."""
    if intensity <= 7 and abs(valence) <= 2:
        return None
    
    now_ms = int(time.time() * 1000)
    emotion = _valence_to_emotion(valence, intensity)
    
    afterimage = {
        "emotion": emotion,
        "valence": valence,
        "intensity": intensity,
        "context": context,
        "created_at": now_ms,
        "half_life_ms": DEFAULT_HALF_LIFE_MS,
        "last_milestone": 100,  # Track decay milestones: 100, 50, 25, 10
    }
    
    state = _load_state()
    state.append(afterimage)
    _save_state(state)
    
    # Broadcast creation
    thalamus.append({
        "source": "limbic",
        "type": "emotion",
        "salience": min(intensity / 10.0, 1.0),
        "data": {
            "event": "created",
            "emotion": emotion,
            "valence": valence,
            "intensity": intensity,
            "context": context,
        }
    })
    
    return afterimage


def get_current_afterimages() -> list[dict]:
    """Return active afterimages with current decayed intensity."""
    state = _load_state()
    now_ms = int(time.time() * 1000)
    active = []
    changed = False
    
    for ai in state:
        current = _decayed_intensity(ai, now_ms)
        if current < DECAY_THRESHOLD:
            changed = True
            continue
        
        # Check milestones
        pct = (current / ai["intensity"]) * 100
        last = ai.get("last_milestone", 100)
        for milestone in [50, 25, 10]:
            if pct <= milestone and last > milestone:
                ai["last_milestone"] = milestone
                changed = True
                thalamus.append({
                    "source": "limbic",
                    "type": "emotion",
                    "salience": current / 10.0,
                    "data": {
                        "event": f"decay_{milestone}pct",
                        "emotion": ai["emotion"],
                        "current_intensity": round(current, 2),
                        "context": ai["context"],
                    }
                })
                break
        
        result = dict(ai)
        result["current_intensity"] = round(current, 2)
        active.append(result)
    
    if changed:
        _save_state(active)
    
    return active


def get_emotional_color() -> Optional[dict]:
    """Return the dominant emotional residue right now, or None if all faded."""
    active = get_current_afterimages()
    if not active:
        return None
    return max(active, key=lambda a: a["current_intensity"])
