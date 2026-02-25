"""ECHO — Reward Signal from Primary (Josh Sentiment Feedback Loop).

Josh's direct feedback (praise, criticism, corrections) shapes Iris's hormone
baseline and drive weights over time. This is the primary reward signal.

Valence: -1.0 (harsh criticism) to +1.0 (strong praise).
"""

import json
import time
from pathlib import Path
from typing import Optional

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "echo-state.json"


def _default_state() -> dict:
    return {
        "events": [],
        "baseline": 0.5,
        "trend": "stable",
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


def record_feedback(
    valence: float,
    intensity: float,
    text: str,
    source: str = "josh",
    endocrine_mod=None,
) -> dict:
    """Log a feedback event with timestamp. Optionally fire endocrine events.

    Args:
        valence: -1.0 (harsh) to +1.0 (praise)
        intensity: 0.0–1.0 strength of the signal
        text: matched or quoted text that triggered the feedback detection
        source: who gave the feedback (default: "josh")
        endocrine_mod: optional endocrine module to fire hormone events

    Returns:
        The feedback event dict.
    """
    state = _load_state()
    now = time.time()

    event = {
        "ts": now,
        "valence": valence,
        "intensity": intensity,
        "text": text[:200],  # truncate long text
        "source": source,
    }

    state["events"].append(event)
    # Keep last 500 events
    state["events"] = state["events"][-500:]

    # Recompute trend + baseline from recent events
    recent = [e for e in state["events"] if now - e["ts"] < 86400]  # last 24h
    if recent:
        avg = sum(e["valence"] for e in recent) / len(recent)
        state["baseline"] = round(avg, 3)
        if avg > 0.2:
            state["trend"] = "improving"
        elif avg < -0.2:
            state["trend"] = "declining"
        else:
            state["trend"] = "stable"

    _save_state(state)

    # Fire hormone events based on valence
    if endocrine_mod is not None:
        try:
            if valence > 0.7:
                endocrine_mod.apply_event("josh_affirming")
                endocrine_mod.apply_event("good_conversation_josh")
            elif valence < -0.3:
                endocrine_mod.update_hormone("cortisol", 0.2, "josh_critical")
        except Exception:
            pass  # degrade gracefully if endocrine not available

    return event


def get_feedback_trend(hours: int = 24) -> dict:
    """Return average valence and trend direction over the last N hours.

    Returns:
        {
            "avg_valence": float,       # average over window
            "trend": "improving" | "declining" | "stable",
            "event_count": int,
            "hours": int,
        }
    """
    state = _load_state()
    now = time.time()
    cutoff = now - hours * 3600

    recent = [e for e in state["events"] if e["ts"] >= cutoff]

    if not recent:
        return {
            "avg_valence": state["baseline"],
            "trend": state["trend"],
            "event_count": 0,
            "hours": hours,
        }

    avg = sum(e["valence"] for e in recent) / len(recent)

    # Trend from first half vs second half
    mid = len(recent) // 2
    if mid > 0:
        first_half = sum(e["valence"] for e in recent[:mid]) / mid
        second_half = sum(e["valence"] for e in recent[mid:]) / (len(recent) - mid)
        diff = second_half - first_half
        if diff > 0.1:
            trend = "improving"
        elif diff < -0.1:
            trend = "declining"
        else:
            trend = "stable"
    else:
        trend = state["trend"]

    return {
        "avg_valence": round(avg, 3),
        "trend": trend,
        "event_count": len(recent),
        "hours": hours,
    }


def get_reinforcement_signal() -> float:
    """Return a -1.0 to 1.0 reinforcement signal based on recent feedback.

    Combines the 24h baseline with short-term trend direction.
    Positive = keep doing this; Negative = adjust behavior.
    """
    state = _load_state()
    now = time.time()

    # Weight recent events more heavily
    recent_1h = [e for e in state["events"] if now - e["ts"] < 3600]
    recent_6h = [e for e in state["events"] if now - e["ts"] < 21600]

    if recent_1h:
        short_term = sum(e["valence"] for e in recent_1h) / len(recent_1h)
    elif recent_6h:
        short_term = sum(e["valence"] for e in recent_6h) / len(recent_6h)
    else:
        short_term = state["baseline"]

    # Normalize baseline (0.0–1.0) to (-1.0 to 1.0)
    baseline_signal = (state["baseline"] - 0.5) * 2.0

    # Blend: 70% short-term, 30% baseline
    signal = 0.7 * short_term + 0.3 * baseline_signal
    return round(max(-1.0, min(1.0, signal)), 3)


def get_status() -> dict:
    """Return feedback system status."""
    state = _load_state()
    now = time.time()
    recent_24h = [e for e in state["events"] if now - e["ts"] < 86400]
    recent_1h = [e for e in state["events"] if now - e["ts"] < 3600]

    return {
        "total_events": len(state["events"]),
        "events_24h": len(recent_24h),
        "events_1h": len(recent_1h),
        "baseline": state["baseline"],
        "trend": state["trend"],
        "reinforcement_signal": get_reinforcement_signal(),
    }
