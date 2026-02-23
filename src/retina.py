"""RETINA — Input Preprocessing / Attention Filter for Pulse.

Scores incoming signals by importance BEFORE they reach CORTEX.
Most data gets filtered before conscious awareness.
"""

import json
import os
import re
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Optional

from pulse.src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "retina-state.json"
_DEFAULT_LEARNING_FILE = _DEFAULT_STATE_DIR / "retina-learning.json"

OWNER_PHONE = os.environ.get("PULSE_OWNER_PHONE", "+15555550100")
DEFAULT_THRESHOLD = 0.3
HIGH_LOAD_THRESHOLD = 0.6
FOCUS_THRESHOLD = 0.8
ATTENTION_LOG_MAX = 50


class ScoredSignal:
    """A signal scored by RETINA."""

    def __init__(self, signal: dict, priority: float, category: str,
                 should_process: bool, reasoning: str):
        self.signal = signal
        self.priority = priority
        self.category = category
        self.should_process = should_process
        self.reasoning = reasoning

    def to_dict(self) -> dict:
        return {
            "signal": self.signal,
            "priority": self.priority,
            "category": self.category,
            "should_process": self.should_process,
            "reasoning": self.reasoning,
        }


# --- Built-in matchers ---

def _match_owner_direct(signal: dict) -> bool:
    sender = signal.get("sender") or signal.get("from") or ""
    return OWNER_PHONE in str(sender)


def _match_owner_mention(signal: dict) -> bool:
    text = str(signal.get("text", "") or signal.get("content", "")).lower()
    return "owner" in text and not _match_owner_direct(signal)


def _match_high_value_alert(signal: dict) -> bool:
    edge = signal.get("edge_pct") or signal.get("edge", 0)
    likes = signal.get("likes", 0)
    try:
        return float(edge) > 10 or int(likes) > 50
    except (ValueError, TypeError):
        return False


def _match_cron_anomaly(signal: dict) -> bool:
    return (signal.get("source_type") == "cron"
            and signal.get("anomaly", False) is True)


def _match_cron_routine(signal: dict) -> bool:
    return (signal.get("source_type") == "cron"
            and not signal.get("anomaly", False))


def _match_heartbeat_quiet(signal: dict) -> bool:
    return signal.get("source_type") == "heartbeat" and not signal.get("has_action", False)


def _match_system_health(signal: dict) -> bool:
    level = signal.get("health_level") or signal.get("alert_level", "")
    return level in ("yellow", "orange", "red")


def _match_notable_mention(signal: dict) -> bool:
    return (signal.get("source_type") == "mention"
            and int(signal.get("follower_count", 0)) > 10000)


def _match_routine_mention(signal: dict) -> bool:
    return (signal.get("source_type") == "mention"
            and int(signal.get("follower_count", 0)) <= 10000)


def _match_web_content(signal: dict) -> bool:
    return signal.get("source_type") == "web_content"


# Default rules: (name, matcher, priority) — order matters (first match wins)
_DEFAULT_RULES = [
    ("owner_direct", _match_owner_direct, 1.0),
    ("owner_mention", _match_owner_mention, 0.9),
    ("high_value_alert", _match_high_value_alert, 0.85),
    ("system_health", _match_system_health, 0.8),
    ("notable_mention", _match_notable_mention, 0.75),
    ("cron_anomaly", _match_cron_anomaly, 0.7),
    ("routine_mention", _match_routine_mention, 0.3),
    ("web_content", _match_web_content, 0.2),
    ("cron_routine_success", _match_cron_routine, 0.1),
    ("heartbeat_quiet", _match_heartbeat_quiet, 0.05),
]


class Retina:
    """Attention filter — scores and queues signals by importance."""

    def __init__(self):
        self._rules: list[tuple[str, Callable, float]] = list(_DEFAULT_RULES)
        self._queue: list[ScoredSignal] = []
        self._attention_log: deque[dict] = deque(maxlen=ATTENTION_LOG_MAX)
        self._threshold = DEFAULT_THRESHOLD
        self._focus_mode = False  # True when in conversation with Josh
        self._spine_level = "green"
        self._buffer_topic: Optional[str] = None
        self._signals_processed = 0
        self._signals_filtered = 0
        self._learning: dict = {}  # category → {correct: int, wrong: int, adjustment: float}
        self._load_state()
        self._load_learning()

    # --- Public API ---

    def score(self, signal: dict) -> ScoredSignal:
        """Score a single signal and add to queue if above threshold."""
        priority = 0.0
        category = "unknown"
        reasoning = "no matching rule"

        for name, matcher, rule_priority in self._rules:
            try:
                if matcher(signal):
                    priority = rule_priority
                    category = name
                    reasoning = f"matched rule: {name}"
                    break
            except Exception:
                continue

        # Apply learning adjustment
        if category in self._learning:
            adj = self._learning[category].get("adjustment", 0.0)
            if adj != 0:
                priority = max(0.0, min(1.0, priority + adj))
                reasoning += f" (learning adj: {adj:+.2f})"

        # Topic boost from BUFFER
        if self._buffer_topic and priority > 0:
            text = str(signal.get("text", "") or signal.get("content", "")).lower()
            if self._buffer_topic.lower() in text:
                priority = min(1.0, priority + 0.2)
                reasoning += f" (+0.2 topic boost: {self._buffer_topic})"

        threshold = self._effective_threshold(signal)
        should_process = priority >= threshold

        scored = ScoredSignal(signal, priority, category, should_process, reasoning)

        # Log
        self._attention_log.append({
            "ts": int(time.time() * 1000),
            "priority": priority,
            "category": category,
            "should_process": should_process,
        })

        if should_process:
            self._queue.append(scored)
            self._queue.sort(key=lambda s: s.priority, reverse=True)
            self._signals_processed += 1
        else:
            self._signals_filtered += 1

        # Broadcast to thalamus
        thalamus.append({
            "source": "retina",
            "type": "attention",
            "salience": priority,
            "data": {
                "category": category,
                "priority": priority,
                "should_process": should_process,
                "reasoning": reasoning,
            },
        })

        self._save_state()
        return scored

    def register_priority_rule(self, name: str, matcher: Callable, priority: float):
        """Add a custom priority rule. Inserted before default rules of same/lower priority."""
        # Remove existing rule with same name
        self._rules = [(n, m, p) for n, m, p in self._rules if n != name]
        # Insert in priority order
        inserted = False
        for i, (_, _, p) in enumerate(self._rules):
            if priority > p:
                self._rules.insert(i, (name, matcher, priority))
                inserted = True
                break
        if not inserted:
            self._rules.append((name, matcher, priority))
        self._save_state()

    def get_attention_queue(self, limit: int = 10) -> list[ScoredSignal]:
        """Return queued signals sorted by priority."""
        return self._queue[:limit]

    def filter_batch(self, signals: list[dict]) -> list[ScoredSignal]:
        """Score and filter a batch, returning only those above threshold."""
        results = []
        for sig in signals:
            scored = self.score(sig)
            if scored.should_process:
                results.append(scored)
        return results

    def clear_queue(self):
        """Clear the attention queue."""
        self._queue.clear()

    def set_spine_level(self, level: str):
        """Update system health level from SPINE."""
        self._spine_level = level
        self._save_state()

    def set_focus_mode(self, active: bool):
        """Enable/disable focus mode (conversation with Josh)."""
        self._focus_mode = active
        self._save_state()

    def set_buffer_topic(self, topic: Optional[str]):
        """Set current topic from BUFFER for relevance boosting."""
        self._buffer_topic = topic

    def record_outcome(self, category: str, was_correct: bool):
        """Record whether a priority decision was correct. Adjusts rules over time."""
        if category not in self._learning:
            self._learning[category] = {"correct": 0, "wrong": 0, "adjustment": 0.0}
        entry = self._learning[category]
        if was_correct:
            entry["correct"] += 1
        else:
            entry["wrong"] += 1
        # Adjust: if >60% wrong over 10+ samples, nudge priority
        total = entry["correct"] + entry["wrong"]
        if total >= 10:
            wrong_rate = entry["wrong"] / total
            if wrong_rate > 0.6:
                entry["adjustment"] = -0.1  # lower priority
            elif wrong_rate < 0.2:
                entry["adjustment"] = 0.05  # slight boost
            else:
                entry["adjustment"] = 0.0
        self._save_learning()

    def get_learning(self) -> dict:
        """Return current learning state."""
        return dict(self._learning)

    def _load_learning(self):
        try:
            if _DEFAULT_LEARNING_FILE.exists():
                self._learning = json.loads(_DEFAULT_LEARNING_FILE.read_text())
        except Exception:
            self._learning = {}

    def _save_learning(self):
        _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
        _DEFAULT_LEARNING_FILE.write_text(json.dumps(self._learning, indent=2))

    @property
    def threshold(self) -> float:
        return self._effective_threshold({})

    # --- Internal ---

    def _effective_threshold(self, signal: dict) -> float:
        """Calculate effective threshold based on system state."""
        if self._focus_mode:
            # In focus mode, only Josh signals pass easily
            if _match_owner_direct(signal):
                return DEFAULT_THRESHOLD
            return FOCUS_THRESHOLD
        if self._spine_level in ("orange", "red"):
            return HIGH_LOAD_THRESHOLD
        return self._threshold

    def _load_state(self):
        try:
            if _DEFAULT_STATE_FILE.exists():
                data = json.loads(_DEFAULT_STATE_FILE.read_text())
                self._threshold = data.get("current_threshold", DEFAULT_THRESHOLD)
                self._signals_processed = data.get("signals_processed_today", 0)
                self._signals_filtered = data.get("signals_filtered_today", 0)
                self._spine_level = data.get("spine_level", "green")
                self._focus_mode = data.get("focus_mode", False)
        except Exception:
            pass

    def _save_state(self):
        _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "current_threshold": self._threshold,
            "signals_processed_today": self._signals_processed,
            "signals_filtered_today": self._signals_filtered,
            "priority_rules_active": [name for name, _, _ in self._rules],
            "spine_level": self._spine_level,
            "focus_mode": self._focus_mode,
            "attention_log": list(self._attention_log),
        }
        _DEFAULT_STATE_FILE.write_text(json.dumps(data, indent=2))


# Module-level singleton
_instance: Optional[Retina] = None


def get_instance() -> Retina:
    global _instance
    if _instance is None:
        _instance = Retina()
    return _instance


def score(signal: dict) -> ScoredSignal:
    return get_instance().score(signal)


def register_priority_rule(name: str, matcher: Callable, priority: float):
    get_instance().register_priority_rule(name, matcher, priority)


def get_attention_queue(limit: int = 10) -> list[ScoredSignal]:
    return get_instance().get_attention_queue(limit)


def filter_batch(signals: list[dict]) -> list[ScoredSignal]:
    return get_instance().filter_batch(signals)
