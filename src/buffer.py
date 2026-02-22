"""BUFFER — Working Memory for Pulse.

Prefrontal cortex equivalent. Captures conversation state before context
compaction so critical information survives window resets.
"""

import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pulse.src import thalamus

STATE_DIR = Path.home() / ".pulse" / "state"
BUFFER_FILE = STATE_DIR / "buffer.json"
ARCHIVE_DIR = STATE_DIR / "buffer-archive"


def _ensure_dirs():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def _empty_buffer() -> dict:
    return {
        "captured_at": 0,
        "session_id": "",
        "decisions": [],
        "action_items": [],
        "emotional_state": {"valence": 0.0, "intensity": 0.0, "context": ""},
        "open_threads": [],
        "key_context": "",
        "participants": [],
        "topic": "",
        "emotional_anchor": {"vibe": "", "energy": 0.5, "engagement": 0.5},
    }


def _load() -> dict:
    if BUFFER_FILE.exists():
        try:
            return json.loads(BUFFER_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return _empty_buffer()


def _save(buf: dict):
    _ensure_dirs()
    BUFFER_FILE.write_text(json.dumps(buf, indent=2))


def capture(
    conversation_summary: str,
    decisions: list,
    action_items: list,
    emotional_state: dict,
    open_threads: list,
    participants: Optional[list] = None,
    topic: Optional[str] = None,
    session_id: Optional[str] = None,
    emotional_anchor: Optional[dict] = None,
) -> dict:
    """Save current working memory state."""
    buf = _load()
    buf["captured_at"] = int(time.time() * 1000)
    buf["session_id"] = session_id or buf.get("session_id") or str(uuid.uuid4())[:8]
    buf["decisions"] = decisions
    buf["action_items"] = action_items
    buf["emotional_state"] = emotional_state
    buf["open_threads"] = open_threads
    buf["key_context"] = conversation_summary
    if participants is not None:
        buf["participants"] = participants
    if topic is not None:
        buf["topic"] = topic
    if emotional_anchor is not None:
        buf["emotional_anchor"] = emotional_anchor
    _save(buf)

    # Broadcast to THALAMUS
    thalamus.append({
        "source": "buffer",
        "type": "state",
        "salience": 0.6,
        "data": {
            "session_id": buf["session_id"],
            "topic": buf["topic"],
            "decisions_count": len(decisions),
            "action_items_count": len(action_items),
            "emotional_valence": emotional_state.get("valence", 0.0),
        },
    })
    return buf


def update_field(field: str, value: Any) -> dict:
    """Update a single field without full capture."""
    buf = _load()
    if field not in buf:
        raise KeyError(f"Unknown buffer field: {field}")
    buf[field] = value
    buf["captured_at"] = int(time.time() * 1000)
    _save(buf)
    return buf


def get_buffer() -> dict:
    """Returns current buffer contents."""
    return _load()


def get_compact_summary(max_tokens: int = 500) -> str:
    """Returns a compressed text summary for context injection.
    
    Approximates tokens as words (rough 1:1 for English).
    """
    buf = _load()
    if not buf.get("captured_at"):
        return ""

    parts = []
    if buf.get("topic"):
        parts.append(f"Topic: {buf['topic']}")
    if buf.get("key_context"):
        parts.append(f"Context: {buf['key_context']}")
    if buf.get("decisions"):
        parts.append("Decisions: " + "; ".join(buf["decisions"]))
    if buf.get("action_items"):
        parts.append("Action items: " + "; ".join(buf["action_items"]))
    if buf.get("open_threads"):
        parts.append("Open threads: " + "; ".join(buf["open_threads"]))
    es = buf.get("emotional_state", {})
    if es.get("context"):
        parts.append(f"Mood: {es['context']} (valence={es.get('valence', 0):.1f})")
    if buf.get("participants"):
        parts.append("Participants: " + ", ".join(buf["participants"]))
    anchor = buf.get("emotional_anchor", {})
    if anchor.get("vibe"):
        parts.append(f"Anchor: vibe={anchor['vibe']} energy={anchor.get('energy', 0.5):.1f} engagement={anchor.get('engagement', 0.5):.1f}")

    summary = "\n".join(parts)
    # Truncate to approximate token limit (avg ~4 chars/token)
    max_chars = max_tokens * 4
    if len(summary) > max_chars:
        summary = summary[:max_chars - 3] + "..."
    return summary


def rotate() -> Optional[str]:
    """Archive current buffer and start fresh. Returns archive path."""
    _ensure_dirs()
    buf = _load()
    if not buf.get("captured_at"):
        return None

    ts = datetime.now().strftime("%Y-%m-%d-%H")
    archive_path = ARCHIVE_DIR / f"{ts}.json"
    archive_path.write_text(json.dumps(buf, indent=2))

    _save(_empty_buffer())

    thalamus.append({
        "source": "buffer",
        "type": "rotate",
        "salience": 0.3,
        "data": {"archived_to": str(archive_path)},
    })
    return str(archive_path)


def auto_capture(messages: list) -> dict:
    """Given recent message dicts, automatically extract working memory.
    
    Each message should have at least: {"role": str, "content": str}
    Optionally: {"sender": str}
    """
    decisions = []
    action_items = []
    open_threads = []
    participants = set()
    topics = []
    valence = 0.0
    intensity = 0.0

    decision_markers = ["decided", "decision", "let's go with", "agreed", "we'll do", "going with", "chosen", "picked"]
    action_markers = ["todo", "to do", "will do", "need to", "should do", "action item", "next step", "let me", "i'll"]
    question_markers = ["?", "what about", "how do we", "should we", "thoughts on", "unresolved"]
    positive_markers = ["great", "awesome", "love", "excited", "happy", "perfect", "excellent", "nice"]
    negative_markers = ["frustrated", "annoyed", "worried", "concerned", "angry", "sad", "disappointed", "stuck"]

    for msg in messages:
        content = msg.get("content", "").lower()
        sender = msg.get("sender") or msg.get("role", "unknown")
        participants.add(sender)

        for marker in decision_markers:
            if marker in content:
                # Extract the sentence containing the marker
                for sentence in msg["content"].replace("\n", ". ").split(". "):
                    if marker in sentence.lower():
                        decisions.append(sentence.strip().rstrip("."))
                        break
                break

        for marker in action_markers:
            if marker in content:
                for sentence in msg["content"].replace("\n", ". ").split(". "):
                    if marker in sentence.lower():
                        action_items.append(sentence.strip().rstrip("."))
                        break
                break

        for marker in question_markers:
            if marker in content:
                for sentence in msg["content"].replace("\n", ". ").split(". "):
                    if marker in sentence.lower() or "?" in sentence:
                        open_threads.append(sentence.strip().rstrip("."))
                        break
                break

        # Sentiment
        pos = sum(1 for m in positive_markers if m in content)
        neg = sum(1 for m in negative_markers if m in content)
        valence += (pos - neg)
        intensity += (pos + neg)

    # Normalize
    n = max(len(messages), 1)
    valence = max(-1.0, min(1.0, valence / n))
    intensity = min(1.0, intensity / (n * 2))

    # Build summary
    all_content = " ".join(m.get("content", "")[:200] for m in messages[-5:])
    summary = all_content[:500] if all_content else ""

    # Deduplicate
    decisions = list(dict.fromkeys(decisions))[:10]
    action_items = list(dict.fromkeys(action_items))[:10]
    open_threads = list(dict.fromkeys(open_threads))[:10]

    emotion_context = "positive" if valence > 0.2 else "negative" if valence < -0.2 else "neutral"

    return capture(
        conversation_summary=summary,
        decisions=decisions,
        action_items=action_items,
        emotional_state={"valence": valence, "intensity": intensity, "context": emotion_context},
        open_threads=open_threads,
        participants=list(participants),
    )
