"""THYMUS — Growth Tracker for Pulse.

Skills registry with acquisition dates, proficiency 0-1, growth rate.
Plateau detection (growth near zero >7 days). Milestone system.
"""

import json
import time
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "thymus-state.json"

PLATEAU_DAYS = 7
PLATEAU_THRESHOLD = 0.01  # growth rate below this = plateau


def _load_state() -> dict:
    if _DEFAULT_STATE_FILE.exists():
        try:
            return json.loads(_DEFAULT_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "skills": {},
        "milestones": [],
        "last_check": 0,
    }


def _save_state(state: dict):
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    _DEFAULT_STATE_FILE.write_text(json.dumps(state, indent=2))


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def register_skill(name: str, initial_proficiency: float = 0.0) -> dict:
    """Register a new skill."""
    state = _load_state()
    if name not in state["skills"]:
        state["skills"][name] = {
            "proficiency": _clamp(initial_proficiency),
            "acquired_at": time.time(),
            "last_practice": time.time(),
            "growth_rate": 0.0,
            "practice_count": 0,
            "plateau_since": None,
        }
        _save_state(state)
    return state["skills"][name]


def practice_skill(name: str, quality: float = 0.5) -> dict:
    """Record practice of a skill. quality 0-1 affects growth."""
    state = _load_state()
    if name not in state["skills"]:
        register_skill(name)
        state = _load_state()
    
    skill = state["skills"][name]
    old_prof = skill["proficiency"]
    
    # Growth: diminishing returns as proficiency increases
    growth = quality * 0.05 * (1.0 - old_prof)
    skill["proficiency"] = _clamp(old_prof + growth)
    skill["practice_count"] += 1
    skill["last_practice"] = time.time()
    
    # Update growth rate (EMA)
    skill["growth_rate"] = skill["growth_rate"] * 0.7 + growth * 0.3
    
    # Check plateau
    if skill["growth_rate"] < PLATEAU_THRESHOLD:
        if skill["plateau_since"] is None:
            skill["plateau_since"] = time.time()
    else:
        skill["plateau_since"] = None
    
    # Check milestones
    milestones_at = [0.25, 0.5, 0.75, 0.9]
    for ms in milestones_at:
        if old_prof < ms <= skill["proficiency"]:
            milestone = {
                "skill": name,
                "level": ms,
                "ts": time.time(),
            }
            state["milestones"].append(milestone)
            state["milestones"] = state["milestones"][-100:]
            
            thalamus.append({
                "source": "thymus",
                "type": "milestone",
                "salience": 0.6,
                "data": milestone,
            })
    
    _save_state(state)
    return dict(skill)


def detect_plateaus() -> list:
    """Detect skills that have plateaued (growth near zero for >7 days)."""
    state = _load_state()
    now = time.time()
    plateaus = []
    
    for name, skill in state["skills"].items():
        if (skill.get("plateau_since") and 
            (now - skill["plateau_since"]) / 86400 >= PLATEAU_DAYS):
            plateaus.append({
                "skill": name,
                "proficiency": skill["proficiency"],
                "plateau_days": (now - skill["plateau_since"]) / 86400,
            })
    
    return plateaus


def get_skills() -> dict:
    """Return all skills."""
    state = _load_state()
    return dict(state["skills"])


def get_milestones(n: int = 10) -> list:
    """Return recent milestones."""
    state = _load_state()
    return state["milestones"][-n:]


def emit_need_signals() -> dict:
    """Check skill plateaus and emit HYPOTHALAMUS need signals."""
    try:
        state = _load_state()
    except Exception:
        return {}

    now = time.time()
    signals = {}

    for name, skill in state.get("skills", {}).items():
        plateau_since = skill.get("plateau_since")
        if plateau_since and (now - plateau_since) / 86400 > 7:
            from pulse.src import hypothalamus
            hypothalamus.record_need_signal("learn_new_skill", "thymus")
            signals["learn_new_skill"] = name
            break  # one signal per check is enough

    return signals


def get_status() -> dict:
    """Return thymus status."""
    state = _load_state()
    return {
        "total_skills": len(state["skills"]),
        "milestones": len(state["milestones"]),
        "plateaus": len(detect_plateaus()),
    }
