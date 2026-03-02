"""TELOS — Live Goal Signal Monitor for Pulse.

Goals in memory/self/goals.json are live signals, not static files.
Drive pressure updates when goals are stuck (stale) or progressing.

Priority 1 goals stale > 3 days → urgency signal.
Any goal stale > 7 days → ship_something signal.

Blocker tagging: goals with a "blocked_on" field are skipped entirely
until unblocked (field removed or set to null). This prevents TELOS from
endlessly pressuring drives for goals that can't move without human action.
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("pulse.telos")

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "telos-state.json"

GOALS_FILE = Path.home() / ".openclaw" / "workspace" / "memory" / "self" / "goals.json"

# Staleness thresholds
_P1_STALE_DAYS = 3
_GENERAL_STALE_DAYS = 7


def _default_state() -> dict:
    return {
        "last_scan": 0,
        "last_scan_result": {},
    }


def _load_state() -> dict:
    if _DEFAULT_STATE_FILE.exists():
        try:
            return json.loads(_DEFAULT_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return _default_state()


def _save_state(state: dict):
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    _DEFAULT_STATE_FILE.write_text(json.dumps(state, indent=2))


def _load_goals() -> list:
    """Load goals from goals.json. Returns list of goal dicts."""
    if not GOALS_FILE.exists():
        return []
    try:
        data = json.loads(GOALS_FILE.read_text())
        return data.get("goals", [])
    except (json.JSONDecodeError, OSError):
        return []


def _save_goals(goals: list):
    """Save goals list back to goals.json."""
    GOALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        if GOALS_FILE.exists():
            data = json.loads(GOALS_FILE.read_text())
        else:
            data = {}
    except (json.JSONDecodeError, OSError):
        data = {}
    data["goals"] = goals
    GOALS_FILE.write_text(json.dumps(data, indent=2))


def _staleness_days(goal: dict) -> float:
    """Compute days since goal was last updated."""
    last_updated = goal.get("last_updated", "")
    if not last_updated:
        return 999.0

    try:
        updated_dt = datetime.strptime(last_updated[:10], "%Y-%m-%d")
        now_dt = datetime.now()
        return max(0.0, (now_dt - updated_dt).total_seconds() / 86400)
    except (ValueError, TypeError):
        return 999.0


def scan_goals(hypothalamus_mod=None, endocrine_mod=None) -> dict:
    """Scan goals.json and emit need signals for stale or urgent goals.

    Args:
        hypothalamus_mod: optional HYPOTHALAMUS module for record_need_signal
        endocrine_mod: optional ENDOCRINE module for cortisol bumps

    Returns:
        {
            "total": int,
            "stale": int,
            "priority1_stale": int,
            "most_urgent": str,
        }
    """
    goals = _load_goals()
    state = _load_state()

    all_active = [g for g in goals if g.get("status") == "active"]

    # Skip goals blocked on external dependencies — they can't move without human action.
    # A goal is blocked if it has a non-empty "blocked_on" string field.
    active_goals = [
        g for g in all_active
        if not g.get("blocked_on")
    ]
    blocked_goals = [g for g in all_active if g.get("blocked_on")]
    if blocked_goals:
        logger.debug(
            "TELOS: skipping %d blocked goal(s): %s",
            len(blocked_goals),
            ", ".join(f"'{g.get('title','?')}' (blocked_on: {g.get('blocked_on')})" for g in blocked_goals),
        )

    total = len(active_goals)
    stale_count = 0
    p1_stale_count = 0
    most_urgent = None
    most_urgent_staleness = -1.0

    for goal in active_goals:
        staleness = _staleness_days(goal)
        priority = goal.get("priority", 99)
        title = goal.get("title", "unknown")

        # Track most urgent (most stale P1)
        if priority == 1 and staleness > most_urgent_staleness:
            most_urgent_staleness = staleness
            most_urgent = title

        # General staleness check
        if staleness > _GENERAL_STALE_DAYS:
            stale_count += 1
            if hypothalamus_mod is not None:
                try:
                    hypothalamus_mod.record_need_signal("ship_something", "goals_sensor")
                except Exception:
                    pass

        # Priority 1 staleness check (tighter threshold)
        if priority == 1 and staleness > _P1_STALE_DAYS:
            p1_stale_count += 1
            if hypothalamus_mod is not None:
                try:
                    hypothalamus_mod.record_need_signal("goals", "goals_sensor")
                except Exception:
                    pass
            if endocrine_mod is not None:
                try:
                    endocrine_mod.update_hormone("cortisol", 0.05, f"p1_goal_stale:{title[:30]}")
                except Exception:
                    pass

    result = {
        "total": total,
        "stale": stale_count,
        "priority1_stale": p1_stale_count,
        "most_urgent": most_urgent or "",
    }

    state["last_scan"] = time.time()
    state["last_scan_result"] = result
    _save_state(state)

    return result


def mark_progress(goal_id: str, note: str) -> bool:
    """Append a progress note to a goal and update last_updated.

    Args:
        goal_id: e.g. "goal_001"
        note: text note to append

    Returns:
        True if goal was found and updated, False otherwise.
    """
    goals = _load_goals()
    today = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    for goal in goals:
        if goal.get("id") == goal_id:
            progress = goal.get("progress", [])
            progress.append(f"[{timestamp}] {note}")
            goal["progress"] = progress
            goal["last_updated"] = today
            _save_goals(goals)
            return True

    return False


def get_active_goals(priority: Optional[int] = None, include_blocked: bool = False) -> list:
    """Return active goals, optionally filtered by priority.

    Args:
        priority: if set, only return goals with this priority level
        include_blocked: if False (default), skip goals with a blocked_on tag

    Returns:
        List of goal dicts (title, id, priority, last_updated, staleness_days, blocked_on).
    """
    goals = _load_goals()
    active = [g for g in goals if g.get("status") == "active"]

    if not include_blocked:
        active = [g for g in active if not g.get("blocked_on")]

    if priority is not None:
        active = [g for g in active if g.get("priority") == priority]

    # Enrich with staleness
    result = []
    for g in active:
        result.append({
            "id": g.get("id"),
            "title": g.get("title"),
            "priority": g.get("priority"),
            "last_updated": g.get("last_updated"),
            "staleness_days": round(_staleness_days(g), 1),
            "type": g.get("type"),
            "blocked_on": g.get("blocked_on"),
        })

    return result


def get_blocked_goals() -> list:
    """Return all active goals currently tagged as blocked.

    Returns:
        List of goal dicts with blocked_on field set.
    """
    goals = _load_goals()
    blocked = [g for g in goals if g.get("status") == "active" and g.get("blocked_on")]
    return [
        {
            "id": g.get("id"),
            "title": g.get("title"),
            "priority": g.get("priority"),
            "blocked_on": g.get("blocked_on"),
            "last_updated": g.get("last_updated"),
        }
        for g in blocked
    ]


def set_blocked(goal_id: str, blocker: Optional[str]) -> bool:
    """Tag or untag a goal as blocked on an external dependency.

    Args:
        goal_id: e.g. "goal_001"
        blocker: string describing what's blocking (e.g. "polymarket_funding"),
                 or None / empty string to unblock.

    Returns:
        True if goal was found and updated, False otherwise.
    """
    goals = _load_goals()
    for goal in goals:
        if goal.get("id") == goal_id:
            if blocker:
                goal["blocked_on"] = blocker
            else:
                goal.pop("blocked_on", None)
            _save_goals(goals)
            return True
    return False


def should_run(loop_count: int) -> bool:
    """Return True if goal scan should run (every 100 loops)."""
    return loop_count % 100 == 0


def get_status() -> dict:
    """Return goals sensor status."""
    state = _load_state()
    now = time.time()
    hours_since = (now - state.get("last_scan", 0)) / 3600.0

    return {
        "last_scan": state.get("last_scan", 0),
        "hours_since_scan": round(hours_since, 1),
        "last_result": state.get("last_scan_result", {}),
        "goals_file_exists": GOALS_FILE.exists(),
    }
