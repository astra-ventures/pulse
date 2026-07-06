"""
CHRONICLE — Automated Historian
==================================
Ported from v1 pulse.src.chronicle into v2 HypostasRuntime.

Records significant events to a timeline. Filters by salience.
Queryable by date.

All state persisted via StateEngine under ``chronicle.*`` dot-paths.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from .state_engine import StateEngine
    from .context_engine import ContextEngine

SIGNIFICANCE_THRESHOLD = 0.5


class Chronicle:
    """Automated historian — records significant events."""

    _KEY = "chronicle"

    def __init__(self, state: "StateEngine", context: "ContextEngine") -> None:
        self._state = state
        self._context = context
        if self._state.get(f"{self._KEY}.entries") is None:
            self._state.set(f"{self._KEY}.entries", [])
            self._state.set(f"{self._KEY}.total_entries", 0)
            self._state.set(f"{self._KEY}.last_capture_ts", 0)

    def record_event(
        self,
        source: str,
        event_type: str,
        data: dict,
        salience: float = 0.5,
    ) -> Optional[dict]:
        """Record a significant event to the chronicle."""
        if salience < SIGNIFICANCE_THRESHOLD:
            return None

        entry = {
            "ts": time.time(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": datetime.now().strftime("%H:%M:%S"),
            "source": source,
            "type": event_type,
            "salience": round(salience, 2),
            "data": data,
        }

        entries = list(self._state.get(f"{self._KEY}.entries") or [])
        entries.append(entry)
        # Keep last 500 entries
        self._state.set(f"{self._KEY}.entries", entries[-500:])
        total = int(self._state.get(f"{self._KEY}.total_entries") or 0) + 1
        self._state.set(f"{self._KEY}.total_entries", total)
        self._state.set(f"{self._KEY}.last_capture_ts", entry["ts"])
        return entry

    # Salience defaults by event type — hot tier doesn't always include salience
    _TYPE_SALIENCE = {
        "MESSAGE_RECEIVED": 0.7,
        "MESSAGE_SENT": 0.5,
        "THOUGHT_LOOP": 0.6,
        "EMOTIONAL_SHIFT": 0.8,
        "DRIVE_PEAK": 0.7,
        "GOAL_PROGRESS": 0.9,
        "RELATIONSHIP_UPDATE": 0.6,
        "INSIGHT": 0.7,
        "SYSTEM_EVENT": 0.3,
        "PULSE_TRIGGER": 0.4,
    }

    def capture_from_context(self, n: int = 20) -> int:
        """Read recent context events and record significant ones."""
        recorded = 0
        try:
            recent = self._context.get_recent_context(hours=1)
            for event in (recent or [])[-n:]:
                event_type = event.get("type", "unknown")
                salience = float(event.get("salience", self._TYPE_SALIENCE.get(event_type, 0.3)))
                if salience >= SIGNIFICANCE_THRESHOLD:
                    result = self.record_event(
                        source=event.get("source", event_type),
                        event_type=event_type,
                        data=event.get("content", {}),
                        salience=salience,
                    )
                    if result:
                        recorded += 1
        except Exception:
            pass
        return recorded

    def query_by_date(self, date_str: str) -> List[dict]:
        """Query chronicle entries by date (YYYY-MM-DD)."""
        entries = list(self._state.get(f"{self._KEY}.entries") or [])
        return [e for e in entries if e.get("date") == date_str]

    def query_recent(self, n: int = 20) -> List[dict]:
        """Return the last N chronicle entries."""
        entries = list(self._state.get(f"{self._KEY}.entries") or [])
        return entries[-n:]

    def tick(self) -> None:
        """Periodic capture from context."""
        self.capture_from_context()

    def status(self) -> dict:
        entries = list(self._state.get(f"{self._KEY}.entries") or [])
        return {
            "total_entries": int(self._state.get(f"{self._KEY}.total_entries") or 0),
            "recent_count": len(entries),
            "last_capture_ts": self._state.get(f"{self._KEY}.last_capture_ts"),
        }
