"""VESPER — Nightly Synthesis Module for Pulse.

Overnight consolidation: synthesize the day, reset fatigue, process what mattered.
Runs during deep_night circadian mode at 300-loop intervals (≈2.5h at 30s/loop).

This is the difference between shutting down and actually resting.
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "vesper-state.json"

_WORKSPACE_ROOT = Path.home() / ".openclaw" / "workspace"
_DAILY_SYNTH_DIR = _WORKSPACE_ROOT / "memory" / "self" / "daily-synthesis"

# Minimum hours between restoration runs
_MIN_INTERVAL_HOURS = 6.0


def _default_state() -> dict:
    return {
        "last_run": 0,
        "run_count": 0,
        "last_synthesis_file": None,
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


def should_run(circadian_mode: str, loop_count: int) -> bool:
    """Return True if restoration should run now.

    Conditions:
    - circadian_mode is "deep_night"
    - loop_count % 300 == 0
    - last_run was > 6 hours ago
    """
    if circadian_mode != "deep_night":
        return False
    if loop_count % 300 != 0:
        return False

    state = _load_state()
    now = time.time()
    hours_since = (now - state.get("last_run", 0)) / 3600.0
    return hours_since > _MIN_INTERVAL_HOURS


def run_restoration(
    chronicle_mod=None,
    engram_mod=None,
    endocrine_mod=None,
    memory_dir: Optional[Path] = None,
) -> dict:
    """Run overnight synthesis and restoration.

    Steps:
    1. Read today's chronicle entries
    2. Read today's memory file (last 2KB)
    3. Synthesize: count shipped events, emotional peaks, conversations
    4. Write synthesis to daily-synthesis/YYYY-MM-DD.json
    5. Apply endocrine overnight decay
    6. Fire rem_success if >3 meaningful events found

    Returns:
        Summary dict with synthesis results.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    state = _load_state()
    now = time.time()

    result = {
        "date": today,
        "shipped_count": 0,
        "peak_emotion": "neutral",
        "key_events": [],
        "conversation_count": 0,
        "meaningful_event_count": 0,
        "endocrine_decayed": False,
        "rem_success_fired": False,
        "synthesis_file": None,
    }

    # 1. Read chronicle entries for today
    chronicle_entries = []
    if chronicle_mod is not None:
        try:
            chronicle_entries = chronicle_mod.query_by_date(today)
        except Exception:
            pass

    # 2. Read today's memory file (last 2KB)
    if memory_dir is None:
        memory_dir = _WORKSPACE_ROOT / "memory"

    memory_text = ""
    memory_file = memory_dir / f"{today}.md"
    if memory_file.exists():
        try:
            size = memory_file.stat().st_size
            with memory_file.open("rb") as fh:
                fh.seek(max(0, size - 2048))
                memory_text = fh.read(2048).decode("utf-8", errors="ignore")
        except OSError:
            pass

    # 3. Synthesize
    shipped_keywords = ["shipped", "deployed", "launched", "published", "committed", "pushed", "completed"]
    conversation_keywords = ["conversation", "josh", "signal", "telegram", "message"]
    emotion_keywords = {
        "excited": 1.0, "joy": 0.9, "accomplished": 0.8,
        "content": 0.6, "neutral": 0.0,
        "anxious": -0.4, "stressed": -0.6, "overwhelmed": -0.8,
    }

    shipped_count = 0
    conversation_count = 0
    key_events = []
    emotion_scores = []

    # Process chronicle entries
    for entry in chronicle_entries:
        etype = entry.get("type", "")
        data = entry.get("data", {})
        summary = data.get("summary", "")
        reason = data.get("reason", "")
        text = f"{etype} {summary} {reason}".lower()

        # Detect shipped events
        if any(kw in text for kw in shipped_keywords):
            shipped_count += 1
            key_events.append({
                "type": "shipped",
                "summary": summary or reason or etype,
                "time": entry.get("time", ""),
            })

        # Detect conversations
        if any(kw in text for kw in conversation_keywords):
            conversation_count += 1

        # Detect emotion peaks
        for emotion, score in emotion_keywords.items():
            if emotion in text:
                emotion_scores.append(score)

    # Also scan memory text
    text_lower = memory_text.lower()
    for kw in shipped_keywords:
        shipped_count += text_lower.count(kw)
    for emotion, score in emotion_keywords.items():
        if emotion in text_lower:
            emotion_scores.append(score)

    # Determine peak emotion
    if emotion_scores:
        max_score = max(emotion_scores)
        min_score = min(emotion_scores)
        # Pick the most extreme emotion
        if abs(max_score) >= abs(min_score):
            peak_score = max_score
        else:
            peak_score = min_score

        if peak_score >= 0.8:
            peak_emotion = "excited"
        elif peak_score >= 0.5:
            peak_emotion = "accomplished"
        elif peak_score >= 0.2:
            peak_emotion = "content"
        elif peak_score >= -0.3:
            peak_emotion = "neutral"
        elif peak_score >= -0.6:
            peak_emotion = "anxious"
        else:
            peak_emotion = "overwhelmed"
    else:
        peak_emotion = "neutral"

    meaningful_event_count = shipped_count + conversation_count

    result.update({
        "shipped_count": shipped_count,
        "peak_emotion": peak_emotion,
        "key_events": key_events[:10],  # cap at 10
        "conversation_count": conversation_count,
        "meaningful_event_count": meaningful_event_count,
    })

    # 4. Write synthesis file
    synthesis_text = (
        f"Day {today}: {shipped_count} shipped events, "
        f"{conversation_count} conversations, peak emotion: {peak_emotion}. "
        f"Chronicle entries: {len(chronicle_entries)}."
    )
    if key_events:
        synthesis_text += " Key: " + "; ".join(
            e.get("summary", "")[:40] for e in key_events[:3]
        )

    synthesis = {
        "date": today,
        "shipped_count": shipped_count,
        "peak_emotion": peak_emotion,
        "key_events": key_events[:10],
        "conversation_count": conversation_count,
        "chronicle_entries": len(chronicle_entries),
        "synthesis_text": synthesis_text,
        "generated_at": now,
    }

    try:
        _DAILY_SYNTH_DIR.mkdir(parents=True, exist_ok=True)
        synth_file = _DAILY_SYNTH_DIR / f"{today}.json"
        synth_file.write_text(json.dumps(synthesis, indent=2))
        result["synthesis_file"] = str(synth_file)
    except OSError as e:
        result["synthesis_error"] = str(e)

    # 5. Apply overnight endocrine decay
    if endocrine_mod is not None:
        try:
            endocrine_mod.tick(hours=1.0)
            result["endocrine_decayed"] = True
        except Exception:
            pass

    # 6. Fire rem_success if >3 meaningful events
    if meaningful_event_count > 3 and endocrine_mod is not None:
        try:
            endocrine_mod.apply_event("rem_success")
            result["rem_success_fired"] = True
        except Exception:
            pass

    # Update restoration state
    state["last_run"] = now
    state["run_count"] = state.get("run_count", 0) + 1
    state["last_synthesis_file"] = result.get("synthesis_file")
    _save_state(state)

    return result


def get_last_synthesis() -> dict:
    """Load and return the most recent synthesis file."""
    if not _DAILY_SYNTH_DIR.exists():
        return {}

    # Find all synthesis files, return the most recent
    synth_files = sorted(_DAILY_SYNTH_DIR.glob("*.json"), reverse=True)
    if not synth_files:
        return {}

    try:
        return json.loads(synth_files[0].read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def get_status() -> dict:
    """Return restoration system status."""
    state = _load_state()
    now = time.time()
    hours_since = (now - state.get("last_run", 0)) / 3600.0

    return {
        "last_run": state.get("last_run", 0),
        "hours_since_last_run": round(hours_since, 1),
        "run_count": state.get("run_count", 0),
        "last_synthesis_file": state.get("last_synthesis_file"),
        "ready": hours_since > _MIN_INTERVAL_HOURS,
    }
