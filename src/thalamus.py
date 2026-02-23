"""Broadcast Layer — Central nervous system bus for Pulse.

Append-only JSONL stream. Every module writes state here, every module reads from here.
"""

import fcntl
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_BROADCAST_FILE = _DEFAULT_STATE_DIR / "broadcast.jsonl"
MAX_ENTRIES = 1000
KEEP_ENTRIES = 500


def _ensure_dir():
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)


def append(entry: dict) -> dict:
    """Append an entry to the broadcast stream. Adds timestamp if missing.
    
    Entry format: {"ts": epoch_ms, "source": str, "type": str, "salience": 0.0-1.0, "data": {}}
    """
    _ensure_dir()
    if "ts" not in entry:
        entry["ts"] = int(time.time() * 1000)
    
    line = json.dumps(entry, separators=(",", ":")) + "\n"
    
    with open(_DEFAULT_BROADCAST_FILE, "a") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(line)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    
    # Check rotation
    _maybe_rotate()
    return entry


def _read_all() -> list[dict]:
    """Read all entries from broadcast file."""
    if not _DEFAULT_BROADCAST_FILE.exists():
        return []
    entries = []
    with open(_DEFAULT_BROADCAST_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def read_recent(n: int = 10) -> list[dict]:
    """Return last N entries."""
    entries = _read_all()
    return entries[-n:]


def read_since(epoch_ms: int) -> list[dict]:
    """Return all entries since given timestamp."""
    return [e for e in _read_all() if e.get("ts", 0) >= epoch_ms]


def read_by_source(source: str, n: int = 10) -> list[dict]:
    """Return last N entries from a specific source."""
    filtered = [e for e in _read_all() if e.get("source") == source]
    return filtered[-n:]


def read_by_type(entry_type: str, n: int = 10) -> list[dict]:
    """Return last N entries of a specific type."""
    filtered = [e for e in _read_all() if e.get("type") == entry_type]
    return filtered[-n:]


def _count_lines() -> int:
    """Count lines in broadcast file."""
    if not _DEFAULT_BROADCAST_FILE.exists():
        return 0
    with open(_DEFAULT_BROADCAST_FILE, "r") as f:
        return sum(1 for line in f if line.strip())


def _maybe_rotate():
    """If file exceeds MAX_ENTRIES, archive old and keep last KEEP_ENTRIES."""
    count = _count_lines()
    if count <= MAX_ENTRIES:
        return
    
    entries = _read_all()
    archive_entries = entries[:-KEEP_ENTRIES]
    keep_entries = entries[-KEEP_ENTRIES:]
    
    # Archive
    date_str = datetime.now().strftime("%Y-%m-%d")
    archive_path = _DEFAULT_STATE_DIR / f"broadcast-archive-{date_str}.jsonl"
    with open(archive_path, "a") as f:
        for e in archive_entries:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")
    
    # Rewrite main file
    with open(_DEFAULT_BROADCAST_FILE, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            for e in keep_entries:
                f.write(json.dumps(e, separators=(",", ":")) + "\n")
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
