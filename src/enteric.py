"""ENTERIC — Gut Feeling / Intuition for Pulse.

The second brain. Fast pattern matching below conscious awareness.
Produces simple toward/away/neutral signals.
"""

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

STATE_DIR = Path.home() / ".pulse" / "state"
STATE_FILE = STATE_DIR / "enteric-state.json"
MAX_PATTERNS = 200


@dataclass
class Intuition:
    direction: str    # toward, away, neutral
    confidence: float # 0.0-1.0
    whisper: str      # brief text of the feeling


@dataclass
class Pattern:
    context_keys: list      # key features of the context
    outcome: str            # positive, negative, neutral
    direction: str          # toward, away, neutral
    confidence: float       # how reliable this pattern has been
    ts: int = 0

    def __post_init__(self):
        if not self.ts:
            self.ts = int(time.time() * 1000)


# ── State persistence ───────────────────────────────────────────────────

def _load_state() -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "pattern_library": [],
        "accuracy_stats": {"toward": {"correct": 0, "total": 0},
                           "away": {"correct": 0, "total": 0},
                           "neutral": {"correct": 0, "total": 0}},
        "override_log": [],
        "training_history": [],
    }


def _save_state(state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    # Prune patterns
    if len(state["pattern_library"]) > MAX_PATTERNS:
        state["pattern_library"] = state["pattern_library"][-MAX_PATTERNS:]
    if len(state["override_log"]) > 100:
        state["override_log"] = state["override_log"][-100:]
    if len(state["training_history"]) > 200:
        state["training_history"] = state["training_history"][-200:]
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _context_keys(context: dict) -> list[str]:
    """Extract key features from a context dict for pattern matching."""
    keys = []
    for k, v in context.items():
        if isinstance(v, str) and len(v) < 100:
            keys.append(f"{k}={v}")
        elif isinstance(v, (int, float, bool)):
            keys.append(f"{k}={v}")
        else:
            keys.append(k)
    return sorted(keys)


def _similarity(keys_a: list[str], keys_b: list[str]) -> float:
    """Simple Jaccard similarity between two key lists."""
    set_a, set_b = set(keys_a), set(keys_b)
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


# ── Mood bias (reads ENDOCRINE state if available) ──────────────────────

def _get_mood_bias() -> tuple[float, float]:
    """Returns (toward_bias, away_bias) from endocrine state.
    High cortisol → away bias. High dopamine → toward bias."""
    endocrine_file = STATE_DIR / "endocrine-state.json"
    if not endocrine_file.exists():
        return (0.0, 0.0)
    try:
        endo = json.loads(endocrine_file.read_text())
        hormones = endo.get("hormones", {})
        cortisol = hormones.get("cortisol", 0.5)
        dopamine = hormones.get("dopamine", 0.5)
        toward_bias = (dopamine - 0.5) * 0.3  # ±0.15 max
        away_bias = (cortisol - 0.5) * 0.3
        return (toward_bias, away_bias)
    except (json.JSONDecodeError, OSError):
        return (0.0, 0.0)


# ── Core functions ──────────────────────────────────────────────────────

def gut_check(context: dict) -> Intuition:
    """Fast pattern matching — returns toward/away/neutral with confidence."""
    state = _load_state()
    patterns = state["pattern_library"]
    ctx_keys = _context_keys(context)

    if not patterns:
        return Intuition(direction="neutral", confidence=0.1, whisper="no patterns yet — too early to tell")

    # Find top-3 most similar patterns
    scored = []
    for p in patterns:
        sim = _similarity(ctx_keys, p.get("context_keys", []))
        if sim > 0.1:
            scored.append((sim, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:3]

    if not top:
        return Intuition(direction="neutral", confidence=0.1, whisper="nothing similar in memory")

    # Weighted vote
    votes = {"toward": 0.0, "away": 0.0, "neutral": 0.0}
    total_weight = 0.0
    for sim, p in top:
        weight = sim * p.get("confidence", 0.5)
        votes[p.get("direction", "neutral")] += weight
        total_weight += weight

    # Apply mood bias
    toward_bias, away_bias = _get_mood_bias()
    votes["toward"] += toward_bias
    votes["away"] += away_bias

    # Pick winner
    direction = max(votes, key=votes.get)
    confidence = votes[direction] / max(total_weight + abs(toward_bias) + abs(away_bias), 0.01)
    confidence = min(1.0, max(0.0, confidence))

    # Generate whisper from best matching pattern
    best_sim, best_pattern = top[0]
    outcome = best_pattern.get("outcome", "unknown")
    whisper = f"this feels like something that went {outcome} before"

    result = Intuition(direction=direction, confidence=round(confidence, 2), whisper=whisper)

    # Broadcast strong intuitions
    if confidence > 0.7:
        thalamus.append({
            "source": "enteric",
            "type": "intuition",
            "salience": confidence,
            "data": {"direction": direction, "confidence": confidence, "whisper": whisper},
        })

    return result


def train(outcome: str, original_context: dict, gut_was: str):
    """After outcome is known, train the gut. outcome = positive/negative/neutral."""
    state = _load_state()
    ctx_keys = _context_keys(original_context)

    # Determine if gut was right
    outcome_direction_map = {"positive": "toward", "negative": "away", "neutral": "neutral"}
    correct_direction = outcome_direction_map.get(outcome, "neutral")
    was_correct = gut_was == correct_direction

    # Update accuracy
    if gut_was in state["accuracy_stats"]:
        state["accuracy_stats"][gut_was]["total"] += 1
        if was_correct:
            state["accuracy_stats"][gut_was]["correct"] += 1

    # Add new pattern
    new_pattern = {
        "context_keys": ctx_keys,
        "outcome": outcome,
        "direction": correct_direction,
        "confidence": 0.6 if was_correct else 0.3,
        "ts": int(time.time() * 1000),
    }
    state["pattern_library"].append(new_pattern)

    # Log training
    state["training_history"].append({
        "outcome": outcome,
        "gut_was": gut_was,
        "correct": was_correct,
        "ts": int(time.time() * 1000),
    })

    _save_state(state)


def log_override(context: dict, gut_direction: str, cortex_decision: str, outcome: Optional[str] = None):
    """Log when CORTEX overrides a gut feeling."""
    state = _load_state()
    state["override_log"].append({
        "context_keys": _context_keys(context),
        "gut_direction": gut_direction,
        "cortex_decision": cortex_decision,
        "outcome": outcome,
        "ts": int(time.time() * 1000),
    })
    _save_state(state)


def get_accuracy() -> dict:
    """How accurate has gut been?"""
    state = _load_state()
    stats = state.get("accuracy_stats", {})
    result = {}
    for direction, data in stats.items():
        total = data.get("total", 0)
        correct = data.get("correct", 0)
        result[direction] = {
            "total": total,
            "correct": correct,
            "accuracy": round(correct / max(total, 1), 2),
        }
    return result


def get_pattern_library() -> list:
    """Return current pattern library."""
    state = _load_state()
    return state.get("pattern_library", [])
