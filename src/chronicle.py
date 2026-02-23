"""CHRONICLE — Automated Historian for Pulse.

Watches THALAMUS for significant events. Timeline in chronicle.jsonl.
Significance filtering. Queryable by date.
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_CHRONICLE_FILE = _DEFAULT_STATE_DIR / "chronicle.jsonl"

SIGNIFICANCE_THRESHOLD = 0.5  # only record events with salience >= this


def _ensure_dir():
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)


def record_event(source: str, event_type: str, data: dict, salience: float = 0.5) -> Optional[dict]:
    """Record a significant event to the chronicle."""
    if salience < SIGNIFICANCE_THRESHOLD:
        return None
    
    _ensure_dir()
    entry = {
        "ts": time.time(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M:%S"),
        "source": source,
        "type": event_type,
        "salience": salience,
        "data": data,
    }
    
    with open(_DEFAULT_CHRONICLE_FILE, "a") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")
    
    return entry


def capture_from_thalamus(n: int = 20) -> int:
    """Read recent THALAMUS entries and record significant ones. Returns count recorded."""
    try:
        entries = thalamus.read_recent(n)
    except Exception:
        return 0
    
    recorded = 0
    for entry in entries:
        salience = entry.get("salience", 0)
        if salience >= SIGNIFICANCE_THRESHOLD:
            result = record_event(
                source=entry.get("source", "unknown"),
                event_type=entry.get("type", "unknown"),
                data=entry.get("data", {}),
                salience=salience,
            )
            if result:
                recorded += 1
    return recorded


def query_by_date(date_str: str) -> list:
    """Query chronicle entries by date (YYYY-MM-DD)."""
    if not _DEFAULT_CHRONICLE_FILE.exists():
        return []
    
    results = []
    with open(_DEFAULT_CHRONICLE_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("date") == date_str:
                    results.append(entry)
            except json.JSONDecodeError:
                continue
    return results


def query_recent(n: int = 20) -> list:
    """Return the last N chronicle entries."""
    if not _DEFAULT_CHRONICLE_FILE.exists():
        return []
    
    entries = []
    with open(_DEFAULT_CHRONICLE_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries[-n:]


def get_status() -> dict:
    """Return chronicle status."""
    if not _DEFAULT_CHRONICLE_FILE.exists():
        return {"total_entries": 0}
    
    count = 0
    with open(_DEFAULT_CHRONICLE_FILE, "r") as f:
        count = sum(1 for line in f if line.strip())
    return {"total_entries": count}
