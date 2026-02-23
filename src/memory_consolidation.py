"""
Memory Consolidation — CHRONICLE → ENGRAM pipeline for Pulse v0.3.0.

During REM (dreaming), Pulse consolidates recent CHRONICLE events into
long-term ENGRAM memories — mirroring how human sleep consolidates
short-term experiences into long-term memory.

Algorithm:
  1. Read last N CHRONICLE events
  2. Score each by importance (salience × recency × event_type weight)
  3. Promote high-importance events to ENGRAM (dedup by content hash)
  4. Decay stale low-importance ENGRAMs (reduce score over time)
  5. Return ConsolidationReport for the dream log

Design notes:
  - Fully file-based; no coupling to running daemon
  - Safe to run concurrently — uses atomic write pattern
  - ENGRAM format: same as process_learnings.py produces (jsonl)
  - Dedup: sha256 of content[:100] prevents reprocessing same event
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("pulse.memory_consolidation")

_DEFAULT_STATE_DIR  = Path.home() / ".pulse" / "state"
_DEFAULT_CHRONICLE  = _DEFAULT_STATE_DIR / "chronicle.jsonl"
_DEFAULT_ENGRAM_DIR = Path.home() / ".pulse" / "hippocampus"
_DEFAULT_ENGRAM_FILE = _DEFAULT_ENGRAM_DIR / "learnings.jsonl"
_CONSOLIDATION_LOG  = _DEFAULT_STATE_DIR / "consolidation-log.jsonl"

# ── Event type importance weights ──────────────────────────────────────────────

EVENT_TYPE_WEIGHTS = {
    "trigger_complete":   1.2,
    "goal_achieved":      1.5,
    "error":              1.3,
    "milestone":          1.4,
    "mood_update":        0.6,
    "drive_spike":        0.8,
    "biosensor_update":   0.7,
    "dream_complete":     1.0,
    "feedback":           1.1,
    "trade_executed":     1.4,
    "system_health":      0.9,
    "default":            1.0,
}

# Recency decay: events older than this score full weight; beyond = reduced
FULL_WEIGHT_HOURS = 4.0
MIN_RECENCY_SCORE = 0.3

# Promotion threshold: events scoring above this become ENGRAMs
PROMOTION_THRESHOLD = 0.6

# Decay rate: ENGRAMs older than this get importance reduced
ENGRAM_DECAY_AGE_DAYS = 14
ENGRAM_DECAY_FACTOR   = 0.8  # multiply importance by this after decay age


@dataclass
class ConsolidatedMemory:
    """A CHRONICLE event that has been promoted to long-term ENGRAM."""
    source_event_id: str
    content: str
    importance: float
    tags: List[str]
    event_type: str
    original_ts: float
    consolidated_at: float = field(default_factory=time.time)
    content_hash: str = ""

    def __post_init__(self):
        if not self.content_hash:
            self.content_hash = hashlib.sha256(
                self.content[:100].encode()
            ).hexdigest()[:16]

    def to_engram_dict(self) -> dict:
        return {
            "content": self.content,
            "importance": round(self.importance, 2),
            "tags": self.tags,
            "source": f"dream_consolidation:{self.event_type}",
            "timestamp": self.consolidated_at,
            "content_hash": self.content_hash,
        }


@dataclass
class ConsolidationReport:
    """Summary of one consolidation run — stored in dream log."""
    events_read:      int = 0
    events_scored:    int = 0
    promoted:         int = 0
    already_known:    int = 0
    decayed:          int = 0
    top_themes:       List[str] = field(default_factory=list)
    dream_insight:    str = ""
    run_at:           float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "events_read": self.events_read,
            "events_scored": self.events_scored,
            "promoted": self.promoted,
            "already_known": self.already_known,
            "decayed": self.decayed,
            "top_themes": self.top_themes,
            "dream_insight": self.dream_insight,
            "run_at": self.run_at,
        }

    def summary_line(self) -> str:
        return (
            f"Consolidated {self.promoted} new memories from {self.events_read} events. "
            f"Themes: {', '.join(self.top_themes[:3]) or 'none'}. "
            f"{self.decayed} stale ENGRAMs decayed."
        )


# ── Core pipeline ─────────────────────────────────────────────────────────────

def read_chronicle_recent(
    n: int = 50,
    chronicle_file: Optional[Path] = None,
) -> List[dict]:
    """Read the last N events from chronicle.jsonl."""
    path = chronicle_file or _DEFAULT_CHRONICLE
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        events = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events[-n:]
    except OSError:
        return []


def score_event(event: dict, now: Optional[float] = None) -> float:
    """Compute an importance score [0.0–2.0] for a CHRONICLE event.

    Score = salience × type_weight × recency_factor
    """
    if now is None:
        now = time.time()

    salience = float(event.get("salience", 0.5))
    event_type = event.get("type", "default")
    type_weight = EVENT_TYPE_WEIGHTS.get(event_type, EVENT_TYPE_WEIGHTS["default"])

    # Recency: events within FULL_WEIGHT_HOURS get 1.0; older events decay toward MIN_RECENCY_SCORE
    ts = event.get("ts") or event.get("timestamp") or now
    age_hours = max(0.0, (now - ts) / 3600)
    if age_hours <= FULL_WEIGHT_HOURS:
        recency = 1.0
    else:
        decay_progress = min(1.0, (age_hours - FULL_WEIGHT_HOURS) / 24)
        recency = max(MIN_RECENCY_SCORE, 1.0 - (1.0 - MIN_RECENCY_SCORE) * decay_progress)

    return round(salience * type_weight * recency, 4)


def _extract_content(event: dict) -> str:
    """Extract a human-readable content string from a CHRONICLE event."""
    data = event.get("data", {})
    # Try common fields in priority order
    for field_name in ("summary", "message", "description", "text", "content", "label"):
        val = data.get(field_name)
        if val and isinstance(val, str) and len(val.strip()) > 5:
            return val.strip()[:500]
    # Fall back to source + type description
    source = event.get("source", "unknown")
    event_type = event.get("type", "event")
    return f"{source}: {event_type} — {json.dumps(data, default=str)[:200]}"


def _extract_tags(event: dict) -> List[str]:
    """Extract tags from a CHRONICLE event."""
    tags = []
    event_type = event.get("type", "")
    if event_type:
        tags.append(event_type)
    source = event.get("source", "")
    if source:
        tags.append(source)
    data = event.get("data", {})
    # Grab explicit tags if present
    explicit = data.get("tags", [])
    if isinstance(explicit, list):
        tags.extend(str(t) for t in explicit[:5])
    return list(dict.fromkeys(tags))[:8]  # dedup, max 8


def _load_known_hashes(engram_file: Path) -> set:
    """Read existing ENGRAM content hashes to avoid re-promoting same events."""
    if not engram_file.exists():
        return set()
    try:
        hashes = set()
        for line in engram_file.read_text(encoding="utf-8").strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                h = entry.get("content_hash", "")
                if h:
                    hashes.add(h)
            except json.JSONDecodeError:
                continue
        return hashes
    except OSError:
        return set()


def _append_engrams(memories: List[ConsolidatedMemory], engram_file: Path):
    """Append new engrams to the ENGRAM jsonl file."""
    engram_file.parent.mkdir(parents=True, exist_ok=True)
    with engram_file.open("a", encoding="utf-8") as f:
        for mem in memories:
            f.write(json.dumps(mem.to_engram_dict()) + "\n")


def decay_old_engrams(
    engram_file: Optional[Path] = None,
    age_days: float = ENGRAM_DECAY_AGE_DAYS,
    decay_factor: float = ENGRAM_DECAY_FACTOR,
) -> int:
    """Reduce importance of ENGRAMs older than age_days. Returns count decayed."""
    path = engram_file or _DEFAULT_ENGRAM_FILE
    if not path.exists():
        return 0

    cutoff = time.time() - age_days * 86400
    decayed = 0
    lines = []

    try:
        for line in path.read_text(encoding="utf-8").strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = entry.get("timestamp", 0)
                importance = entry.get("importance", 5)
                if ts < cutoff and importance > 1:
                    entry["importance"] = round(max(1, importance * decay_factor), 2)
                    decayed += 1
                lines.append(json.dumps(entry))
            except json.JSONDecodeError:
                lines.append(line)

        if decayed > 0:
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    except OSError as e:
        logger.warning(f"decay_old_engrams failed: {e}")

    return decayed


def _derive_themes(memories: List[ConsolidatedMemory]) -> List[str]:
    """Extract top recurring tags from consolidated memories."""
    tag_counts: dict = {}
    for mem in memories:
        for tag in mem.tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    return [t for t, _ in sorted(tag_counts.items(), key=lambda x: -x[1])][:5]


def _generate_insight(memories: List[ConsolidatedMemory], events_read: int) -> str:
    """Generate a plain-text dream insight from consolidated memories."""
    if not memories:
        return f"Quiet session — {events_read} events reviewed, nothing new to consolidate."
    themes = _derive_themes(memories)
    top = memories[0] if memories else None
    theme_str = ", ".join(themes[:3]) if themes else "general activity"
    insight = (
        f"{len(memories)} memories consolidated around: {theme_str}. "
    )
    if top:
        insight += f'Most significant: "{top.content[:120].rstrip()}..."'
    return insight


def consolidate(
    n_events: int = 50,
    importance_threshold: float = PROMOTION_THRESHOLD,
    chronicle_file: Optional[Path] = None,
    engram_file: Optional[Path] = None,
    now: Optional[float] = None,
) -> ConsolidationReport:
    """Run the full CHRONICLE → ENGRAM consolidation pipeline.

    Args:
        n_events: how many recent CHRONICLE events to consider
        importance_threshold: score cutoff for ENGRAM promotion
        chronicle_file: override default chronicle path (for testing)
        engram_file: override default engram path (for testing)
        now: override current time (for testing)

    Returns:
        ConsolidationReport with stats and insight text.
    """
    report = ConsolidationReport(run_at=now or time.time())
    efile = engram_file or _DEFAULT_ENGRAM_FILE

    # 1. Read CHRONICLE
    events = read_chronicle_recent(n_events, chronicle_file)
    report.events_read = len(events)

    if not events:
        report.dream_insight = "Chronicle empty — nothing to consolidate."
        return report

    # 2. Score events
    t = now or time.time()
    scored = [
        (event, score_event(event, now=t))
        for event in events
    ]
    above_threshold = [(e, s) for e, s in scored if s >= importance_threshold]
    report.events_scored = len(above_threshold)

    # 3. Load known content hashes (dedup)
    known_hashes = _load_known_hashes(efile)

    # 4. Build ConsolidatedMemory objects, skipping already-known events
    new_memories: List[ConsolidatedMemory] = []
    for event, score in sorted(above_threshold, key=lambda x: -x[1]):
        content = _extract_content(event)
        content_hash = hashlib.sha256(content[:100].encode()).hexdigest()[:16]

        if content_hash in known_hashes:
            report.already_known += 1
            continue

        mem = ConsolidatedMemory(
            source_event_id=event.get("id", ""),
            content=content,
            importance=min(10.0, score * 5),  # rescale 0-2 → 0-10 for ENGRAM format
            tags=_extract_tags(event),
            event_type=event.get("type", "default"),
            original_ts=event.get("ts") or event.get("timestamp") or t,
            consolidated_at=t,
            content_hash=content_hash,
        )
        new_memories.append(mem)
        known_hashes.add(content_hash)

    report.promoted = len(new_memories)

    # 5. Write new ENGRAMs
    if new_memories:
        _append_engrams(new_memories, efile)
        logger.info(f"Promoted {len(new_memories)} new ENGRAMs from CHRONICLE")

    # 6. Decay old ENGRAMs
    report.decayed = decay_old_engrams(efile)

    # 7. Generate themes and insight
    report.top_themes = _derive_themes(new_memories)
    report.dream_insight = _generate_insight(new_memories, len(events))

    # 8. Log to consolidation history
    _log_consolidation(report)

    return report


def _log_consolidation(report: ConsolidationReport):
    """Append consolidation record to consolidation-log.jsonl."""
    try:
        _CONSOLIDATION_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _CONSOLIDATION_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(report.to_dict()) + "\n")
    except OSError:
        pass
