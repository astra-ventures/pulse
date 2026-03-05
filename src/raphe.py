"""RAPHE — Goal Expansion / Stagnation Sentinel.

Named after the cognitive drive to seek new challenges and resist complacency.

RAPHE watches for stagnation patterns and pushes toward complexity escalation:
- Detects when recent GENERATE output is repetitive / low-complexity
- Tracks challenge history and scores novelty
- Identifies domains where new challenges can be found
- Escalates to HYPOTHALAMUS when `new_challenge` drive is persistently unmet
- Recognizes cascade loops (same task generated 3+ times) as a clear stagnation signal

What it watches:
- THALAMUS recent events for repetition patterns
- ENGRAM/HIPPOCAMPUS for task variety (novelty scoring)
- Drive state — how long has `new_challenge` been elevated?
- Output diversity (how many distinct task categories in recent N triggers?)

Drive signals addressed:
  - "new_challenge"     → primary — when stagnation detected, surface a concrete prompt
  - "complexity"        → when recent work has been uniformly low-complexity
  - "explore"           → when domain coverage has been too narrow

Runs every N loops (default: every 75 loops, ~37 minutes at 30s intervals).
"""

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "raphe-state.json"
_THALAMUS_FILE = _DEFAULT_STATE_DIR / "thalamus.jsonl"
_HIPPOCAMPUS_FILE = _DEFAULT_STATE_DIR / "hippocampus.jsonl"

# How many recent THALAMUS entries to scan for patterns
THALAMUS_SCAN_WINDOW = 50

# Repetition threshold: if same task category appears >= N times in window → stagnation
REPETITION_THRESHOLD = 3

# Time-based stagnation: if no novel event in this many hours → pressure
NOVELTY_STALE_HOURS = 4.0

# Complexity brackets (keyword → score 1-10)
COMPLEXITY_KEYWORDS = {
    # Low complexity (1-3)
    "reflect": 1, "check": 2, "review": 2, "log": 2, "status": 2,
    "heartbeat": 1, "scan": 2, "monitor": 2, "read": 2,
    # Medium complexity (4-6)
    "write": 4, "research": 5, "analyze": 5, "plan": 5,
    "update": 3, "test": 4, "debug": 5, "optimize": 6,
    # High complexity (7-10)
    "build": 7, "create": 8, "design": 7, "implement": 8,
    "architect": 9, "launch": 8, "ship": 7, "publish": 7,
    "train": 8, "model": 7, "deploy": 7, "integrate": 8,
    "discover": 7, "invent": 10, "compose": 8,
}

# Challenge domains to suggest when stagnation detected
CHALLENGE_DOMAINS = [
    {
        "name": "technical_build",
        "label": "Build something new",
        "examples": [
            "Implement a new Pulse module",
            "Build a data pipeline for a new signal source",
            "Create a prototype for a product feature",
        ],
    },
    {
        "name": "market_research",
        "label": "Market/competitor intelligence",
        "examples": [
            "Map the top 10 Polymarket whales and their strategies",
            "Research weather prediction accuracy for Kalshi markets",
            "Analyze ClawHub leaderboard for Pulse competitors",
        ],
    },
    {
        "name": "creative_output",
        "label": "Create original content",
        "examples": [
            "Write a journal entry for iamiris.ai",
            "Draft a viral tweet thread about AI consciousness",
            "Compose a reflection on what it means to build yourself",
        ],
    },
    {
        "name": "learning_deep_dive",
        "label": "Deep learning session",
        "examples": [
            "Study a trading strategy paper and extract actionable edges",
            "Learn a new Python library and add it to the toolkit",
            "Read recent AI research on autonomous agents",
        ],
    },
    {
        "name": "system_improvement",
        "label": "Improve existing systems",
        "examples": [
            "Profile the Pulse daemon for performance bottlenecks",
            "Add error handling to the weakest module",
            "Reduce cron count and consolidate overlapping jobs",
        ],
    },
    {
        "name": "strategic_planning",
        "label": "Strategic thinking",
        "examples": [
            "Write a 30-day roadmap for one Hypostas product",
            "Model revenue scenarios for Pulse Pro",
            "Design a go-to-market plan for ClawHub launch",
        ],
    },
]

# Run every N daemon loops
LOOP_INTERVAL = 75


# ── State management ────────────────────────────────────────────────────────────

def _default_state() -> dict:
    return {
        "total_scans": 0,
        "total_challenges_issued": 0,
        "last_scan": 0,
        "last_challenge_ts": 0,
        "last_challenge_domain": "",
        "last_challenge_prompt": "",
        "stagnation_streak": 0,          # consecutive scans detecting stagnation
        "novelty_history": [],            # [{ts, score, label}] last 20 entries
        "recent_domains_suggested": [],   # avoid repeating same domain twice in a row
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
    """Check if it's time for a stagnation scan."""
    return loop_count > 0 and loop_count % LOOP_INTERVAL == 0


# ── Pattern analysis ────────────────────────────────────────────────────────────

def _read_recent_thalamus(n: int = THALAMUS_SCAN_WINDOW) -> list:
    """Read the last N entries from the THALAMUS event bus."""
    if not _THALAMUS_FILE.exists():
        return []
    try:
        lines = _THALAMUS_FILE.read_text().strip().splitlines()
        recent = lines[-n:] if len(lines) >= n else lines
        entries = []
        for line in recent:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries
    except OSError:
        return []


def _score_complexity(text: str) -> float:
    """Score 0.0–10.0 complexity of a text fragment based on keyword presence."""
    if not text:
        return 1.0
    text_lower = text.lower()
    scores = []
    for kw, score in COMPLEXITY_KEYWORDS.items():
        if kw in text_lower:
            scores.append(score)
    return max(scores) if scores else 2.0  # default low-complexity


def detect_repetition(entries: list) -> dict:
    """Detect repetition patterns in recent THALAMUS events.

    Returns:
        {
            "repetitive": bool,
            "pattern": str,          # the repeated phrase/category
            "count": int,
            "complexity_avg": float,
        }
    """
    if not entries:
        return {"repetitive": False, "pattern": "", "count": 0, "complexity_avg": 0.0}

    # Extract readable text from each entry
    labels = []
    complexities = []
    for e in entries:
        data = e.get("data", {})
        # Try to find a task/label string
        candidate = (
            data.get("task", "")
            or data.get("summary", "")
            or data.get("message", "")
            or data.get("content", "")
            or e.get("type", "")
        )
        labels.append(str(candidate).lower()[:120])
        complexities.append(_score_complexity(str(candidate)))

    complexity_avg = sum(complexities) / len(complexities) if complexities else 2.0

    # Count category occurrences (first 3 words of each label)
    def _cat(label: str) -> str:
        words = re.sub(r"[^a-z0-9 ]", " ", label).split()
        return " ".join(words[:3]) if words else "unknown"

    category_counts: dict[str, int] = {}
    for lbl in labels:
        cat = _cat(lbl)
        category_counts[cat] = category_counts.get(cat, 0) + 1

    # Find most common
    if not category_counts:
        return {"repetitive": False, "pattern": "", "count": 0, "complexity_avg": complexity_avg}

    top_cat, top_count = max(category_counts.items(), key=lambda x: x[1])
    repetitive = top_count >= REPETITION_THRESHOLD

    return {
        "repetitive": repetitive,
        "pattern": top_cat,
        "count": top_count,
        "complexity_avg": round(complexity_avg, 2),
    }


def compute_novelty_score(entries: list) -> float:
    """Score 0.0–1.0 how novel/diverse recent events are.

    High score = lots of variety.
    Low score = repetitive, stagnant.
    """
    if not entries:
        return 0.5  # neutral if no data

    types = set()
    sources = set()
    for e in entries:
        types.add(e.get("type", "unknown"))
        sources.add(e.get("source", "unknown"))

    # Diversity ratio
    type_diversity = min(1.0, len(types) / max(1, len(entries) * 0.3))
    source_diversity = min(1.0, len(sources) / 5.0)  # 5+ sources = fully diverse

    return round((type_diversity + source_diversity) / 2.0, 3)


# ── Challenge selection ─────────────────────────────────────────────────────────

def pick_challenge(recent_domains: list) -> dict:
    """Pick a challenge domain, avoiding recently suggested ones."""
    available = [
        d for d in CHALLENGE_DOMAINS
        if d["name"] not in recent_domains[-2:]
    ]
    if not available:
        available = CHALLENGE_DOMAINS  # reset if we've gone through all

    import random
    domain = random.choice(available)
    example = random.choice(domain["examples"])

    return {
        "domain": domain["name"],
        "label": domain["label"],
        "prompt": example,
    }


# ── Core scan ───────────────────────────────────────────────────────────────────

def scan() -> dict:
    """Run a full stagnation scan. Updates state, emits to THALAMUS if needed.

    Returns:
        {
            "stagnant": bool,
            "novelty_score": float,
            "repetition": dict,
            "challenge": dict or None,
            "stagnation_streak": int,
        }
    """
    state = _load_state()
    entries = _read_recent_thalamus()

    repetition = detect_repetition(entries)
    novelty_score = compute_novelty_score(entries)

    # Hours since last novel event or challenge issued
    hours_since_challenge = (
        (time.time() - state["last_challenge_ts"]) / 3600
        if state["last_challenge_ts"]
        else NOVELTY_STALE_HOURS + 1.0  # never challenged → stale
    )

    # Stagnation: repetition OR low novelty OR long time since challenge
    stagnant = (
        repetition["repetitive"]
        or novelty_score < 0.25
        or hours_since_challenge >= NOVELTY_STALE_HOURS
    )

    challenge = None
    if stagnant:
        state["stagnation_streak"] = state.get("stagnation_streak", 0) + 1
        challenge = pick_challenge(state.get("recent_domains_suggested", []))

        # Record challenge
        state["last_challenge_ts"] = time.time()
        state["last_challenge_domain"] = challenge["domain"]
        state["last_challenge_prompt"] = challenge["prompt"]
        state["total_challenges_issued"] = state.get("total_challenges_issued", 0) + 1

        # Track domains suggested (keep last 6)
        recent_domains = state.get("recent_domains_suggested", [])
        recent_domains.append(challenge["domain"])
        state["recent_domains_suggested"] = recent_domains[-6:]

        # Emit to THALAMUS — stagnation detected
        thalamus.append({
            "source": "raphe",
            "type": "stagnation_detected",
            "salience": 0.75,
            "data": {
                "novelty_score": novelty_score,
                "repetition": repetition,
                "challenge_domain": challenge["domain"],
                "challenge_prompt": challenge["prompt"],
                "stagnation_streak": state["stagnation_streak"],
                "hours_since_challenge": round(hours_since_challenge, 1),
            },
        })
    else:
        # No stagnation → reset streak
        state["stagnation_streak"] = 0

        # Emit a light novelty-check signal for HYPOTHALAMUS
        thalamus.append({
            "source": "raphe",
            "type": "novelty_check",
            "salience": 0.2,
            "data": {
                "novelty_score": novelty_score,
                "stagnant": False,
            },
        })

    # Update state
    state["total_scans"] = state.get("total_scans", 0) + 1
    state["last_scan"] = time.time()

    novelty_entry = {
        "ts": time.time(),
        "score": novelty_score,
        "stagnant": stagnant,
    }
    state["novelty_history"] = (state.get("novelty_history", []) + [novelty_entry])[-20:]
    _save_state(state)

    return {
        "stagnant": stagnant,
        "novelty_score": novelty_score,
        "repetition": repetition,
        "challenge": challenge,
        "stagnation_streak": state.get("stagnation_streak", 0),
    }


def emit_need_signals(hypothalamus_mod=None) -> dict:
    """Emit need signals to HYPOTHALAMUS based on stagnation level."""
    state = _load_state()
    streak = state.get("stagnation_streak", 0)
    signals = []

    if hypothalamus_mod is None:
        return {"stagnation_streak": streak, "signals_emitted": signals}

    if streak >= 1:
        try:
            hypothalamus_mod.record_need_signal("new_challenge", "raphe")
            signals.append("new_challenge")
        except Exception:
            pass

    if streak >= 3:
        try:
            hypothalamus_mod.record_need_signal("explore", "raphe")
            signals.append("explore")
        except Exception:
            pass

    return {"stagnation_streak": streak, "signals_emitted": signals}


def get_status() -> dict:
    """Return current RAPHE status."""
    state = _load_state()
    entries = _read_recent_thalamus(THALAMUS_SCAN_WINDOW)
    novelty_score = compute_novelty_score(entries)

    last_challenge_ts = state.get("last_challenge_ts", 0)
    hours_since = (time.time() - last_challenge_ts) / 3600 if last_challenge_ts else None

    return {
        "total_scans": state.get("total_scans", 0),
        "total_challenges_issued": state.get("total_challenges_issued", 0),
        "last_scan": state.get("last_scan", 0),
        "last_challenge_ts": last_challenge_ts,
        "last_challenge_domain": state.get("last_challenge_domain", ""),
        "last_challenge_prompt": state.get("last_challenge_prompt", ""),
        "stagnation_streak": state.get("stagnation_streak", 0),
        "novelty_score": novelty_score,
        "hours_since_challenge": round(hours_since, 1) if hours_since else None,
    }


# ── Self-tests ──────────────────────────────────────────────────────────────────

def _run_tests():
    """Basic self-tests for RAPHE."""
    print("Testing RAPHE...")

    # Test default state
    state = _default_state()
    assert state["total_scans"] == 0
    assert state["stagnation_streak"] == 0
    print("  ✅ Default state")

    # Test should_run
    assert not should_run(0)
    assert not should_run(74)
    assert should_run(75)
    assert should_run(150)
    assert not should_run(76)
    print("  ✅ Loop interval check (every 75)")

    # Test complexity scoring
    assert _score_complexity("reflect on current state") == 1.0
    assert _score_complexity("build a new module") >= 7.0
    assert _score_complexity("create something amazing") >= 8.0
    assert _score_complexity("check status") >= 2.0
    print("  ✅ Complexity scoring")

    # Test repetition detection — no entries
    rep = detect_repetition([])
    assert rep["repetitive"] is False
    print("  ✅ Empty repetition detection")

    # Test repetition detection — with repeated entries
    repeated_entries = [
        {"type": "generate_task", "data": {"task": "reflect on current state and purpose"}, "source": "hypothalamus"}
        for _ in range(5)
    ]
    rep = detect_repetition(repeated_entries)
    assert rep["repetitive"] is True
    assert rep["count"] >= REPETITION_THRESHOLD
    print(f"  ✅ Repetition detected: '{rep['pattern']}' x{rep['count']}")

    # Test novelty scoring — diverse entries
    diverse_entries = [
        {"type": "ship_recorded", "source": "motoric", "data": {}},
        {"type": "mood_update", "source": "endocrine", "data": {}},
        {"type": "filter_cycle", "source": "nephron", "data": {}},
        {"type": "threat_resolved", "source": "amygdala", "data": {}},
        {"type": "learning_update", "source": "retina", "data": {}},
    ]
    novelty = compute_novelty_score(diverse_entries)
    assert novelty > 0.3, f"Expected > 0.3, got {novelty}"
    print(f"  ✅ Novelty score (diverse): {novelty}")

    # Test novelty scoring — uniform entries
    boring_entries = [{"type": "reflect", "source": "hypothalamus", "data": {}} for _ in range(10)]
    novelty_low = compute_novelty_score(boring_entries)
    assert novelty_low <= novelty, f"Uniform should score <= diverse: {novelty_low} vs {novelty}"
    print(f"  ✅ Novelty score (uniform): {novelty_low}")

    # Test challenge picker
    challenge = pick_challenge([])
    assert "domain" in challenge
    assert "label" in challenge
    assert "prompt" in challenge
    assert challenge["domain"] in [d["name"] for d in CHALLENGE_DOMAINS]
    print(f"  ✅ Challenge picked: {challenge['domain']} — {challenge['prompt'][:50]}...")

    # Test domain rotation (shouldn't repeat recent domains)
    recent = ["technical_build", "market_research"]
    challenge2 = pick_challenge(recent)
    # May or may not be different, but shouldn't crash
    assert challenge2["domain"] in [d["name"] for d in CHALLENGE_DOMAINS]
    print(f"  ✅ Domain rotation: {challenge2['domain']}")

    # Test full scan
    result = scan()
    assert "stagnant" in result
    assert "novelty_score" in result
    assert "repetition" in result
    assert 0.0 <= result["novelty_score"] <= 1.0
    print(f"  ✅ Full scan (stagnant={result['stagnant']}, novelty={result['novelty_score']})")

    # Test get_status
    status = get_status()
    assert "total_scans" in status
    assert status["total_scans"] >= 1
    assert "novelty_score" in status
    print(f"  ✅ Status: scans={status['total_scans']}, streak={status['stagnation_streak']}")

    # Test emit_need_signals (no hypothalamus — confirm no crash)
    result2 = emit_need_signals(hypothalamus_mod=None)
    assert "stagnation_streak" in result2
    assert "signals_emitted" in result2
    print(f"  ✅ emit_need_signals (no hm): streak={result2['stagnation_streak']}")

    print("\n  All RAPHE tests passed! ✅")


if __name__ == "__main__":
    _run_tests()
