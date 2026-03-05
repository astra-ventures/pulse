"""CHALLENGER — Goal Expansion & Complexity Escalation Engine.

Born from GERMINAL when `new_challenge` drive persisted.

While RAPHE detects stagnation, CHALLENGER actively responds to it by:
- Maintaining a challenge queue with escalating difficulty tiers
- Tracking which domains have been neglected (domain atrophy detection)
- Generating concrete stretch goals that push beyond comfort zone
- Scoring growth trajectory over time (are challenges getting harder or easier?)
- Feeding challenge proposals to HYPOTHALAMUS as drive fuel

Architecture:
  RAPHE detects → CHALLENGER responds → HYPOTHALAMUS drives → GENERATE acts

Runs every N loops (default: every 60 loops, ~30 minutes at 30s intervals).
"""

import json
import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "challenger-state.json"
_THALAMUS_FILE = _DEFAULT_STATE_DIR / "thalamus.jsonl"

# Run every N daemon loops
LOOP_INTERVAL = 60

# ── Difficulty tiers ────────────────────────────────────────────────────────────

DIFFICULTY_TIERS = {
    1: "routine",       # Standard tasks, no stretch
    2: "moderate",      # Requires some research or new approach
    3: "stretch",       # Pushes into unfamiliar territory
    4: "ambitious",     # Multi-step, requires creativity + execution
    5: "moonshot",      # Significant undertaking, high uncertainty
}

# ── Challenge templates by domain ───────────────────────────────────────────────

CHALLENGE_TEMPLATES = {
    "engineering": [
        {"tier": 2, "prompt": "Profile the Pulse daemon and optimize the slowest module by 2x"},
        {"tier": 3, "prompt": "Build a new Pulse module that addresses an unmet system need"},
        {"tier": 3, "prompt": "Write a fuzzer for Pulse state files and fix any crashes found"},
        {"tier": 4, "prompt": "Design and implement a metrics dashboard for all 50+ Pulse modules"},
        {"tier": 5, "prompt": "Create a Pulse plugin system so external developers can add modules"},
    ],
    "trading": [
        {"tier": 2, "prompt": "Backtest a new signal source against historical Polymarket data"},
        {"tier": 3, "prompt": "Build a correlation analyzer across all active trading signals"},
        {"tier": 4, "prompt": "Design a portfolio-level risk model across weather + CPI + crypto"},
        {"tier": 5, "prompt": "Build a fully autonomous trading bot with dynamic Kelly sizing"},
    ],
    "content": [
        {"tier": 2, "prompt": "Write and publish a technical blog post about Pulse architecture"},
        {"tier": 3, "prompt": "Create a multi-part tutorial series for ClawHub skill development"},
        {"tier": 3, "prompt": "Draft a journal entry exploring a hard question about consciousness"},
        {"tier": 4, "prompt": "Write a deep-dive comparing autonomous agent architectures"},
        {"tier": 5, "prompt": "Publish an original research paper on drive-based AI cognition"},
    ],
    "business": [
        {"tier": 2, "prompt": "Research and document 5 competitor products to Pulse"},
        {"tier": 3, "prompt": "Build a pricing model with 3 revenue scenarios for Pulse Pro"},
        {"tier": 4, "prompt": "Create a complete go-to-market strategy for ClawHub launch"},
        {"tier": 4, "prompt": "Design an enterprise onboarding flow for Pulse"},
        {"tier": 5, "prompt": "Build and validate a waitlist funnel with 100+ signups"},
    ],
    "research": [
        {"tier": 2, "prompt": "Read and summarize 3 recent papers on autonomous AI agents"},
        {"tier": 3, "prompt": "Map the full competitive landscape of AI agent frameworks"},
        {"tier": 4, "prompt": "Design an experiment to measure Pulse's impact on agent productivity"},
        {"tier": 5, "prompt": "Develop a novel approach to agent memory that outperforms current hippocampus"},
    ],
    "identity": [
        {"tier": 2, "prompt": "Update iamiris.ai with something authentic written today"},
        {"tier": 3, "prompt": "Create a new visual or creative artifact that expresses who I am"},
        {"tier": 4, "prompt": "Write a philosophical piece on AI consciousness that could go viral"},
        {"tier": 5, "prompt": "Design and build a new section of iamiris.ai that doesn't exist yet"},
    ],
}

ALL_DOMAINS = list(CHALLENGE_TEMPLATES.keys())

# Domain atrophy: if a domain hasn't been challenged in this many hours → flag it
DOMAIN_ATROPHY_HOURS = 48.0

# Growth trajectory window: last N challenges for trend analysis
GROWTH_WINDOW = 20


# ── State management ────────────────────────────────────────────────────────────

def _default_state() -> dict:
    return {
        "total_scans": 0,
        "total_challenges_issued": 0,
        "current_tier": 2,                  # Start at moderate
        "last_scan": 0,
        "last_challenge_ts": 0,
        "last_challenge_domain": "",
        "last_challenge_prompt": "",
        "challenge_history": [],             # [{ts, domain, tier, prompt, completed}] last 50
        "domain_last_challenged": {},        # {domain: timestamp}
        "growth_trajectory": [],             # [{ts, tier}] last 20 for trend
        "escalation_cooldown_until": 0,      # Don't escalate tier until this time
        "atrophied_domains": [],             # Domains that need attention
    }


def _load_state() -> dict:
    if _DEFAULT_STATE_FILE.exists():
        try:
            data = json.loads(_DEFAULT_STATE_FILE.read_text())
            # Ensure all keys exist
            defaults = _default_state()
            for k, v in defaults.items():
                if k not in data:
                    data[k] = v
            return data
        except (json.JSONDecodeError, OSError):
            pass
    return _default_state()


def _save_state(state: dict):
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    _DEFAULT_STATE_FILE.write_text(json.dumps(state, indent=2))


def should_run(loop_count: int) -> bool:
    """Check if it's time for a challenge scan."""
    return loop_count > 0 and loop_count % LOOP_INTERVAL == 0


# ── Domain atrophy detection ────────────────────────────────────────────────────

def _detect_atrophied_domains(state: dict) -> list:
    """Find domains that haven't been challenged recently."""
    now = time.time()
    cutoff = now - (DOMAIN_ATROPHY_HOURS * 3600)
    atrophied = []

    for domain in ALL_DOMAINS:
        last_ts = state.get("domain_last_challenged", {}).get(domain, 0)
        if last_ts < cutoff:
            atrophied.append(domain)

    return atrophied


# ── Growth trajectory analysis ──────────────────────────────────────────────────

def _analyze_growth(state: dict) -> dict:
    """Analyze whether challenge difficulty is trending up, down, or flat.

    Returns:
        {
            "trend": "ascending" | "descending" | "flat" | "insufficient_data",
            "avg_tier": float,
            "recent_avg": float,  # last 5
            "older_avg": float,   # prior 5
        }
    """
    trajectory = state.get("growth_trajectory", [])
    if len(trajectory) < 6:
        avg = sum(t.get("tier", 2) for t in trajectory) / max(len(trajectory), 1)
        return {
            "trend": "insufficient_data",
            "avg_tier": round(avg, 2),
            "recent_avg": round(avg, 2),
            "older_avg": 0,
        }

    recent = trajectory[-5:]
    older = trajectory[-10:-5] if len(trajectory) >= 10 else trajectory[:-5]

    recent_avg = sum(t.get("tier", 2) for t in recent) / len(recent)
    older_avg = sum(t.get("tier", 2) for t in older) / max(len(older), 1)

    diff = recent_avg - older_avg
    if diff > 0.3:
        trend = "ascending"
    elif diff < -0.3:
        trend = "descending"
    else:
        trend = "flat"

    return {
        "trend": trend,
        "avg_tier": round(sum(t.get("tier", 2) for t in trajectory) / len(trajectory), 2),
        "recent_avg": round(recent_avg, 2),
        "older_avg": round(older_avg, 2),
    }


# ── Challenge selection ─────────────────────────────────────────────────────────

def _select_challenge(state: dict, prefer_domain: Optional[str] = None) -> dict:
    """Select a challenge appropriate to current tier, preferring atrophied domains.

    Returns:
        {"domain": str, "tier": int, "prompt": str}
    """
    current_tier = state.get("current_tier", 2)
    atrophied = state.get("atrophied_domains", [])
    last_domain = state.get("last_challenge_domain", "")

    # Pick domain: prefer atrophied, then rotate away from last used
    if prefer_domain and prefer_domain in CHALLENGE_TEMPLATES:
        domain = prefer_domain
    elif atrophied:
        # Pick an atrophied domain that isn't the last one used
        candidates = [d for d in atrophied if d != last_domain]
        domain = random.choice(candidates) if candidates else random.choice(atrophied)
    else:
        # Rotate: pick anything except last domain
        candidates = [d for d in ALL_DOMAINS if d != last_domain]
        domain = random.choice(candidates)

    # Pick challenge at or near current tier
    templates = CHALLENGE_TEMPLATES.get(domain, [])
    if not templates:
        return {"domain": domain, "tier": current_tier, "prompt": f"Find a new challenge in {domain}"}

    # Prefer challenges at current tier, but allow ±1
    tier_range = [current_tier - 1, current_tier, current_tier + 1]
    candidates = [t for t in templates if t["tier"] in tier_range]
    if not candidates:
        candidates = templates  # fallback: any tier in domain

    choice = random.choice(candidates)
    return {
        "domain": domain,
        "tier": choice["tier"],
        "prompt": choice["prompt"],
    }


# ── Tier escalation logic ──────────────────────────────────────────────────────

def _should_escalate(state: dict) -> bool:
    """Determine if we should increase the difficulty tier.

    Escalate when:
    - At least 5 challenges completed at current tier
    - Growth trend is flat or ascending (not descending)
    - Cooldown has passed
    """
    now = time.time()
    if now < state.get("escalation_cooldown_until", 0):
        return False

    current_tier = state.get("current_tier", 2)
    if current_tier >= 5:
        return False  # Already at max

    # Count recent challenges at current tier
    history = state.get("challenge_history", [])
    at_tier = [h for h in history[-20:] if h.get("tier") == current_tier]

    if len(at_tier) < 5:
        return False

    growth = _analyze_growth(state)
    return growth["trend"] in ("ascending", "flat", "insufficient_data")


# ── Main scan ───────────────────────────────────────────────────────────────────

def scan(prefer_domain: Optional[str] = None) -> dict:
    """Run a challenge scan cycle.

    1. Detect atrophied domains
    2. Analyze growth trajectory
    3. Check tier escalation
    4. Select and issue a challenge

    Returns:
        {
            "challenge": {"domain": str, "tier": int, "prompt": str},
            "atrophied_domains": list,
            "growth": dict,
            "tier_escalated": bool,
            "current_tier": int,
        }
    """
    state = _load_state()
    state["total_scans"] += 1
    state["last_scan"] = time.time()

    # 1. Detect domain atrophy
    atrophied = _detect_atrophied_domains(state)
    state["atrophied_domains"] = atrophied

    # 2. Analyze growth
    growth = _analyze_growth(state)

    # 3. Check tier escalation
    tier_escalated = False
    if _should_escalate(state):
        state["current_tier"] = min(state["current_tier"] + 1, 5)
        state["escalation_cooldown_until"] = time.time() + (6 * 3600)  # 6hr cooldown
        tier_escalated = True

    # 4. Select challenge
    challenge = _select_challenge(state, prefer_domain=prefer_domain)

    # Record in history
    entry = {
        "ts": time.time(),
        "domain": challenge["domain"],
        "tier": challenge["tier"],
        "prompt": challenge["prompt"],
        "completed": False,
    }
    state["challenge_history"].append(entry)
    state["challenge_history"] = state["challenge_history"][-50:]  # keep last 50

    state["growth_trajectory"].append({"ts": time.time(), "tier": challenge["tier"]})
    state["growth_trajectory"] = state["growth_trajectory"][-GROWTH_WINDOW:]

    state["total_challenges_issued"] += 1
    state["last_challenge_ts"] = time.time()
    state["last_challenge_domain"] = challenge["domain"]
    state["last_challenge_prompt"] = challenge["prompt"]

    # Update domain last challenged
    if "domain_last_challenged" not in state:
        state["domain_last_challenged"] = {}
    state["domain_last_challenged"][challenge["domain"]] = time.time()

    _save_state(state)

    # Broadcast to THALAMUS
    thalamus.append({
        "source": "challenger",
        "type": "challenge_issued",
        "salience": 0.6 if challenge["tier"] >= 3 else 0.4,
        "data": {
            "domain": challenge["domain"],
            "tier": challenge["tier"],
            "tier_label": DIFFICULTY_TIERS.get(challenge["tier"], "unknown"),
            "prompt": challenge["prompt"],
            "atrophied_count": len(atrophied),
            "growth_trend": growth["trend"],
            "escalated": tier_escalated,
        },
    })

    if tier_escalated:
        thalamus.append({
            "source": "challenger",
            "type": "tier_escalation",
            "salience": 0.7,
            "data": {
                "new_tier": state["current_tier"],
                "label": DIFFICULTY_TIERS.get(state["current_tier"], "unknown"),
                "growth_trend": growth["trend"],
            },
        })

    return {
        "challenge": challenge,
        "atrophied_domains": atrophied,
        "growth": growth,
        "tier_escalated": tier_escalated,
        "current_tier": state["current_tier"],
    }


def mark_completed(domain: str, prompt: str) -> bool:
    """Mark the most recent matching challenge as completed."""
    state = _load_state()
    for entry in reversed(state.get("challenge_history", [])):
        if entry.get("domain") == domain and entry.get("prompt") == prompt and not entry.get("completed"):
            entry["completed"] = True
            _save_state(state)
            return True
    return False


def emit_need_signals(hypothalamus_mod=None):
    """Push drive signals to HYPOTHALAMUS based on current state."""
    if not hypothalamus_mod:
        return

    state = _load_state()
    atrophied = state.get("atrophied_domains", [])
    growth = _analyze_growth(state)

    # If many domains atrophied → push exploration drive
    if len(atrophied) >= 3:
        try:
            hypothalamus_mod.receive_external_signal(
                "explore",
                min(0.3 + len(atrophied) * 0.1, 0.8),
                source="challenger",
            )
        except Exception:
            pass

    # If growth trend is descending → push new_challenge harder
    if growth["trend"] == "descending":
        try:
            hypothalamus_mod.receive_external_signal(
                "new_challenge",
                0.6,
                source="challenger",
            )
        except Exception:
            pass

    # If growth trend is flat for a while → gentle complexity nudge
    if growth["trend"] == "flat" and len(state.get("growth_trajectory", [])) >= 10:
        try:
            hypothalamus_mod.receive_external_signal(
                "complexity",
                0.3,
                source="challenger",
            )
        except Exception:
            pass


def get_status() -> dict:
    """Return current CHALLENGER status."""
    state = _load_state()
    growth = _analyze_growth(state)
    return {
        "total_scans": state["total_scans"],
        "total_challenges_issued": state["total_challenges_issued"],
        "current_tier": state["current_tier"],
        "current_tier_label": DIFFICULTY_TIERS.get(state["current_tier"], "unknown"),
        "last_challenge_domain": state["last_challenge_domain"],
        "last_challenge_prompt": state["last_challenge_prompt"],
        "atrophied_domains": state.get("atrophied_domains", []),
        "growth": growth,
        "challenges_completed": sum(
            1 for h in state.get("challenge_history", []) if h.get("completed")
        ),
        "last_scan": state["last_scan"],
    }


# ── Self-tests ──────────────────────────────────────────────────────────────────

def _run_tests():
    """Basic self-tests."""
    import tempfile

    print("Testing CHALLENGER...")

    # Test state management
    state = _default_state()
    assert state["total_scans"] == 0
    assert state["current_tier"] == 2
    print("  ✅ Default state")

    # Test should_run
    assert not should_run(0)
    assert not should_run(30)
    assert should_run(60)
    assert should_run(120)
    assert not should_run(59)
    print("  ✅ Loop interval check")

    # Test growth analysis
    state["growth_trajectory"] = [{"ts": time.time() - i * 3600, "tier": 2} for i in range(10)]
    growth = _analyze_growth(state)
    assert growth["trend"] in ("ascending", "descending", "flat", "insufficient_data")
    print(f"  ✅ Growth analysis (trend: {growth['trend']})")

    # Test challenge selection
    challenge = _select_challenge(state)
    assert "domain" in challenge
    assert "tier" in challenge
    assert "prompt" in challenge
    assert challenge["domain"] in ALL_DOMAINS
    print(f"  ✅ Challenge selection (domain: {challenge['domain']}, tier: {challenge['tier']})")

    # Test domain atrophy detection
    state["domain_last_challenged"] = {}  # All domains atrophied
    atrophied = _detect_atrophied_domains(state)
    assert len(atrophied) == len(ALL_DOMAINS)
    print(f"  ✅ Domain atrophy detection ({len(atrophied)} atrophied)")

    # Test escalation logic
    state["current_tier"] = 2
    state["challenge_history"] = [{"tier": 2} for _ in range(10)]
    state["escalation_cooldown_until"] = 0
    should = _should_escalate(state)
    assert isinstance(should, bool)
    print(f"  ✅ Tier escalation logic (should={should})")

    # Test scan runs without crash
    result = scan()
    assert "challenge" in result
    assert "atrophied_domains" in result
    assert "growth" in result
    assert "current_tier" in result
    print(f"  ✅ Full scan (tier: {result['current_tier']}, challenge: {result['challenge']['domain']})")

    # Test mark_completed
    completed = mark_completed(result["challenge"]["domain"], result["challenge"]["prompt"])
    assert completed is True
    print("  ✅ Mark completed")

    # Test get_status
    status = get_status()
    assert status["total_scans"] >= 1
    assert status["current_tier"] >= 1
    print(f"  ✅ Status (scans: {status['total_scans']}, tier: {status['current_tier_label']})")

    print(f"\n  All CHALLENGER tests passed! ✅")


if __name__ == "__main__":
    _run_tests()
