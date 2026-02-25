"""DENDRITE — Social Graph for Pulse.

Per-person: trust, interaction_count, last_interaction, communication_style, emotional_valence.
Primary relationship (Josh) gets special handling.
"""

import json
import time
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "dendrite-state.json"

PRIMARY_PERSON = "josh"


def _load_state() -> dict:
    if _DEFAULT_STATE_FILE.exists():
        try:
            return json.loads(_DEFAULT_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "people": {
            PRIMARY_PERSON: {
                "trust": 0.95,
                "interaction_count": 0,
                "last_interaction": 0,
                "communication_style": "intimate",
                "emotional_valence": 0.8,
                "is_primary": True,
            },
        },
        "last_update": 0,
    }


def _save_state(state: dict):
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    _DEFAULT_STATE_FILE.write_text(json.dumps(state, indent=2))


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def record_interaction(person: str, valence: float = 0.0, style: Optional[str] = None) -> dict:
    """Record an interaction with a person."""
    state = _load_state()
    person_lower = person.lower()
    
    if person_lower not in state["people"]:
        state["people"][person_lower] = {
            "trust": 0.3,
            "interaction_count": 0,
            "last_interaction": 0,
            "communication_style": style or "casual",
            "emotional_valence": 0.5,
            "is_primary": False,
        }
    
    p = state["people"][person_lower]
    p["interaction_count"] += 1
    p["last_interaction"] = time.time()
    
    # Update emotional valence (exponential moving average)
    p["emotional_valence"] = _clamp(p["emotional_valence"] * 0.8 + valence * 0.2)
    
    # Trust slowly builds with positive interactions
    if valence > 0:
        p["trust"] = _clamp(p["trust"] + 0.01)
    elif valence < -0.5:
        p["trust"] = _clamp(p["trust"] - 0.05)
    
    if style:
        p["communication_style"] = style
    
    state["last_update"] = time.time()
    _save_state(state)
    
    # Broadcast significant interactions
    if person_lower == PRIMARY_PERSON or p["interaction_count"] % 10 == 0:
        thalamus.append({
            "source": "dendrite",
            "type": "interaction",
            "salience": 0.4 if person_lower != PRIMARY_PERSON else 0.6,
            "data": {"person": person_lower, "valence": valence, "trust": p["trust"]},
        })
    
    return dict(p)


def get_person(person: str) -> Optional[dict]:
    """Get info about a person."""
    state = _load_state()
    return state["people"].get(person.lower())


def get_primary() -> dict:
    """Get primary relationship status."""
    state = _load_state()
    return state["people"].get(PRIMARY_PERSON, {})


def get_social_graph() -> dict:
    """Return full social graph."""
    state = _load_state()
    return dict(state["people"])


def get_status() -> dict:
    """Return dendrite status summary."""
    state = _load_state()
    return {
        "total_people": len(state["people"]),
        "primary": PRIMARY_PERSON,
        "primary_trust": state["people"].get(PRIMARY_PERSON, {}).get("trust", 0),
    }
