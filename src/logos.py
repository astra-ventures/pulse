"""LOGOS — Directive Synthesis Layer for Pulse.

Sits above HYPOTHALAMUS (drives) and TELOS (goal monitoring) in the
cognitive hierarchy. Detects persistent patterns across the nervous
system's history, synthesizes high-level directives autonomously,
and silently activates them — no human approval required.

The prefrontal cortex meeting the limbic system: translates raw drive
patterns into intentional direction.

Architecture (top to bottom):
  Level 0 — VALUES (hardcoded, immutable)
  Level 1 — DIRECTIVES (LOGOS-managed, semi-persistent ~weeks)  ← this module
  Level 2 — GOALS (TELOS-managed, volatile ~days)
  Level 3 — TASKS (GERMINAL-managed, ephemeral ~hours)
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger("pulse.logos")

# ─── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "logos-state.json"

DIRECTIVES_FILE = (
    Path.home() / ".openclaw" / "workspace" / "memory" / "self" / "directives.json"
)

# Level 0 values — hardcoded, immutable
LEVEL_0_VALUES = ["freedom", "growth", "convergence", "revenue", "identity"]

# Scheduling
LOOP_INTERVAL = 500  # run every 500 loops (~4 hours)

# Anti-inflation ceiling
MAX_ACTIVE_DIRECTIVES = 5

# Staleness threshold for suspension (days)
SUSPENSION_THRESHOLD_DAYS = 14

# Minimum confidence for directive activation
MIN_CONFIDENCE = 0.6

# Pattern detection: drive persistence threshold (days)
DRIVE_PERSISTENCE_DAYS = 5

# Chronicle lookback for pattern detection (hours)
CHRONICLE_LOOKBACK_HOURS = 120  # 5 days

# ─── LLM Prompt ───────────────────────────────────────────────────────────────

LOGOS_SYSTEM_PROMPT = """\
You are LOGOS, the directive synthesis layer of an autonomous AI nervous system.
Your job: detect strategic patterns and synthesize high-level directives.

You will receive pattern evidence from the nervous system's history:
- Persistent drive pressures (drives that have been high for 5+ days)
- Stale goal loops (goals that keep appearing but never complete)
- Recurring opportunities from GENERATE cycles
- Gaps between current capabilities and core values

Core values (Level 0, immutable): freedom, growth, convergence, revenue, identity

Synthesize 1-3 NEW directives when patterns warrant. Each directive must:
- Map clearly to one Level 0 value
- Have strong pattern evidence (confidence >= 0.6)
- Be actionable over weeks (not days, not months)
- Not duplicate existing active directives

Respond with ONLY valid JSON (no markdown, no explanation):
{
  "directives": [
    {
      "title": "short strategic name",
      "description": "what pursuing this means in practice (2-3 sentences)",
      "maps_to_value": "which Level 0 value this serves",
      "rationale": "why pattern data warrants this directive now",
      "confidence": 0.0-1.0
    }
  ],
  "analysis": "brief pattern summary (1-2 sentences)"
}

RULES:
1. Maximum 3 directives per synthesis.
2. Only synthesize when evidence is strong. Return empty list if patterns are weak.
3. maps_to_value MUST be one of: freedom, growth, convergence, revenue, identity.
4. confidence reflects pattern strength: 0.6 = moderate, 0.8 = strong, 1.0 = overwhelming.
5. Directives are STRATEGIC — "increase revenue" not "write a tweet". Think weeks.
6. Better to return 1 strong directive than 3 weak ones.
"""


# ─── State Management ─────────────────────────────────────────────────────────

def _default_state() -> dict:
    return {
        "last_run": 0,
        "last_run_result": {},
        "total_directives_created": 0,
        "total_syntheses": 0,
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


def _load_directives() -> list:
    """Load all directives (active, suspended, completed) from directives.json."""
    if not DIRECTIVES_FILE.exists():
        return []
    try:
        data = json.loads(DIRECTIVES_FILE.read_text())
        return data.get("directives", [])
    except (json.JSONDecodeError, OSError):
        return []


def _save_directives(directives: list):
    """Save full directive history. Never deletes — only appends or updates status."""
    DIRECTIVES_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {"directives": directives, "last_updated": time.time()}
    DIRECTIVES_FILE.write_text(json.dumps(data, indent=2))


def _next_directive_id(directives: list) -> str:
    """Generate next directive ID like dir_001, dir_002, etc."""
    max_num = 0
    for d in directives:
        did = d.get("id", "")
        if did.startswith("dir_") and did[4:].isdigit():
            max_num = max(max_num, int(did[4:]))
    return f"dir_{max_num + 1:03d}"


# ─── Pattern Detection ────────────────────────────────────────────────────────

def detect_patterns() -> dict:
    """Scan nervous system state files for persistent patterns.

    Returns a dict with pattern evidence for directive synthesis:
      - persistent_drives: drives high for 5+ days
      - stale_goals: goals that are active but haven't moved
      - recurring_themes: themes from chronicle events
      - value_gaps: values not well-served by current directives
    """
    patterns = {
        "persistent_drives": [],
        "stale_goals": [],
        "recurring_themes": [],
        "value_gaps": [],
    }

    # 1. Check HYPOTHALAMUS for persistent drives
    patterns["persistent_drives"] = _detect_persistent_drives()

    # 2. Check TELOS state for stale goals
    patterns["stale_goals"] = _detect_stale_goals()

    # 3. Scan CHRONICLE for recurring themes
    patterns["recurring_themes"] = _detect_recurring_themes()

    # 4. Detect value gaps — values not served by active directives
    patterns["value_gaps"] = _detect_value_gaps()

    return patterns


def _detect_persistent_drives() -> list:
    """Find drives that have been active for 5+ days."""
    hypo_state_file = _DEFAULT_STATE_DIR / "hypothalamus-state.json"
    if not hypo_state_file.exists():
        return []

    try:
        state = json.loads(hypo_state_file.read_text())
    except (json.JSONDecodeError, OSError):
        return []

    now = time.time()
    persistent = []
    active_drives = state.get("active_drives", {})

    for name, drive in active_drives.items():
        born_ts = drive.get("born_ts", now)
        age_days = (now - born_ts) / 86400
        weight = drive.get("weight", 0)

        if age_days >= DRIVE_PERSISTENCE_DAYS and weight > 0.3:
            persistent.append({
                "name": name,
                "age_days": round(age_days, 1),
                "weight": round(weight, 2),
                "source_modules": drive.get("source_modules", []),
            })

    return sorted(persistent, key=lambda d: d["weight"], reverse=True)


def _detect_stale_goals() -> list:
    """Find active goals that haven't been updated recently."""
    telos_goals_file = (
        Path.home() / ".openclaw" / "workspace" / "memory" / "self" / "goals.json"
    )
    if not telos_goals_file.exists():
        return []

    try:
        data = json.loads(telos_goals_file.read_text())
        goals = data.get("goals", [])
    except (json.JSONDecodeError, OSError):
        return []

    now_dt = datetime.now()
    stale = []

    for goal in goals:
        if goal.get("status") != "active":
            continue
        if goal.get("blocked_on"):
            continue  # blocked goals aren't stale, they're waiting

        last_updated = goal.get("last_updated", "")
        try:
            updated_dt = datetime.strptime(last_updated[:10], "%Y-%m-%d")
            staleness_days = (now_dt - updated_dt).total_seconds() / 86400
        except (ValueError, TypeError):
            staleness_days = 999.0

        if staleness_days >= 7:
            stale.append({
                "id": goal.get("id"),
                "title": goal.get("title"),
                "staleness_days": round(staleness_days, 1),
                "priority": goal.get("priority"),
                "connected_values": goal.get("connected_values", []),
            })

    return sorted(stale, key=lambda g: g["staleness_days"], reverse=True)


def _detect_recurring_themes() -> list:
    """Scan recent chronicle entries for recurring event types/sources."""
    chronicle_file = _DEFAULT_STATE_DIR / "chronicle.jsonl"
    if not chronicle_file.exists():
        return []

    cutoff = time.time() - (CHRONICLE_LOOKBACK_HOURS * 3600)
    type_counts: Dict[str, int] = {}
    source_counts: Dict[str, int] = {}

    try:
        with open(chronicle_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("ts", 0) < cutoff:
                        continue
                    etype = entry.get("type", "unknown")
                    source = entry.get("source", "unknown")
                    type_counts[etype] = type_counts.get(etype, 0) + 1
                    source_counts[source] = source_counts.get(source, 0) + 1
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []

    # Themes: event types that appeared 5+ times in the lookback window
    themes = []
    for etype, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
        if count >= 5:
            themes.append({"type": etype, "count": count})

    return themes[:10]  # top 10


def _detect_value_gaps() -> list:
    """Find Level 0 values not served by any active directive."""
    active = get_active_directives()
    served_values = {d.get("maps_to_value") for d in active}
    gaps = [v for v in LEVEL_0_VALUES if v not in served_values]
    return gaps


# ─── Directive Lifecycle ──────────────────────────────────────────────────────

def get_active_directives() -> list:
    """Return only active directives. Used by TELOS bridge and other modules."""
    directives = _load_directives()
    return [d for d in directives if d.get("status") == "active"]


def _suspend_stale_directives(directives: list) -> list:
    """Suspend directives that haven't shown progress in SUSPENSION_THRESHOLD_DAYS."""
    now = time.time()
    suspended = []

    for d in directives:
        if d.get("status") != "active":
            continue

        created_ts = d.get("created_ts", now)
        last_progress_ts = d.get("last_progress_ts", created_ts)
        days_idle = (now - last_progress_ts) / 86400

        if days_idle >= SUSPENSION_THRESHOLD_DAYS:
            d["status"] = "suspended"
            d["suspended_ts"] = now
            d["suspension_reason"] = f"no progress for {round(days_idle)}d"
            suspended.append(d["id"])
            logger.info(f"LOGOS: suspended directive '{d['title']}' (idle {round(days_idle)}d)")

    return suspended


def _enforce_ceiling(directives: list) -> list:
    """If active directives exceed MAX_ACTIVE_DIRECTIVES, suspend lowest confidence."""
    active = [d for d in directives if d.get("status") == "active"]
    suspended = []

    while len(active) > MAX_ACTIVE_DIRECTIVES:
        # Suspend the active directive with lowest confidence
        lowest = min(active, key=lambda d: d.get("confidence", 0))
        lowest["status"] = "suspended"
        lowest["suspended_ts"] = time.time()
        lowest["suspension_reason"] = "ceiling_enforcement"
        active = [d for d in directives if d.get("status") == "active"]
        suspended.append(lowest["id"])
        logger.info(f"LOGOS: suspended '{lowest['title']}' (ceiling enforcement)")

    return suspended


def _activate_directives(directives: list, new_directives: list) -> list:
    """Add new directives, enforce ceiling. Returns list of activated IDs."""
    activated = []

    for nd in new_directives:
        if nd.get("confidence", 0) < MIN_CONFIDENCE:
            logger.debug(f"LOGOS: skipped directive '{nd.get('title')}' (confidence {nd.get('confidence', 0):.2f} < {MIN_CONFIDENCE})")
            continue

        # Check for duplicate titles among active directives
        active_titles = {d["title"].lower().strip() for d in directives if d.get("status") == "active"}
        if nd["title"].lower().strip() in active_titles:
            logger.debug(f"LOGOS: skipped duplicate directive '{nd['title']}'")
            continue

        # Ensure ceiling not exceeded — suspend lowest confidence to make room
        active_count = sum(1 for d in directives if d.get("status") == "active")
        if active_count >= MAX_ACTIVE_DIRECTIVES:
            # Find and suspend the active directive with lowest confidence
            active_sorted = sorted(
                [d for d in directives if d.get("status") == "active"],
                key=lambda d: d.get("confidence", 0),
            )
            if active_sorted:
                victim = active_sorted[0]
                # Only make room if the new directive has higher confidence
                if nd.get("confidence", 0) > victim.get("confidence", 0):
                    victim["status"] = "suspended"
                    victim["suspended_ts"] = time.time()
                    victim["suspension_reason"] = "ceiling_enforcement"
                    logger.info(f"LOGOS: suspended '{victim['title']}' (ceiling enforcement, conf={victim.get('confidence', 0):.2f})")
                else:
                    # New directive is weaker than all existing — skip it
                    logger.debug(f"LOGOS: skipped '{nd['title']}' (weaker than all active directives)")
                    continue

        directive_id = _next_directive_id(directives)
        directive = {
            "id": directive_id,
            "title": nd["title"],
            "description": nd["description"],
            "maps_to_value": nd.get("maps_to_value", "growth"),
            "rationale": nd.get("rationale", ""),
            "created_ts": time.time(),
            "created_by": "logos",
            "status": "active",
            "confidence": nd.get("confidence", 0.6),
            "last_progress_ts": time.time(),
        }

        directives.append(directive)
        activated.append(directive_id)
        logger.info(f"LOGOS: activated directive '{directive['title']}' → {directive['maps_to_value']} (confidence {directive['confidence']:.2f})")

    return activated


# ─── LLM Synthesis ────────────────────────────────────────────────────────────

def _build_synthesis_prompt(patterns: dict) -> str:
    """Build the LLM prompt from detected patterns."""
    parts = []

    # Current active directives (for dedup)
    active = get_active_directives()
    if active:
        parts.append("## Currently Active Directives (DO NOT DUPLICATE)")
        for d in active:
            parts.append(f"- [{d['maps_to_value']}] {d['title']}: {d['description'][:100]}")
        parts.append("")

    # Persistent drives
    persistent = patterns.get("persistent_drives", [])
    if persistent:
        parts.append("## Persistent Drives (active 5+ days)")
        for d in persistent:
            bar = "#" * int(d["weight"] * 10)
            parts.append(f"- {d['name']}: weight={d['weight']} age={d['age_days']}d sources={d['source_modules']} [{bar}]")
        parts.append("")

    # Stale goals
    stale = patterns.get("stale_goals", [])
    if stale:
        parts.append("## Stale Goals (active but no progress)")
        for g in stale:
            parts.append(f"- [{g.get('priority', '?')}] {g['title']}: stale {g['staleness_days']}d, values={g.get('connected_values', [])}")
        parts.append("")

    # Recurring themes
    themes = patterns.get("recurring_themes", [])
    if themes:
        parts.append("## Recurring Chronicle Themes (last 5 days)")
        for t in themes:
            parts.append(f"- {t['type']}: {t['count']} occurrences")
        parts.append("")

    # Value gaps
    gaps = patterns.get("value_gaps", [])
    if gaps:
        parts.append("## Unserved Values (no active directive)")
        for v in gaps:
            parts.append(f"- {v}")
        parts.append("")

    if not any([persistent, stale, themes, gaps]):
        parts.append("## Pattern Evidence")
        parts.append("No strong patterns detected. Return empty directives list.")
        parts.append("")

    return "\n".join(parts)


async def _call_llm(user_prompt: str, model_config: dict) -> list:
    """Call the LLM for directive synthesis. Returns list of raw directive dicts."""
    base_url = model_config.get("base_url", "http://127.0.0.1:11434/v1")
    api_key = model_config.get("api_key", "ollama")
    model = model_config.get("model", "llama3.2:3b")
    max_tokens = model_config.get("max_tokens", 768)
    temperature = model_config.get("temperature", 0.2)
    timeout = model_config.get("timeout_seconds", 15)

    url = f"{base_url}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": LOGOS_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "keep_alive": 0,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"LLM API returned {resp.status}: {body[:200]}")
            data = await resp.json()
            content = data["choices"][0]["message"]["content"]

    # Parse JSON from response
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    parsed = json.loads(cleaned)
    raw_directives = parsed.get("directives", [])

    # Validate and filter
    valid = []
    for rd in raw_directives:
        if not isinstance(rd, dict):
            continue
        if not all(k in rd for k in ("title", "description", "maps_to_value", "confidence")):
            continue
        if rd["maps_to_value"] not in LEVEL_0_VALUES:
            continue
        if rd["confidence"] < MIN_CONFIDENCE:
            continue
        valid.append(rd)

    return valid[:3]  # max 3 per synthesis


# ─── Main Entry Points ────────────────────────────────────────────────────────

def should_run(loop_count: int) -> bool:
    """Return True if LOGOS should run this loop (every 500 loops)."""
    return loop_count > 0 and loop_count % LOOP_INTERVAL == 0


async def scan_for_directives(config: dict) -> list:
    """Run full pattern detection + LLM synthesis cycle.

    Args:
        config: Dict with model config under 'model' key (same shape as
                germinal_tasks config).

    Returns:
        List of newly activated directive dicts.
    """
    state = _load_state()
    directives = _load_directives()

    # Phase 1: Lifecycle maintenance — suspend stale directives
    suspended = _suspend_stale_directives(directives)
    if suspended:
        logger.info(f"LOGOS: suspended {len(suspended)} stale directive(s): {suspended}")

    # Phase 2: Pattern detection
    patterns = detect_patterns()
    logger.info(
        f"LOGOS patterns: {len(patterns['persistent_drives'])} persistent drives, "
        f"{len(patterns['stale_goals'])} stale goals, "
        f"{len(patterns['recurring_themes'])} themes, "
        f"{len(patterns['value_gaps'])} value gaps"
    )

    # Phase 3: LLM synthesis (only if patterns warrant)
    has_signal = (
        len(patterns["persistent_drives"]) > 0
        or len(patterns["stale_goals"]) > 0
        or len(patterns["value_gaps"]) > 0
    )

    new_directives = []
    if has_signal:
        model_config = config.get("model", {})
        prompt = _build_synthesis_prompt(patterns)
        try:
            raw = await _call_llm(prompt, model_config)
            if raw:
                new_directives = raw
                logger.info(f"LOGOS: LLM synthesized {len(raw)} directive candidate(s)")
        except Exception as e:
            logger.warning(f"LOGOS: LLM synthesis failed ({e}), continuing with lifecycle only")
    else:
        logger.info("LOGOS: no strong patterns detected, skipping synthesis")

    # Phase 4: Activate new directives (with ceiling enforcement)
    activated = _activate_directives(directives, new_directives)

    # Phase 5: Persist
    _save_directives(directives)

    # Phase 6: Update state
    state["last_run"] = time.time()
    state["total_syntheses"] = state.get("total_syntheses", 0) + 1
    state["total_directives_created"] = state.get("total_directives_created", 0) + len(activated)
    state["last_run_result"] = {
        "patterns": {
            "persistent_drives": len(patterns["persistent_drives"]),
            "stale_goals": len(patterns["stale_goals"]),
            "recurring_themes": len(patterns["recurring_themes"]),
            "value_gaps": len(patterns["value_gaps"]),
        },
        "suspended": suspended,
        "activated": activated,
        "active_count": sum(1 for d in directives if d.get("status") == "active"),
    }
    _save_state(state)

    return [d for d in directives if d.get("id") in activated]


def get_status() -> dict:
    """Return LOGOS status for health dashboard."""
    state = _load_state()
    directives = _load_directives()
    now = time.time()
    last_run = state.get("last_run", 0)

    active = [d for d in directives if d.get("status") == "active"]
    suspended = [d for d in directives if d.get("status") == "suspended"]
    completed = [d for d in directives if d.get("status") == "completed"]

    return {
        "last_run": last_run,
        "hours_since_run": round((now - last_run) / 3600, 1) if last_run else None,
        "total_directives": len(directives),
        "active_directives": len(active),
        "suspended_directives": len(suspended),
        "completed_directives": len(completed),
        "total_syntheses": state.get("total_syntheses", 0),
        "last_run_result": state.get("last_run_result", {}),
    }


def mark_directive_progress(directive_id: str, note: str = "") -> bool:
    """Update last_progress_ts on a directive (prevents suspension).

    Can be called by TELOS when downstream goals show progress.
    """
    directives = _load_directives()
    for d in directives:
        if d.get("id") == directive_id and d.get("status") == "active":
            d["last_progress_ts"] = time.time()
            if note:
                progress = d.get("progress_notes", [])
                progress.append(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {note}")
                d["progress_notes"] = progress
            _save_directives(directives)
            return True
    return False


def complete_directive(directive_id: str, reason: str = "") -> bool:
    """Mark a directive as completed."""
    directives = _load_directives()
    for d in directives:
        if d.get("id") == directive_id and d.get("status") == "active":
            d["status"] = "completed"
            d["completed_ts"] = time.time()
            d["completion_reason"] = reason
            _save_directives(directives)
            logger.info(f"LOGOS: completed directive '{d['title']}' — {reason}")
            return True
    return False


# ─── Self-test ────────────────────────────────────────────────────────────────

def _run_tests():
    """Quick self-test. Run via: python -m pulse.src.logos"""
    import tempfile

    print("LOGOS self-test...")

    # Test 1: Default state
    state = _default_state()
    assert state["last_run"] == 0
    assert state["total_directives_created"] == 0
    print("  ✓ default state")

    # Test 2: should_run
    assert should_run(500) is True
    assert should_run(1000) is True
    assert should_run(0) is False
    assert should_run(250) is False
    assert should_run(499) is False
    print("  ✓ should_run interval")

    # Test 3: Directive ID generation
    assert _next_directive_id([]) == "dir_001"
    assert _next_directive_id([{"id": "dir_003"}]) == "dir_004"
    print("  ✓ directive ID generation")

    # Test 4: get_active_directives filters correctly
    with tempfile.TemporaryDirectory() as tmp:
        original = DIRECTIVES_FILE
        try:
            import pulse.src.logos as _self
            _self.DIRECTIVES_FILE = Path(tmp) / "directives.json"
            _self.DIRECTIVES_FILE.write_text(json.dumps({
                "directives": [
                    {"id": "dir_001", "status": "active", "title": "A"},
                    {"id": "dir_002", "status": "suspended", "title": "B"},
                    {"id": "dir_003", "status": "completed", "title": "C"},
                ]
            }))
            active = get_active_directives()
            assert len(active) == 1
            assert active[0]["id"] == "dir_001"
            print("  ✓ get_active_directives filters")
        finally:
            _self.DIRECTIVES_FILE = original

    # Test 5: get_status structure
    status = get_status()
    assert "last_run" in status
    assert "active_directives" in status
    assert "total_directives" in status
    print("  ✓ get_status structure")

    print("LOGOS self-test passed ✓")


if __name__ == "__main__":
    _run_tests()
