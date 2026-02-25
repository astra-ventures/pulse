"""Silence Detector — Treats meaningful absence as information.

Tracks activity timestamps per source and scores significance of silence
based on time-of-day, source type, and duration.
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "silence-state.json"

# Sources we track
SOURCES = ["josh", "markets", "agents", "crons"]


def _load_state() -> dict:
    if _DEFAULT_STATE_FILE.exists():
        try:
            return json.loads(_DEFAULT_STATE_FILE.read_text())
        except (json.JSONDecodeError, KeyError):
            pass
    return {"timestamps": {}, "broadcast_flags": {}}


def _save_state(state: dict):
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    _DEFAULT_STATE_FILE.write_text(json.dumps(state, indent=2))


def update_timestamp(source: str):
    """Record activity from a source."""
    state = _load_state()
    state.setdefault("timestamps", {})[source] = int(time.time() * 1000)
    # Reset broadcast flag so we can fire again next time
    state.setdefault("broadcast_flags", {})[source] = False
    _save_state(state)


def _is_sleep_hours(now: Optional[datetime] = None) -> bool:
    """Check if current time is sleep hours (11PM-8AM)."""
    if now is None:
        now = datetime.now()
    return now.hour >= 23 or now.hour < 8


def _josh_significance(elapsed_hours: float, now: Optional[datetime] = None) -> float:
    """Josh silence significance: 0 during sleep, linear 2h-8h during waking."""
    if _is_sleep_hours(now):
        return 0.0
    if elapsed_hours < 2:
        return 0.0
    # Linear from 0 at 2h to 1.0 at 8h
    return min((elapsed_hours - 2) / 6.0, 1.0)


def _market_significance(elapsed_hours: float) -> float:
    """Market silence on data release day = 0.8 immediately."""
    # Simplified: if markets silent > 1 hour, moderate concern
    if elapsed_hours < 1:
        return 0.0
    return 0.8


def _cron_significance(elapsed_hours: float) -> float:
    """No cron output for >2 hours = system health concern."""
    if elapsed_hours < 2:
        return 0.0
    return 0.5


def _agent_significance(elapsed_hours: float) -> float:
    """Agent silence scoring."""
    if elapsed_hours < 1:
        return 0.0
    return min(elapsed_hours / 8.0, 0.7)


SIGNIFICANCE_FNS = {
    "josh": _josh_significance,
    "markets": _market_significance,
    "crons": _cron_significance,
    "agents": _agent_significance,
}


def check_silence(now: Optional[datetime] = None) -> list[dict]:
    """Check all sources for meaningful silence. Returns list of active silences."""
    state = _load_state()
    timestamps = state.get("timestamps", {})
    broadcast_flags = state.get("broadcast_flags", {})
    now_ms = int(time.time() * 1000)
    if now is None:
        now = datetime.now()
    
    silences = []
    changed = False
    
    for source in SOURCES:
        last_ts = timestamps.get(source)
        if last_ts is None:
            continue
        
        elapsed_ms = now_ms - last_ts
        elapsed_hours = elapsed_ms / 3_600_000
        
        fn = SIGNIFICANCE_FNS.get(source)
        if fn is None:
            continue
        
        # Josh needs time-of-day awareness
        if source == "josh":
            significance = fn(elapsed_hours, now)
        else:
            significance = fn(elapsed_hours)
        
        if significance <= 0:
            continue
        
        silence_entry = {
            "source": source,
            "duration_hours": round(elapsed_hours, 2),
            "duration_ms": elapsed_ms,
            "significance": round(significance, 3),
        }
        silences.append(silence_entry)
        
        # Broadcast when crossing 0.5 threshold (once per silence period)
        if significance >= 0.5 and not broadcast_flags.get(source, False):
            broadcast_flags[source] = True
            changed = True
            thalamus.append({
                "source": "vagus",
                "type": "silence",
                "salience": significance,
                "data": {
                    "silent_source": source,
                    "duration_hours": round(elapsed_hours, 2),
                    "significance": round(significance, 3),
                }
            })
    
    if changed:
        state["broadcast_flags"] = broadcast_flags
        _save_state(state)
    
    return silences


def emit_need_signals() -> dict:
    """Check silence durations and emit HYPOTHALAMUS need signals."""
    try:
        state = _load_state()
    except Exception:
        return {}

    timestamps = state.get("timestamps", {})
    signals = {}

    # Primary contact (Josh) silent > 48 hours → connection need
    josh_ts = timestamps.get("josh")
    if josh_ts is not None:
        now_ms = int(time.time() * 1000)
        elapsed_seconds = (now_ms - josh_ts) / 1000
        if elapsed_seconds > 172800:  # 48 hours
            from pulse.src import hypothalamus
            hypothalamus.record_need_signal("connection", "vagus")
            signals["connection"] = elapsed_seconds

    return signals


def get_pressure_delta() -> dict:
    """Optional hook: generate drive pressure from silence."""
    silences = check_silence()
    pressure = {}
    for s in silences:
        if s["source"] == "josh" and s["significance"] > 0.3:
            pressure["connection"] = s["significance"] * 0.5
        if s["source"] == "crons" and s["significance"] > 0:
            pressure["vigilance"] = s["significance"] * 0.3
    return pressure
