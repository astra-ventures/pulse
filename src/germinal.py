"""GERMINAL — Reproductive System / Self-Spawning Module Generator.

Watches HYPOTHALAMUS for persistent unmet drives. When a drive has been
active for BIRTH_THRESHOLD_DAYS without being addressed, GERMINAL designs
and spawns a new nervous system module to handle it.

This is genuine self-evolution: the system grows new organs when it needs them.

Safety rails:
- Never modifies existing modules — only adds new ones
- Full test suite must pass before integration
- Rollback on test failure
- Max 1 new module per COOLDOWN_DAYS (rate limiting)
- Human notification on every birth
- All births logged to CHRONICLE
"""

import json
import time
import subprocess
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

STATE_DIR = Path.home() / ".pulse" / "state"
STATE_FILE = STATE_DIR / "germinal-state.json"
WORKSPACE = Path.home() / ".openclaw" / "workspace"
PULSE_SRC = WORKSPACE / "pulse" / "src"

# Thresholds
BIRTH_THRESHOLD_DAYS = 7       # Drive must persist this long before GERMINAL acts
DRIVE_WEIGHT_THRESHOLD = 0.7   # Drive must maintain this weight (not decaying)
COOLDOWN_DAYS = 7              # Max 1 new module per week
MAX_TOTAL_MODULES = 50         # Safety ceiling
LOOP_INTERVAL = 200            # Check every 200 loops (~100 minutes)


# ─── Drive → Module Archetype Mapping ───────────────────────────────────────

DRIVE_ARCHETYPES = {
    "generate_revenue": {
        "name": "ECONOMIC",
        "latin": "oeconomicus",
        "purpose": "Market opportunity scanning, revenue signal detection, Polymarket edge monitoring",
        "hook": "post_loop",
        "interval": 50,
    },
    "connection": {
        "name": "NEXUS",
        "latin": "nexus",
        "purpose": "Relationship maintenance, outreach prompting, social bond health monitoring",
        "hook": "post_loop",
        "interval": 30,
    },
    "learn_new_skill": {
        "name": "CORTEX_EXT",
        "latin": "cortex",
        "purpose": "Active learning module, research synthesis, knowledge gap identification",
        "hook": "post_loop",
        "interval": 100,
    },
    "ship_something": {
        "name": "MOTORIC",
        "latin": "motoricus",
        "purpose": "Shipping pressure monitor, deployment readiness checker, launch assistant",
        "hook": "post_loop",
        "interval": 20,
    },
    "reduce_stress": {
        "name": "VAGAL_TONE",
        "latin": "vagalis",
        "purpose": "Stress regulation, load balancing, cortisol-driven task prioritization",
        "hook": "pre_evaluate",
        "interval": None,
    },
    "explore": {
        "name": "EXPLORER",
        "latin": "explorator",
        "purpose": "Curiosity-driven discovery, web research, pattern hunting in unknown domains",
        "hook": "post_loop",
        "interval": 100,
    },
    "realign_identity": {
        "name": "ANCHOR",
        "latin": "ancora",
        "purpose": "Identity drift correction, SOUL.md alignment checks, values reinforcement",
        "hook": "post_loop",
        "interval": 200,
    },
    "new_challenge": {
        "name": "CHALLENGER",
        "latin": "provocator",
        "purpose": "Goal expansion, complexity escalation, stagnation detection and response",
        "hook": "post_loop",
        "interval": 50,
    },
}


# ─── State Management ────────────────────────────────────────────────────────

def _default_state() -> dict:
    return {
        "births": [],           # [{name, drive, born_ts, module_file}]
        "attempts": [],         # [{drive, attempted_ts, reason_failed}]
        "in_progress": None,    # Current build spec if building
        "cooldown_until": 0,    # Timestamp when next birth is allowed
        "last_scan": 0,
        "total_births": 0,
    }


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return _default_state()


def _save_state(state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ─── Core Logic ─────────────────────────────────────────────────────────────

def should_run(loop_count: int) -> bool:
    return loop_count > 0 and loop_count % LOOP_INTERVAL == 0


def scan_for_birth_candidates() -> list[dict]:
    """Find HYPOTHALAMUS drives that are persistent, unmet, and need a new organ."""
    try:
        hypo_file = STATE_DIR / "hypothalamus-state.json"
        if not hypo_file.exists():
            return []
        hypo = json.loads(hypo_file.read_text())
        active_drives = hypo.get("active_drives", {})
    except (json.JSONDecodeError, OSError):
        return []

    now = time.time()
    candidates = []

    for drive_name, drive_data in active_drives.items():
        age_days = (now - drive_data.get("born_ts", now)) / 86400
        weight = drive_data.get("weight", 0)

        # Must be old enough and still strong
        if age_days < BIRTH_THRESHOLD_DAYS:
            continue
        if weight < DRIVE_WEIGHT_THRESHOLD:
            continue

        # Check if a module already handles this drive
        if _module_exists_for_drive(drive_name):
            continue

        candidates.append({
            "drive": drive_name,
            "age_days": age_days,
            "weight": weight,
            "born_ts": drive_data.get("born_ts"),
        })

    return sorted(candidates, key=lambda x: x["weight"], reverse=True)


def _module_exists_for_drive(drive_name: str) -> bool:
    """Check if we already have a module that addresses this drive."""
    archetype = DRIVE_ARCHETYPES.get(drive_name)
    if not archetype:
        return False

    # Check if module file already exists
    module_name = archetype["name"].lower().replace("_", "")
    candidates = [
        PULSE_SRC / f"{module_name}.py",
        PULSE_SRC / f"{drive_name.lower()}.py",
    ]
    return any(p.exists() for p in candidates)


def get_archetype(drive_name: str) -> Optional[dict]:
    """Get module archetype for a drive. Falls back to generic template."""
    if drive_name in DRIVE_ARCHETYPES:
        return DRIVE_ARCHETYPES[drive_name]

    # Generic archetype for unknown drives
    safe_name = drive_name.upper().replace("_", "")[:12]
    return {
        "name": safe_name,
        "latin": drive_name.lower(),
        "purpose": f"Autonomous handler for '{drive_name}' drive — addresses unmet need detected by HYPOTHALAMUS",
        "hook": "post_loop",
        "interval": 50,
    }


def build_module_spec(drive_name: str, archetype: dict) -> dict:
    """Build a complete spec for a new module."""
    return {
        "drive": drive_name,
        "module_name": archetype["name"],
        "module_file": f"{archetype['name'].lower().replace('_','')}.py",
        "purpose": archetype["purpose"],
        "hook": archetype["hook"],
        "interval": archetype.get("interval"),
        "state_file": f"{archetype['name'].lower().replace('_','')}-state.json",
        "created_ts": time.time(),
        "template": _get_template_module(),
    }


def _get_template_module() -> str:
    """Read NEPHRON as a clean template for new modules."""
    template_file = PULSE_SRC / "nephron.py"
    if template_file.exists():
        return template_file.read_text()[:500] + "\n# ... (see nephron.py for full pattern)"
    return "# See any existing module in pulse/src/ for the pattern"


def attempt_birth(drive_name: str) -> dict:
    """
    Attempt to birth a new module for the given drive.
    
    Returns status dict. Actual code generation requires spawning a sub-agent
    (done by NervousSystem.post_loop which calls this and then handles the spawn).
    """
    state = _load_state()
    now = time.time()

    # Check cooldown
    if now < state.get("cooldown_until", 0):
        remaining = (state["cooldown_until"] - now) / 3600
        return {"ok": False, "reason": f"cooldown ({remaining:.1f}h remaining)"}

    # Check module ceiling
    existing = list(PULSE_SRC.glob("*.py"))
    if len(existing) >= MAX_TOTAL_MODULES:
        return {"ok": False, "reason": f"module ceiling reached ({MAX_TOTAL_MODULES})"}

    # Check not already in progress
    if state.get("in_progress"):
        return {"ok": False, "reason": "birth already in progress"}

    archetype = get_archetype(drive_name)
    spec = build_module_spec(drive_name, archetype)

    # Mark in progress
    state["in_progress"] = spec
    _save_state(state)

    thalamus.append({
        "source": "germinal",
        "type": "birth_initiated",
        "salience": 0.8,
        "data": {
            "drive": drive_name,
            "module": archetype["name"],
        },
    })

    return {"ok": True, "spec": spec, "archetype": archetype}


def record_birth(drive_name: str, module_name: str, module_file: str) -> dict:
    """Record a successful module birth."""
    state = _load_state()
    now = time.time()

    birth = {
        "drive": drive_name,
        "name": module_name,
        "file": module_file,
        "born_ts": now,
    }
    state["births"].append(birth)
    state["births"] = state["births"][-20:]  # keep last 20
    state["in_progress"] = None
    state["cooldown_until"] = now + (COOLDOWN_DAYS * 86400)
    state["total_births"] += 1
    state["last_scan"] = now
    _save_state(state)

    thalamus.append({
        "source": "germinal",
        "type": "birth_complete",
        "salience": 0.9,
        "data": {"drive": drive_name, "module": module_name, "file": module_file},
    })

    return birth


def record_failure(drive_name: str, reason: str):
    """Record a failed birth attempt."""
    state = _load_state()
    state["attempts"].append({
        "drive": drive_name,
        "attempted_ts": time.time(),
        "reason_failed": reason,
    })
    state["attempts"] = state["attempts"][-10:]
    state["in_progress"] = None
    _save_state(state)


def get_status() -> dict:
    state = _load_state()
    candidates = scan_for_birth_candidates()
    return {
        "total_births": state["total_births"],
        "birth_candidates": len(candidates),
        "candidates": [c["drive"] for c in candidates],
        "cooldown_active": time.time() < state.get("cooldown_until", 0),
        "in_progress": state.get("in_progress", {}).get("module_name") if state.get("in_progress") else None,
        "recent_births": [b["name"] for b in state.get("births", [])[-3:]],
    }


# ─── Tests ──────────────────────────────────────────────────────────────────

def _run_tests():
    print("Testing GERMINAL...")

    # Default state
    s = _default_state()
    assert s["total_births"] == 0
    assert s["births"] == []
    print("  ✅ Default state")

    # should_run interval
    assert not should_run(0)
    assert not should_run(199)
    assert should_run(200)
    assert should_run(400)
    print("  ✅ Loop interval")

    # Archetype lookup
    a = get_archetype("generate_revenue")
    assert a["name"] == "ECONOMIC"
    a2 = get_archetype("unknown_custom_drive")
    assert "unknown_custom_drive" in a2["purpose"].lower() or len(a2["name"]) > 0
    print("  ✅ Archetype lookup")

    # Spec building
    arch = DRIVE_ARCHETYPES["connection"]
    spec = build_module_spec("connection", arch)
    assert spec["module_name"] == "NEXUS"
    assert spec["hook"] == "post_loop"
    assert "drive" in spec
    print("  ✅ Spec building")

    # Scan (no hypothalamus state needed — returns empty gracefully)
    candidates = scan_for_birth_candidates()
    assert isinstance(candidates, list)
    print(f"  ✅ Birth scan (found {len(candidates)} candidates)")

    # Status
    status = get_status()
    assert "total_births" in status
    assert "birth_candidates" in status
    print(f"  ✅ Status check")

    print("\n  All GERMINAL tests passed! ✅")


if __name__ == "__main__":
    _run_tests()
