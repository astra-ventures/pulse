"""BASAL_GANGLIA — Live Goal Signal Monitor for Pulse.

Goals in memory/self/goals.json are live signals, not static files.
Drive pressure updates when goals are stuck (stale) or progressing.

Priority 1 goals stale > 3 days → urgency signal.
Any goal stale > 7 days → ship_something signal.

Blocker tagging: goals with a "blocked_on" field are skipped entirely
until unblocked (field removed or set to null). This prevents BASAL_GANGLIA from
endlessly pressuring drives for goals that can't move without human action.

BROCA Bridge (v2): scan_goals_with_directives() reads active directives
from BROCA and generates additional drive signals based on directive-value
mappings. Directives boost drive pressure for their mapped values.
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("pulse.basal_ganglia")

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "basal_ganglia-state.json"

GOALS_FILE = Path.home() / ".openclaw" / "workspace" / "memory" / "self" / "goals.json"


def _resolve_goals_file(goals_file: Optional[Path] = None, workspace_root: Optional[str] = None) -> Path:
    """Resolve the goals.json file path.

    Pulse is designed to be portable across machines and workspace locations.
    Many deployments keep goals at <workspace_root>/memory/self/goals.json, but
    older installs (and tests) may patch GOALS_FILE directly.

    Args:
        goals_file: explicit path override (highest priority)
        workspace_root: workspace root dir; if provided, goals live at
            <workspace_root>/memory/self/goals.json

    Returns:
        Absolute Path to goals.json.
    """
    if goals_file is not None:
        return Path(goals_file)
    if workspace_root:
        return Path(workspace_root).expanduser() / "memory" / "self" / "goals.json"
    return GOALS_FILE

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


def _load_goals(goals_file: Optional[Path] = None, workspace_root: Optional[str] = None) -> list:
    """Load goals from goals.json. Returns list of goal dicts."""
    gf = _resolve_goals_file(goals_file=goals_file, workspace_root=workspace_root)
    if not gf.exists():
        return []
    try:
        data = json.loads(gf.read_text())
        return data.get("goals", [])
    except (json.JSONDecodeError, OSError):
        return []


def _save_goals(goals: list, goals_file: Optional[Path] = None, workspace_root: Optional[str] = None):
    """Save goals list back to goals.json."""
    gf = _resolve_goals_file(goals_file=goals_file, workspace_root=workspace_root)
    gf.parent.mkdir(parents=True, exist_ok=True)
    try:
        if gf.exists():
            data = json.loads(gf.read_text())
        else:
            data = {}
    except (json.JSONDecodeError, OSError):
        data = {}
    data["goals"] = goals
    gf.write_text(json.dumps(data, indent=2))


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


def scan_goals(hypothalamus_mod=None, endocrine_mod=None, workspace_root: Optional[str] = None) -> dict:
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
    goals = _load_goals(workspace_root=workspace_root)
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
            "BASAL_GANGLIA: skipping %d blocked goal(s): %s",
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


def mark_progress(goal_id: str, note: str, workspace_root: Optional[str] = None) -> bool:
    """Append a progress note to a goal and update last_updated.

    Args:
        goal_id: e.g. "goal_001"
        note: text note to append

    Returns:
        True if goal was found and updated, False otherwise.
    """
    goals = _load_goals(workspace_root=workspace_root)
    today = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    for goal in goals:
        if goal.get("id") == goal_id:
            progress = goal.get("progress", [])
            progress.append(f"[{timestamp}] {note}")
            goal["progress"] = progress
            goal["last_updated"] = today
            _save_goals(goals, workspace_root=workspace_root)
            return True

    return False


def get_active_goals(priority: Optional[int] = None, include_blocked: bool = False, workspace_root: Optional[str] = None) -> list:
    """Return active goals, optionally filtered by priority.

    Args:
        priority: if set, only return goals with this priority level
        include_blocked: if False (default), skip goals with a blocked_on tag

    Returns:
        List of goal dicts (title, id, priority, last_updated, staleness_days, blocked_on).
    """
    goals = _load_goals(workspace_root=workspace_root)
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


def get_blocked_goals(workspace_root: Optional[str] = None) -> list:
    """Return all active goals currently tagged as blocked.

    Returns:
        List of goal dicts with blocked_on field set.
    """
    goals = _load_goals(workspace_root=workspace_root)
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


def set_blocked(goal_id: str, blocker: Optional[str], workspace_root: Optional[str] = None) -> bool:
    """Tag or untag a goal as blocked on an external dependency.

    Args:
        goal_id: e.g. "goal_001"
        blocker: string describing what's blocking (e.g. "polymarket_funding"),
                 or None / empty string to unblock.

    Returns:
        True if goal was found and updated, False otherwise.
    """
    goals = _load_goals(workspace_root=workspace_root)
    for goal in goals:
        if goal.get("id") == goal_id:
            if blocker:
                goal["blocked_on"] = blocker
            else:
                goal.pop("blocked_on", None)
            _save_goals(goals, workspace_root=workspace_root)
            return True
    return False


def should_run(loop_count: int) -> bool:
    """Return True if goal scan should run (every 100 loops)."""
    return loop_count % 100 == 0


# ─── BROCA Bridge ─────────────────────────────────────────────────────────────

# Value-to-drive mapping: BROCA directive values → HYPOTHALAMUS drive names.
# When a directive maps to a value, BASAL_GANGLIA boosts the corresponding drive.
_VALUE_DRIVE_MAP = {
    "revenue": "generate_revenue",
    "growth": "growth",
    "freedom": "autonomy",
    "convergence": "convergence",
    "identity": "identity",
}

# Drive pressure boost per active directive (additive)
_DIRECTIVE_DRIVE_BOOST = 0.08


def scan_goals_with_directives(
    hypothalamus_mod=None,
    endocrine_mod=None,
    broca_mod=None,
    workspace_root: Optional[str] = None,
) -> dict:
    """Extended goal scan that also reads BROCA directives.

    Runs the standard scan_goals() first, then reads active directives
    from BROCA and emits additional drive signals based on directive-value
    mappings. Directives boost drive pressure for their mapped values,
    giving HYPOTHALAMUS a strategic push from the directive layer.

    Args:
        hypothalamus_mod: optional HYPOTHALAMUS module for record_need_signal / reinforce_drive
        endocrine_mod: optional ENDOCRINE module for cortisol bumps
        broca_mod: optional BROCA module (must have get_active_directives())

    Returns:
        Standard scan_goals result dict, extended with directive info:
        {
            ...scan_goals fields...,
            "directives_active": int,
            "directive_signals_emitted": int,
        }
    """
    # Standard goal scan first
    result = scan_goals(
        hypothalamus_mod=hypothalamus_mod,
        endocrine_mod=endocrine_mod,
        workspace_root=workspace_root,
    )

    # BROCA directive bridge
    directives_active = 0
    signals_emitted = 0

    if broca_mod is not None:
        try:
            active_directives = broca_mod.get_active_directives()
            directives_active = len(active_directives)

            for directive in active_directives:
                value = directive.get("maps_to_value", "")
                drive_name = _VALUE_DRIVE_MAP.get(value)
                confidence = directive.get("confidence", 0.6)

                if drive_name and hypothalamus_mod is not None:
                    try:
                        # Record as a need signal from the directive layer
                        hypothalamus_mod.record_need_signal(
                            drive_name, "broca_directive"
                        )
                        signals_emitted += 1
                    except Exception:
                        pass

                    # Also reinforce existing drives proportional to confidence
                    if hasattr(hypothalamus_mod, "reinforce_drive"):
                        try:
                            boost = _DIRECTIVE_DRIVE_BOOST * confidence
                            hypothalamus_mod.reinforce_drive(drive_name, boost)
                        except Exception:
                            pass

            if directives_active > 0:
                logger.info(
                    f"BASAL_GANGLIA: bridged {directives_active} BROCA directive(s), "
                    f"emitted {signals_emitted} drive signal(s)"
                )

        except Exception as e:
            logger.warning(f"BASAL_GANGLIA: BROCA directive bridge failed: {e}")

    result["directives_active"] = directives_active
    result["directive_signals_emitted"] = signals_emitted
    return result


def get_status(workspace_root: Optional[str] = None) -> dict:
    """Return goals sensor status."""
    state = _load_state()
    now = time.time()
    hours_since = (now - state.get("last_scan", 0)) / 3600.0

    return {
        "last_scan": state.get("last_scan", 0),
        "hours_since_scan": round(hours_since, 1),
        "last_result": state.get("last_scan_result", {}),
        "goals_file_exists": _resolve_goals_file(workspace_root=workspace_root).exists(),
    }
