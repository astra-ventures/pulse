"""CALLOSUM — Logic-Emotion Bridge for Pulse.

Periodically reconciles logical (CORTEX-driven) and emotional
(LIMBIC/ENDOCRINE/REM) states to produce integrated self-awareness.
"""

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "callosum-state.json"
DREAM_DIR = Path.home() / ".openclaw" / "workspace" / "memory" / "self" / "dreams"


@dataclass
class BridgeInsight:
    timestamp: float
    logical_state: str
    emotional_state: str
    gut_signal: str  # toward|away|neutral
    split_detected: bool
    tension: str
    bridge: str
    integration_score: float

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "BridgeInsight":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── State persistence ───────────────────────────────────────────────────

def _load_state() -> dict:
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    if _DEFAULT_STATE_FILE.exists():
        try:
            return json.loads(_DEFAULT_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "insights": [],
        "integration_history": [],
        "last_bridge_ts": None,
        "last_mood_snapshot": None,
        "bridge_count": 0,
    }


def _save_state(state: dict):
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    _DEFAULT_STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Internal helpers ────────────────────────────────────────────────────

def _get_logical_state() -> str:
    """Read recent CORTEX/rational activity from THALAMUS."""
    try:
        entries = thalamus.read_by_source("cortex", n=5)
        entries += thalamus.read_by_type("state", n=3)
        entries += thalamus.read_by_source("nervous_system", n=3)
        if entries:
            summaries = []
            for e in entries[-5:]:
                data = e.get("data", {})
                reason = data.get("reason", data.get("type", str(data)[:80]))
                summaries.append(str(reason)[:100])
            return "; ".join(summaries) if summaries else "quiet — no recent logical activity"
        return "quiet — no recent logical activity"
    except Exception:
        return "unable to read logical state"


def _get_emotional_state() -> tuple[str, dict]:
    """Read ENDOCRINE mood + LIMBIC afterimages. Returns (summary, mood_dict)."""
    mood = {}
    parts = []
    try:
        from pulse.src import endocrine
        mood = endocrine.get_mood()
        parts.append(f"mood: {mood.get('label', 'unknown')}")
    except Exception:
        parts.append("mood: unknown")

    try:
        from pulse.src import limbic
        afterimages = limbic.get_current_afterimages()
        if afterimages:
            emotions = [a.get("emotion", "?") for a in afterimages[:3]]
            parts.append(f"afterimages: {', '.join(emotions)}")
    except Exception:
        pass

    return " | ".join(parts) if parts else "no emotional data", mood


def _get_gut_signal() -> str:
    """Read ENTERIC gut feeling."""
    try:
        from pulse.src import enteric
        intuition = enteric.gut_check({})
        return intuition.direction
    except Exception:
        return "neutral"


def _get_dream_themes() -> list[str]:
    """Read recent dream themes from dream logs."""
    themes = []
    try:
        if DREAM_DIR.exists():
            dream_files = sorted(DREAM_DIR.glob("*.md"), reverse=True)[:3]
            for f in dream_files:
                content = f.read_text()[:200]
                themes.append(content.split("\n")[0] if content else "")
    except Exception:
        pass
    return themes


def _calculate_integration(logical: str, emotional: str, gut: str) -> float:
    """Simple heuristic for how well logic and emotion align. 0.0-1.0."""
    score = 0.5  # baseline

    # If gut says "toward", slight boost
    if gut == "toward":
        score += 0.15
    elif gut == "away":
        score -= 0.15

    # If emotional state mentions positive mood, boost
    positive_words = {"content", "energized", "focused", "creative", "joy", "warmth"}
    negative_words = {"stressed", "anxious", "frustrated", "anguish", "melancholy"}

    emotional_lower = emotional.lower()
    if any(w in emotional_lower for w in positive_words):
        score += 0.15
    if any(w in emotional_lower for w in negative_words):
        score -= 0.1

    # If logical state is active (not quiet), slight boost
    if "quiet" not in logical.lower():
        score += 0.1

    return max(0.0, min(1.0, score))


def _detect_tension(logical: str, emotional: str, gut: str) -> tuple[bool, str, str]:
    """Detect if there's a split between logic and emotion.
    Returns (split_detected, tension, bridge)."""
    # Simple heuristic: if gut says away but logical is active, there's tension
    if gut == "away" and "quiet" not in logical.lower():
        return (True,
                "Logical side is active but gut feeling says pull away",
                "The resistance may signal a need to pause and reflect before continuing")

    # If emotional state is negative but logical is active
    neg_markers = {"stressed", "anxious", "frustrated", "cortisol"}
    emotional_lower = emotional.lower()
    if any(m in emotional_lower for m in neg_markers) and "quiet" not in logical.lower():
        return (True,
                f"Emotional state ({emotional}) conflicts with active logical processing",
                "Acknowledging the stress while continuing may help integrate both sides")

    # If afterimages present with no logical activity
    if "afterimage" in emotional_lower and "quiet" in logical.lower():
        return (True,
                "Emotional residue persists while logical side is idle",
                "The quiet may be needed to process lingering emotions")

    return (False, "", "Logic and emotion are reasonably aligned")


# ── Core functions ──────────────────────────────────────────────────────

def bridge() -> BridgeInsight:
    """Run a reconciliation cycle."""
    now = time.time() * 1000
    logical = _get_logical_state()
    emotional, mood = _get_emotional_state()
    gut = _get_gut_signal()
    dreams = _get_dream_themes()

    integration = _calculate_integration(logical, emotional, gut)
    split_detected, tension, bridge_text = _detect_tension(logical, emotional, gut)

    # If dreams present, note them
    if dreams:
        bridge_text += f" (recent dream themes: {'; '.join(d for d in dreams if d)})"

    insight = BridgeInsight(
        timestamp=now,
        logical_state=logical[:300],
        emotional_state=emotional[:300],
        gut_signal=gut,
        split_detected=split_detected,
        tension=tension[:300],
        bridge=bridge_text[:500],
        integration_score=integration,
    )

    # Save to state
    state = _load_state()
    state["insights"].append(insight.to_dict())
    state["insights"] = state["insights"][-50:]  # keep last 50
    state["integration_history"].append({"ts": now, "score": integration})
    state["integration_history"] = state["integration_history"][-100:]
    state["last_bridge_ts"] = now
    state["bridge_count"] = state.get("bridge_count", 0) + 1

    if mood:
        state["last_mood_snapshot"] = mood

    _save_state(state)

    # Broadcast to THALAMUS
    thalamus.append({
        "source": "callosum",
        "type": "insight",
        "salience": 0.6 if not split_detected else 0.8,
        "data": insight.to_dict(),
    })

    # If split detected, notify DISSONANCE
    if split_detected:
        try:
            dissonance_path = Path.home() / ".openclaw" / "workspace" / "memory" / "self" / "contradictions.md"
            if dissonance_path.exists():
                with open(dissonance_path, "a") as f:
                    f.write(f"\n\n### Callosum Split — {time.strftime('%Y-%m-%d %H:%M')}\n")
                    f.write(f"**Tension:** {tension}\n")
                    f.write(f"**Bridge:** {bridge_text}\n")
        except Exception:
            pass

    return insight


def get_recent_insights(n: int = 5) -> list[BridgeInsight]:
    """Recent reconciliation outputs."""
    state = _load_state()
    return [BridgeInsight.from_dict(i) for i in state.get("insights", [])[-n:]]


def get_integration_score() -> float:
    """Average integration score. 0.0 (split) to 1.0 (integrated)."""
    state = _load_state()
    history = state.get("integration_history", [])
    if not history:
        return 0.5
    recent = history[-10:]
    return sum(h["score"] for h in recent) / len(recent)


def detect_split() -> Optional[dict]:
    """If logic and emotion are strongly divergent, return the split."""
    logical = _get_logical_state()
    emotional, _ = _get_emotional_state()
    gut = _get_gut_signal()

    split_detected, tension, bridge_text = _detect_tension(logical, emotional, gut)
    if split_detected:
        return {
            "logical": logical[:200],
            "emotional": emotional[:200],
            "tension": tension,
            "bridge": bridge_text,
        }
    return None


def request_emergency_dream() -> bool:
    """When logic-emotion split persists >24hrs, set flag for REM to check."""
    state = _load_state()
    # Check if split has persisted for >24 hours
    recent_insights = state.get("insights", [])[-48:]  # ~48 bridge cycles
    if not recent_insights:
        return False
    
    now = time.time() * 1000
    twenty_four_hours_ms = 24 * 3600 * 1000
    
    # Count recent splits
    split_count = 0
    oldest_split_ts = None
    for insight in recent_insights:
        if insight.get("split_detected"):
            split_count += 1
            ts = insight.get("timestamp", 0)
            if oldest_split_ts is None or ts < oldest_split_ts:
                oldest_split_ts = ts
    
    if split_count >= 3 and oldest_split_ts and (now - oldest_split_ts) >= twenty_four_hours_ms:
        state["emergency_dream_requested"] = True
        state["emergency_dream_ts"] = now
        _save_state(state)
        
        thalamus.append({
            "source": "callosum",
            "type": "emergency_dream_request",
            "salience": 0.9,
            "data": {
                "split_count": split_count,
                "duration_hours": (now - oldest_split_ts) / 3600000,
                "reason": "Logic-emotion split persisting >24 hours",
            },
        })
        return True
    return False


def is_emergency_dream_requested() -> bool:
    """Check if an emergency dream has been requested."""
    state = _load_state()
    return state.get("emergency_dream_requested", False)


def clear_emergency_dream():
    """Clear the emergency dream flag (after REM processes it)."""
    state = _load_state()
    state["emergency_dream_requested"] = False
    _save_state(state)


def should_run(loop_count: int) -> bool:
    """Check if callosum should run this loop (every 10th)."""
    return loop_count > 0 and loop_count % 10 == 0


def load_state():
    """Public: load state (for startup)."""
    return _load_state()
