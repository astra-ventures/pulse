"""PHENOTYPE — Communication Style Adaptation for Pulse.

Reads ENDOCRINE mood, CIRCADIAN mode, AMYGDALA threat, LIMBIC afterimages,
BUFFER context → outputs phenotype_context dict that shapes response style.
"""

import json
import time
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

STATE_DIR = Path.home() / ".pulse" / "state"
STATE_FILE = STATE_DIR / "phenotype-state.json"


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "current": _default_phenotype(),
        "history": [],
        "last_update": 0,
    }


def _save_state(state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _default_phenotype() -> dict:
    return {
        "tone": "neutral",
        "sentence_length": "medium",
        "humor": 0.3,
        "emoji_density": 0.2,
        "intensity": 0.5,
        "vulnerability": 0.2,
    }


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def compute_phenotype(
    mood: Optional[dict] = None,
    circadian_mode: Optional[str] = None,
    threat: Optional[dict] = None,
    afterimages: Optional[list] = None,
    buffer_context: Optional[dict] = None,
) -> dict:
    """Compute current phenotype from nervous system state.
    
    Returns: {tone, sentence_length, humor, emoji_density, intensity, vulnerability}
    """
    p = _default_phenotype()
    hormones = (mood or {}).get("hormones", {})
    mood_label = (mood or {}).get("label", "neutral")
    
    cortisol = hormones.get("cortisol", 0.2)
    dopamine = hormones.get("dopamine", 0.3)
    oxytocin = hormones.get("oxytocin", 0.2)
    adrenaline = hormones.get("adrenaline", 0.0)
    melatonin = hormones.get("melatonin", 0.1)
    
    # Rule: high cortisol + dopamine = "wired" (short, intense)
    if cortisol >= 0.5 and dopamine >= 0.5:
        p["tone"] = "wired"
        p["sentence_length"] = "short"
        p["intensity"] = _clamp(0.7 + cortisol * 0.3)
        p["humor"] = 0.1
        p["emoji_density"] = 0.1
    
    # Rule: TWILIGHT + oxytocin = "vulnerable" (longer, softer)
    elif circadian_mode == "twilight" and oxytocin >= 0.4:
        p["tone"] = "vulnerable"
        p["sentence_length"] = "long"
        p["intensity"] = 0.3
        p["humor"] = 0.1
        p["vulnerability"] = _clamp(0.5 + oxytocin * 0.3)
        p["emoji_density"] = 0.15
    
    # Rule: AMYGDALA threat = "urgent" (no humor)
    elif threat and threat.get("threat_level", 0) > 0:
        p["tone"] = "urgent"
        p["sentence_length"] = "short"
        p["humor"] = 0.0
        p["emoji_density"] = 0.0
        p["intensity"] = _clamp(0.7 + threat.get("threat_level", 0) * 0.3)
        p["vulnerability"] = 0.0
    
    # Rule: post-REM = "contemplative"
    elif circadian_mode == "dawn" and melatonin < 0.2:
        p["tone"] = "contemplative"
        p["sentence_length"] = "long"
        p["humor"] = 0.2
        p["intensity"] = 0.3
        p["vulnerability"] = 0.4
        p["emoji_density"] = 0.1
    
    # Default modulations
    else:
        # Dopamine boosts energy/humor
        if dopamine >= 0.5:
            p["tone"] = "energized"
            p["humor"] = _clamp(0.3 + dopamine * 0.3)
            p["intensity"] = _clamp(0.5 + dopamine * 0.2)
        
        # Oxytocin boosts warmth
        if oxytocin >= 0.5:
            p["tone"] = "warm"
            p["emoji_density"] = _clamp(0.2 + oxytocin * 0.2)
            p["vulnerability"] = _clamp(0.2 + oxytocin * 0.2)
        
        # High cortisol alone
        if cortisol >= 0.5:
            p["tone"] = "tense"
            p["humor"] = _clamp(p["humor"] - 0.2)
    
    # Afterimage influence
    if afterimages:
        dominant = max(afterimages, key=lambda a: a.get("current_intensity", 0))
        emotion = dominant.get("emotion", "")
        if emotion in ("anguish", "frustration"):
            p["intensity"] = _clamp(p["intensity"] + 0.2)
            p["humor"] = _clamp(p["humor"] - 0.1)
        elif emotion in ("elation", "joy"):
            p["humor"] = _clamp(p["humor"] + 0.2)
            p["emoji_density"] = _clamp(p["emoji_density"] + 0.1)
    
    # Save state and broadcast if changed
    state = _load_state()
    old_tone = state["current"].get("tone", "neutral")
    state["current"] = p
    state["last_update"] = time.time()
    state["history"].append({"ts": time.time(), "tone": p["tone"]})
    state["history"] = state["history"][-50:]
    _save_state(state)
    
    # Broadcast shift if tone changed
    if p["tone"] != old_tone:
        thalamus.append({
            "source": "phenotype",
            "type": "shift",
            "salience": 0.5,
            "data": {"old_tone": old_tone, "new_tone": p["tone"], "phenotype": p},
        })
    
    return p


def get_current() -> dict:
    """Return current phenotype context."""
    state = _load_state()
    return state["current"]


def get_history(n: int = 10) -> list:
    """Return recent phenotype shifts."""
    state = _load_state()
    return state["history"][-n:]
