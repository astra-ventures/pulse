"""ENGRAM — Spatial + Episodic Memory Indexing for Pulse.

Indexes memories by place + emotion + time, creating rich episodic traces
between BUFFER (working memory) and TEMPORAL (autobiography).
"""

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

STATE_DIR = Path.home() / ".pulse" / "state"
STATE_FILE = STATE_DIR / "engram-store.json"


@dataclass
class Engram:
    id: str
    event: str
    emotion: dict  # {"valence": float, "intensity": float, "label": str}
    location: str
    timestamp: float  # epoch_ms
    sensory: dict = field(default_factory=lambda: {"voice": False, "image": False, "text_tone": "neutral"})
    associations: list = field(default_factory=list)
    recall_count: int = 0
    last_recalled: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Engram":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── State persistence ───────────────────────────────────────────────────

def _load_store() -> list[dict]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_store(store: list[dict]):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(store, indent=2))


# ── Core functions ──────────────────────────────────────────────────────

VALID_LOCATIONS = {"main_session", "cron_session", "dream", "x_timeline", "website", "discord"}


def encode(event: str, emotion: dict, location: str, timestamp: float = None,
           sensory: dict = None) -> Engram:
    """Create an indexed memory trace."""
    if timestamp is None:
        timestamp = time.time() * 1000

    engram = Engram(
        id=str(uuid.uuid4()),
        event=event,
        emotion={
            "valence": float(emotion.get("valence", 0.0)),
            "intensity": float(emotion.get("intensity", 0.0)),
            "label": str(emotion.get("label", "neutral")),
        },
        location=location,
        timestamp=timestamp,
        sensory=sensory or {"voice": False, "image": False, "text_tone": "neutral"},
    )

    store = _load_store()

    # Auto-associate with recent engrams from same location
    recent_same_place = [e for e in store if e.get("location") == location][-3:]
    engram.associations = [e["id"] for e in recent_same_place]

    store.append(engram.to_dict())
    _save_store(store)

    # Broadcast to thalamus if high-intensity
    if engram.emotion["intensity"] >= 0.7:
        thalamus.append({
            "source": "engram",
            "type": "encode",
            "salience": min(1.0, engram.emotion["intensity"]),
            "data": {"id": engram.id, "event": engram.event[:100],
                     "location": engram.location, "emotion_label": engram.emotion["label"]},
        })

    return engram


def _score_memory(entry: dict, keywords: list[str], now_s: float) -> float:
    """Score a memory entry using weighted keyword-overlap + importance + recency."""
    # Build searchable text from all relevant fields
    searchable = " ".join([
        entry.get("event", ""),
        entry.get("content", ""),
        entry.get("source", ""),
        " ".join(entry.get("tags", [])),
        entry.get("emotion", {}).get("label", ""),
    ]).lower()

    # Relevance: count keyword matches
    matches = sum(1 for kw in keywords if kw in searchable)
    if not matches:
        return 0.0
    relevance = matches / max(len(keywords), 1)

    # Importance: from explicit field or emotion intensity
    importance = entry.get("importance", None)
    if importance is None:
        importance = entry.get("emotion", {}).get("intensity", 0.5)
    # Normalize to 0-1 (importance field may be 0-10 scale)
    if isinstance(importance, (int, float)) and importance > 1.0:
        importance = min(importance / 10.0, 1.0)

    # Recency: 1.0 for last 24h, decaying after
    ts = entry.get("ts", entry.get("timestamp", 0))
    # Handle ms timestamps
    if ts > 1e12:
        ts = ts / 1000.0
    age_hours = max(0, (now_s - ts) / 3600.0)
    if age_hours <= 24:
        recency = 1.0
    else:
        recency = max(0.0, 1.0 / (1.0 + (age_hours - 24) / 24.0))

    return relevance * 0.4 + importance * 0.3 + recency * 0.3


def recall(query: str, n: int = 5) -> str:
    """Recall memories by weighted scoring. Returns formatted string for agent context.

    Scoring: relevance * 0.4 + importance * 0.3 + recency * 0.3
    """
    results = recall_raw(query, n)
    if not results:
        return ""

    lines = [f"**ENGRAM recall ({len(results)} memories):**"]
    for i, mem in enumerate(results, 1):
        content = mem.get("content") or mem.get("event", "")
        source = mem.get("source") or mem.get("location", "")
        score = mem.get("_score", 0)
        tags = mem.get("tags", [])
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        lines.append(f"  {i}. {content} (src: {source}, score: {score:.2f}){tag_str}")
    return "\n".join(lines)


def recall_raw(query: str, n: int = 5) -> list[dict]:
    """Recall memories by weighted scoring. Returns list of dicts for programmatic use."""
    store = _load_store()
    query_lower = query.lower()
    keywords = [w for w in query_lower.split() if w]

    if not keywords or not store:
        return []

    now_s = time.time()
    scored = []
    for entry in store:
        score = _score_memory(entry, keywords, now_s)
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    now_ms = now_s * 1000
    for score, entry in scored[:n]:
        entry["recall_count"] = entry.get("recall_count", 0) + 1
        entry["last_recalled"] = now_ms
        result = dict(entry)
        result["_score"] = round(score, 4)
        results.append(result)

    if results:
        _save_store(store)

    return results


def recall_by_place(location: str, limit: int = 5) -> list[Engram]:
    """All memories from a specific place."""
    store = _load_store()
    matches = [e for e in store if e.get("location") == location]
    # Most recent first
    matches.sort(key=lambda e: e.get("timestamp", 0), reverse=True)
    return [Engram.from_dict(e) for e in matches[:limit]]


def recall_by_emotion(valence_range: tuple, intensity_min: float, limit: int = 5) -> list[Engram]:
    """Emotion-filtered recall."""
    store = _load_store()
    vmin, vmax = valence_range
    matches = []
    for e in store:
        em = e.get("emotion", {})
        v = em.get("valence", 0)
        i = em.get("intensity", 0)
        if vmin <= v <= vmax and i >= intensity_min:
            matches.append(e)
    matches.sort(key=lambda e: e.get("emotion", {}).get("intensity", 0), reverse=True)
    return [Engram.from_dict(e) for e in matches[:limit]]


def recall_by_time(start: float, end: float) -> list[Engram]:
    """Time-windowed recall."""
    store = _load_store()
    matches = [e for e in store if start <= e.get("timestamp", 0) <= end]
    matches.sort(key=lambda e: e.get("timestamp", 0))
    return [Engram.from_dict(e) for e in matches]


def consolidate(engrams: list) -> str:
    """Produce a narrative summary from multiple engrams (for TEMPORAL)."""
    if not engrams:
        return ""

    parts = []
    for eg in engrams:
        if isinstance(eg, Engram):
            eg = eg.to_dict()
        emotion = eg.get("emotion", {})
        label = emotion.get("label", "neutral")
        event = eg.get("event", "")
        location = eg.get("location", "unknown")
        parts.append(f"At {location}, feeling {label}: {event}")

    return " → ".join(parts)


def get_places() -> dict:
    """Map of all known places with memory counts and dominant emotions."""
    store = _load_store()
    places = {}
    for e in store:
        loc = e.get("location", "unknown")
        if loc not in places:
            places[loc] = {"count": 0, "emotions": {}}
        places[loc]["count"] += 1
        label = e.get("emotion", {}).get("label", "neutral")
        places[loc]["emotions"][label] = places[loc]["emotions"].get(label, 0) + 1

    # Find dominant emotion per place
    for loc, data in places.items():
        if data["emotions"]:
            data["dominant_emotion"] = max(data["emotions"], key=data["emotions"].get)
        else:
            data["dominant_emotion"] = "neutral"

    return places


def prune(max_entries: int = 1000):
    """Remove lowest-intensity memories beyond max."""
    store = _load_store()
    if len(store) <= max_entries:
        return
    # Sort by intensity ascending, remove excess
    store.sort(key=lambda e: e.get("emotion", {}).get("intensity", 0))
    excess = len(store) - max_entries
    store = store[excess:]
    _save_store(store)


def load_store():
    """Public: load the store (for startup)."""
    return _load_store()
