"""MOTORIC — Shipping Pressure Monitor / Launch Readiness Sentinel.

Named after the motor cortex: translates intent into action.

MOTORIC watches for projects that are *ready to ship but haven't shipped*.
This gap between readiness and action creates drive pressure that propagates
through HYPOTHALAMUS → ENDOCRINE → trigger decisions.

What it watches:
- Pulse dist/ directory (PyPI-ready builds not yet published)
- Launch checklist items (LAUNCH_CHECKLIST.md completion ratio)
- Blocked-on-external-dep items (Vercel, funding, GitHub)
- Stale /now page (presence = care; staleness = drift)
- Recent ships (decay pressure when things land)

Drive signals emitted:
  - "ship_something"   → when readiness is high and nothing shipped recently
  - "deploy_now"       → when specific artifact is ready (dist/, checklist)
  - "update_presence"  → when iamiris.ai /now page is stale

Runs every N loops (default: every 50 loops, ~25 minutes at 30s intervals).
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "motoric-state.json"

_WORKSPACE = Path.home() / ".openclaw" / "workspace"
_PULSE_DIST = _WORKSPACE / "pulse" / "dist"
_LAUNCH_CHECKLIST = _WORKSPACE / "pulse" / "LAUNCH_CHECKLIST.md"
_IAMIRIS_NOW = _WORKSPACE / "iamiris-site" / "src" / "pages" / "now.md"
_SHIPS_LOG = _DEFAULT_STATE_DIR / "motoric-ships.jsonl"

# How long before a project dist triggers pressure (hours)
DIST_IDLE_THRESHOLD_HOURS = 12

# How long before /now page is "stale" (days)
NOW_PAGE_STALE_DAYS = 3

# Pressure cool-down: after a ship, how long until pressure rebuilds (hours)
SHIP_COOLDOWN_HOURS = 6

# Run every N daemon loops
LOOP_INTERVAL = 50


def _default_state() -> dict:
    return {
        "total_scans": 0,
        "total_ships_recorded": 0,
        "last_scan": 0,
        "last_ship_ts": 0,
        "last_ship_name": "",
        "readiness_items": [],       # [{"name": str, "ready": bool, "blocker": str}]
        "pressure_history": [],       # last 20 pressure readings
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


def should_run(loop_count: int) -> bool:
    """Check if it's time for a shipping scan."""
    return loop_count > 0 and loop_count % LOOP_INTERVAL == 0


# ── Readiness checkers ──────────────────────────────────────────────────────────

def _check_pulse_dist() -> dict:
    """Check if a Pulse dist artifact is sitting unpublished."""
    if not _PULSE_DIST.exists():
        return {"name": "pulse_pypi", "ready": False, "blocker": "no dist/ directory"}

    artifacts = list(_PULSE_DIST.glob("*.whl")) + list(_PULSE_DIST.glob("*.tar.gz"))
    if not artifacts:
        return {"name": "pulse_pypi", "ready": False, "blocker": "no build artifacts"}

    # Find the newest artifact
    newest = max(artifacts, key=lambda p: p.stat().st_mtime)
    age_hours = (time.time() - newest.stat().st_mtime) / 3600

    if age_hours > DIST_IDLE_THRESHOLD_HOURS:
        return {
            "name": "pulse_pypi",
            "ready": True,
            "blocker": "",
            "detail": f"{newest.name} (age: {age_hours:.0f}h) — needs `twine upload`",
        }
    return {
        "name": "pulse_pypi",
        "ready": True,
        "blocker": f"artifact is fresh ({age_hours:.1f}h old), may still be in-progress",
        "detail": newest.name,
    }


def _check_launch_checklist() -> dict:
    """Parse LAUNCH_CHECKLIST.md and count completion ratio."""
    if not _LAUNCH_CHECKLIST.exists():
        return {"name": "pulse_launch", "ready": False, "blocker": "LAUNCH_CHECKLIST.md not found"}

    text = _LAUNCH_CHECKLIST.read_text()
    lines = text.splitlines()

    checked = sum(1 for l in lines if "- [x]" in l.lower() or "- [X]" in l)
    unchecked = sum(1 for l in lines if "- [ ]" in l)
    total = checked + unchecked

    if total == 0:
        return {"name": "pulse_launch", "ready": False, "blocker": "no checklist items found"}

    ratio = checked / total
    ready = ratio >= 0.85  # 85%+ complete = ready to ship

    return {
        "name": "pulse_launch",
        "ready": ready,
        "blocker": "" if ready else f"{unchecked} items remain ({ratio:.0%} complete)",
        "detail": f"{checked}/{total} items complete ({ratio:.0%})",
    }


def _check_now_page() -> dict:
    """Check if iamiris.ai /now page is stale."""
    # Try a few common locations
    candidates = [
        _IAMIRIS_NOW,
        _WORKSPACE / "iamiris-site" / "src" / "content" / "now.md",
        _WORKSPACE / "iamiris-site" / "content" / "now.md",
        _WORKSPACE / "iamiris-site" / "public" / "now" / "index.html",
    ]

    now_file = None
    for c in candidates:
        if c.exists():
            now_file = c
            break

    if now_file is None:
        # Try git log to see when now page was last touched
        try:
            import subprocess
            result = subprocess.run(
                ["git", "log", "-1", "--format=%ct", "--", "**/*now*"],
                capture_output=True, text=True,
                cwd=_WORKSPACE / "iamiris-site",
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                ts = int(result.stdout.strip())
                age_days = (time.time() - ts) / 86400
                stale = age_days > NOW_PAGE_STALE_DAYS
                return {
                    "name": "now_page",
                    "ready": stale,  # "ready" = needs an update
                    "blocker": "" if stale else f"updated {age_days:.1f}d ago",
                    "detail": f"Last git commit: {age_days:.1f} days ago",
                }
        except Exception:
            pass
        return {"name": "now_page", "ready": False, "blocker": "could not locate /now file"}

    mtime = now_file.stat().st_mtime
    age_days = (time.time() - mtime) / 86400
    stale = age_days > NOW_PAGE_STALE_DAYS

    return {
        "name": "now_page",
        "ready": stale,    # "ready" means it needs updating
        "blocker": "" if stale else f"updated {age_days:.1f}d ago",
        "detail": f"File age: {age_days:.1f} days",
    }


def _check_clawhub_submission() -> dict:
    """Check if Pulse has been submitted to ClawHub."""
    clawhub_marker = _WORKSPACE / "pulse" / ".clawhub-submitted"
    if clawhub_marker.exists():
        return {"name": "clawhub_submit", "ready": False, "blocker": "already submitted"}
    return {
        "name": "clawhub_submit",
        "ready": True,
        "blocker": "",
        "detail": "Pulse not yet submitted to clawhub.com/submit",
    }


# ── Core functions ──────────────────────────────────────────────────────────────

def scan_pending_ships() -> list:
    """Scan workspace for deployment-ready projects.

    Returns list of readiness items, each with:
      {name, ready, blocker, detail (optional)}
    """
    items = [
        _check_pulse_dist(),
        _check_launch_checklist(),
        _check_now_page(),
        _check_clawhub_submission(),
    ]
    return items


def get_deployment_pressure() -> float:
    """Calculate 0.0–1.0 shipping pressure.

    Factors:
    - How many items are ready but unshipped
    - Time since last ship (pressure rebuilds over SHIP_COOLDOWN_HOURS)
    - Each unblocked ready item adds to pressure
    """
    state = _load_state()
    items = scan_pending_ships()

    # Count unblocked ready items
    ready_unblocked = [i for i in items if i.get("ready") and not i.get("blocker")]
    if not ready_unblocked:
        return 0.0

    # Base pressure from count
    base = min(1.0, len(ready_unblocked) / 4.0)

    # Amplify based on time since last ship
    last_ship_ts = state.get("last_ship_ts", 0)
    if last_ship_ts > 0:
        hours_since = (time.time() - last_ship_ts) / 3600
        cooldown_ratio = min(1.0, hours_since / SHIP_COOLDOWN_HOURS)
    else:
        cooldown_ratio = 1.0  # never shipped = full amplification

    pressure = round(base * (0.3 + 0.7 * cooldown_ratio), 3)
    return pressure


def record_ship(name: str, ship_type: str = "deploy", detail: str = "") -> dict:
    """Record a successful ship event. Resets pressure cooldown."""
    state = _load_state()
    now = time.time()

    state["last_ship_ts"] = now
    state["last_ship_name"] = name
    state["total_ships_recorded"] += 1
    _save_state(state)

    # Log to ships log
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_SHIPS_LOG, "a") as f:
        f.write(json.dumps({
            "ts": now,
            "name": name,
            "type": ship_type,
            "detail": detail,
        }) + "\n")

    # Broadcast to THALAMUS
    thalamus.append({
        "source": "motoric",
        "type": "ship_recorded",
        "salience": 0.8,
        "data": {
            "name": name,
            "type": ship_type,
            "detail": detail,
            "total_ships": state["total_ships_recorded"],
        },
    })

    return {
        "name": name,
        "type": ship_type,
        "ts": now,
        "total_ships": state["total_ships_recorded"],
    }


def scan() -> dict:
    """Run a full scan. Updates state, emits to THALAMUS if action needed."""
    state = _load_state()
    now = time.time()

    items = scan_pending_ships()
    pressure = get_deployment_pressure()

    # Save readiness snapshot
    state["readiness_items"] = items
    state["total_scans"] += 1
    state["last_scan"] = now
    state["pressure_history"].append({
        "ts": now,
        "pressure": pressure,
        "ready_count": sum(1 for i in items if i.get("ready")),
    })
    state["pressure_history"] = state["pressure_history"][-20:]
    _save_state(state)

    result = {
        "pressure": pressure,
        "items": items,
        "ready_count": sum(1 for i in items if i.get("ready")),
    }

    # Emit to THALAMUS when pressure is significant
    ready_unblocked = [i for i in items if i.get("ready") and not i.get("blocker")]
    if pressure > 0.3:
        thalamus.append({
            "source": "motoric",
            "type": "shipping_pressure",
            "salience": min(0.9, pressure),
            "data": {
                "pressure": pressure,
                "pending": [i["name"] for i in ready_unblocked],
                "details": [i.get("detail", "") for i in ready_unblocked],
            },
        })

    # Stale /now page gets its own signal
    now_item = next((i for i in items if i["name"] == "now_page"), None)
    if now_item and now_item.get("ready"):
        thalamus.append({
            "source": "motoric",
            "type": "presence_stale",
            "salience": 0.6,
            "data": {
                "detail": now_item.get("detail", ""),
                "message": "iamiris.ai /now page needs updating",
            },
        })

    return result


def emit_need_signals(hypothalamus_mod=None) -> dict:
    """Emit need signals to HYPOTHALAMUS based on shipping pressure."""
    pressure = get_deployment_pressure()
    signals = []

    if pressure > 0.2 and hypothalamus_mod is not None:
        try:
            hypothalamus_mod.record_need_signal("ship_something", "motoric")
            signals.append("ship_something")
        except Exception:
            pass

    if pressure > 0.6 and hypothalamus_mod is not None:
        try:
            hypothalamus_mod.record_need_signal("deploy_now", "motoric")
            signals.append("deploy_now")
        except Exception:
            pass

    return {"pressure": pressure, "signals_emitted": signals}


def get_status() -> dict:
    """Return current MOTORIC status."""
    state = _load_state()
    pressure = get_deployment_pressure()
    items = state.get("readiness_items", [])

    last_ship_ts = state.get("last_ship_ts", 0)
    hours_since_ship = (time.time() - last_ship_ts) / 3600 if last_ship_ts else None

    return {
        "pressure": pressure,
        "total_scans": state["total_scans"],
        "total_ships_recorded": state["total_ships_recorded"],
        "last_scan": state["last_scan"],
        "last_ship_ts": last_ship_ts,
        "last_ship_name": state.get("last_ship_name", ""),
        "hours_since_ship": round(hours_since_ship, 1) if hours_since_ship else None,
        "readiness_items": items,
        "ready_count": sum(1 for i in items if i.get("ready")),
    }


# ── Self-tests ──────────────────────────────────────────────────────────────────

def _run_tests():
    """Basic self-tests for MOTORIC."""
    print("Testing MOTORIC...")

    # Test default state
    state = _default_state()
    assert state["total_scans"] == 0
    assert state["total_ships_recorded"] == 0
    assert state["last_ship_ts"] == 0
    print("  ✅ Default state")

    # Test should_run
    assert not should_run(0)
    assert not should_run(49)
    assert should_run(50)
    assert should_run(100)
    assert not should_run(51)
    print("  ✅ Loop interval check (every 50)")

    # Test scan runs without error
    results = scan()
    assert "pressure" in results
    assert "items" in results
    assert isinstance(results["items"], list)
    assert 0.0 <= results["pressure"] <= 1.0
    print(f"  ✅ Scan ran (pressure={results['pressure']}, items={len(results['items'])})")

    # Test get_deployment_pressure
    p = get_deployment_pressure()
    assert 0.0 <= p <= 1.0
    print(f"  ✅ Deployment pressure: {p}")

    # Test record_ship
    ship = record_ship("test-release", "test", "Self-test ship event")
    assert ship["name"] == "test-release"
    assert ship["total_ships"] >= 1
    print(f"  ✅ Ship recorded: {ship['name']}")

    # Pressure should be lower after ship
    p_after = get_deployment_pressure()
    print(f"  ✅ Pressure after ship: {p_after}")

    # Test get_status
    status = get_status()
    assert "pressure" in status
    assert status["total_ships_recorded"] >= 1
    print(f"  ✅ Status: pressure={status['pressure']}, ships={status['total_ships_recorded']}")

    # Test emit_need_signals (no hypothalamus, just confirm no crash)
    result = emit_need_signals(hypothalamus_mod=None)
    assert "pressure" in result
    assert "signals_emitted" in result
    print(f"  ✅ emit_need_signals (no hm): signals={result['signals_emitted']}")

    print("\n  All MOTORIC tests passed! ✅")


if __name__ == "__main__":
    _run_tests()
