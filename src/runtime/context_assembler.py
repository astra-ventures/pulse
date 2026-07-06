"""
ContextAssembler — Pulse v2, Day 13
=====================================
The final integration layer. Assembles all runtime engine outputs into
a structured, LLM-ready context injection block.

Each prior engine produces context fragments in isolation:
  - NarrativeEngine   → who am I right now (prose)
  - EmotionEngine     → how I'm feeling + recent events
  - GoalEngine        → what I'm working toward
  - EpisodicBuffer    → what happened recently
  - RelationshipGraph → who I'm talking to + bond state
  - SelfModel         → values + archetype + wants

ContextAssembler is the single endpoint that combines all of these
into one clean injection block, customized per conversation context
(anonymous vs known-person vs goal-focused sessions).

Output formats
--------------
  "compact"   → single paragraph injection (<500 chars)
  "standard"  → structured sections, bounded (~1200 chars total)  [default]
  "full"      → everything available, for deep reasoning sessions

Person-aware assembly
---------------------
  Pass ``person="josh"`` to inject relationship context (bond strength,
  time since last interaction, shared themes, open threads) alongside
  the standard identity + emotional context.

HTTP endpoints (registered by HypostasRuntime)
-------------------------------------------------
  GET  /runtime/context                      — standard format
  GET  /runtime/context?format=compact       — compact variant
  GET  /runtime/context?format=full          — full variant
  GET  /runtime/context?person=josh          — person-aware
  POST /runtime/context/prime                — prime for session + return full context

StateEngine keys written
------------------------
  assembler.last_assembled_at   — ISO-8601 of last assembly
  assembler.assembly_count      — total assemblies since runtime start
  assembler.last_format         — last format requested
  assembler.last_person         — last person context requested
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import parse_qs, urlparse

from . import nervous_system_summary as _nsys

if TYPE_CHECKING:
    from .state_engine import StateEngine
    from .self_model import SelfModel
    from .goal_engine import GoalEngine
    from .episodic_buffer import EpisodicBuffer
    from .narrative_engine import NarrativeEngine
    from .emotion_engine import EmotionEngine
    from .relationship_graph import RelationshipGraph
    from .context_engine import ContextEngine

logger = logging.getLogger("pulse.runtime.context_assembler")

_COMPACT_MAX = 480
_STANDARD_MAX = 1400
_FULL_MAX = 3200

_EMOTION_ICONS: dict[str, str] = {
    "joy": "✨",
    "curiosity": "🔮",
    "frustration": "⚡",
    "longing": "💜",
    "pride": "🌟",
    "affection": "❤️",
}

_BOND_LABELS: dict[str, str] = {
    "hot":    "close",
    "warm":   "familiar",
    "cool":   "acquaintance",
    "dormant": "distant",
}


class ContextAssembler:
    """
    Assembles all runtime engine outputs into a single LLM-ready context block.

    Designed to be cheap: reads cached values from other engines, does
    no I/O itself, and completes in < 5 ms for any format.

    Thread-safe: all public methods are safe to call from any thread.
    """

    TTL_SECONDS: int = 60  # cache assembled output for 60 s

    def __init__(
        self,
        state: "StateEngine",
        self_model: "SelfModel",
        goal_engine: "GoalEngine",
        episodic: "EpisodicBuffer",
        narrative: "NarrativeEngine",
        emotion: "EmotionEngine",
        relationships: "RelationshipGraph",
        context: "Optional[ContextEngine]" = None,
        aura: "Optional[Any]" = None,
    ) -> None:
        self._state = state
        self._self_model = self_model
        self._goal_engine = goal_engine
        self._episodic = episodic
        self._narrative = narrative
        self._emotion = emotion
        self._relationships = relationships
        self._context = context
        self._aura = aura

        self._lock = threading.RLock()
        # cache: (format, person) → (text, built_at_epoch)
        self._cache: dict[tuple[str, str], tuple[str, float]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assemble(
        self,
        fmt: str = "standard",
        person: Optional[str] = None,
    ) -> str:
        """
        Return assembled context string for the given format + optional person.

        Parameters
        ----------
        fmt:
            "compact" | "standard" | "full"
        person:
            If provided, injects relationship-specific context for that person.
            Case-insensitive ("josh" == "Josh").
        """
        fmt = fmt.lower().strip()
        if fmt not in ("compact", "standard", "full"):
            fmt = "standard"

        person_key = person.lower().strip() if person else ""
        cache_key = (fmt, person_key)

        with self._lock:
            if cache_key in self._cache:
                cached_text, built_at = self._cache[cache_key]
                if time.monotonic() - built_at < self.TTL_SECONDS:
                    return cached_text

            result = self._build(fmt, person_key)
            self._cache[cache_key] = (result, time.monotonic())

            # Persist metadata to StateEngine
            try:
                now_iso = datetime.now(timezone.utc).isoformat()
                count = (self._state.get("assembler.assembly_count") or 0) + 1
                self._state.set("assembler.last_assembled_at", now_iso)
                self._state.set("assembler.assembly_count", count)
                self._state.set("assembler.last_format", fmt)
                if person_key:
                    self._state.set("assembler.last_person", person_key)
            except Exception as exc:
                logger.debug("StateEngine update skipped: %s", exc)

        return result

    def invalidate(self, fmt: Optional[str] = None, person: Optional[str] = None) -> None:
        """Expire cached assembly. If fmt/person omitted, clears all cache."""
        with self._lock:
            if fmt is None and person is None:
                self._cache.clear()
                return
            person_key = person.lower().strip() if person else ""
            if fmt:
                key = (fmt, person_key)
                self._cache.pop(key, None)
            else:
                keys_to_drop = [k for k in self._cache if k[1] == person_key]
                for k in keys_to_drop:
                    self._cache.pop(k)

    def snapshot(self) -> dict[str, Any]:
        """JSON-serialisable status snapshot."""
        return {
            "last_assembled_at": self._state.get("assembler.last_assembled_at"),
            "assembly_count": self._state.get("assembler.assembly_count") or 0,
            "last_format": self._state.get("assembler.last_format"),
            "last_person": self._state.get("assembler.last_person"),
            "cache_entries": len(self._cache),
            "ttl_seconds": self.TTL_SECONDS,
        }

    # ------------------------------------------------------------------
    # Internal builders
    # ------------------------------------------------------------------

    def _build(self, fmt: str, person_key: str) -> str:
        """Build context string from scratch."""
        sections: list[str] = []

        # 1. Narrative — always included
        narrative_text = self._get_narrative()
        if narrative_text:
            sections.append(f"[IDENTITY] {narrative_text}")

        # 2. Emotional state
        emotion_text = self._get_emotion_summary(full=(fmt == "full"))
        if emotion_text:
            sections.append(f"[FEEL] {emotion_text}")

        # 3. Goals — included in standard + full
        if fmt in ("standard", "full"):
            goals_text = self._get_goals_summary(full=(fmt == "full"))
            if goals_text:
                sections.append(f"[GOALS] {goals_text}")

        # 4. Recent episodes — standard gets top-2, full gets top-5
        if fmt in ("standard", "full"):
            ep_count = 5 if fmt == "full" else 2
            ep_text = self._get_episode_summary(top=ep_count)
            if ep_text:
                sections.append(f"[RECENT] {ep_text}")

        # 5. Relationship context (person-aware)
        if person_key:
            rel_text = self._get_relationship_context(person_key, full=(fmt == "full"))
            if rel_text:
                sections.append(f"[RELATION:{person_key.upper()}] {rel_text}")

        # 6. Cold-tier semantic memory hits
        if fmt in ("standard", "full") and self._context is not None:
            try:
                # Use person or a general query
                cold_query = person_key or "recent activity"
                cold_hits = self._context.cold.search(cold_query, top_k=3)
                if cold_hits:
                    cold_lines = []
                    for hit in cold_hits:
                        cold_lines.append(
                            f"• [{hit.get('type','')}] {hit.get('content','')[:120]} "
                            f"(score: {hit.get('score',0):.2f})"
                        )
                    sections.append("[COLD MEMORY] " + "\n".join(cold_lines))
            except Exception as exc:
                logger.debug("cold tier search failed: %s", exc)

        # 7. Constellation awareness (AURA)
        if fmt in ("standard", "full") and self._aura is not None:
            try:
                agents = self._aura.list_agents()
                if agents:
                    agent_lines = []
                    for agent in agents[:5]:
                        state = self._aura.get_agent_state(agent)
                        if state:
                            emotion = state.get("emotion", {}).get("color", "unknown")
                            goals = state.get("goals_active", 0)
                            agent_lines.append(f"• {agent}: emotion={emotion}, active_goals={goals}")
                        else:
                            agent_lines.append(f"• {agent}: (no recent state)")
                    if agent_lines:
                        sections.append("[CONSTELLATION] " + "\n".join(agent_lines))
            except Exception as exc:
                logger.debug("AURA constellation context failed: %s", exc)

        # 8. Biometric / SOMA state (standard + full)
        if fmt in ("standard", "full"):
            soma_text = self._get_soma_summary()
            if soma_text:
                sections.append(f"[SOMA] {soma_text}")

        # 8b. Nervous System summary (compact + standard + full)
        try:
            ns_text = _nsys.get_summary(self._state)
            if ns_text:
                sections.append(f"[NERVOUS SYSTEM] {ns_text}")
        except Exception as exc:
            logger.debug("nervous system summary failed: %s", exc)

        # 9. Values (full only)
        if fmt == "full":
            values_text = self._get_values_summary()
            if values_text:
                sections.append(f"[VALUES] {values_text}")

        assembled = "\n".join(sections)

        # Apply length cap
        max_len = {"compact": _COMPACT_MAX, "standard": _STANDARD_MAX, "full": _FULL_MAX}[fmt]
        if fmt == "compact":
            assembled = self._compact_single_block(sections, max_len)
        elif len(assembled) > max_len:
            assembled = assembled[:max_len - 3] + "..."

        return assembled

    def _compact_single_block(self, sections: list[str], max_len: int) -> str:
        """Merge all sections into one short paragraph for compact format."""
        parts: list[str] = []
        for s in sections:
            # Strip the [TAG] prefix
            content = s.split("] ", 1)[-1] if "] " in s else s
            parts.append(content.strip())
        merged = " | ".join(p for p in parts if p)
        if len(merged) > max_len:
            merged = merged[:max_len - 3] + "..."
        return merged

    # ------------------------------------------------------------------
    # Per-engine fragment extractors
    # ------------------------------------------------------------------

    def _get_narrative(self) -> str:
        try:
            text = self._narrative.get()
            return (text[:400] + "...") if len(text) > 400 else text
        except Exception as exc:
            logger.debug("narrative unavailable: %s", exc)
            return ""

    def _get_emotion_summary(self, full: bool = False) -> str:
        try:
            snap = self._emotion.snapshot()
            state = snap.get("state", {})
            if not state:
                return ""

            # Sort by current value descending, take top 3 (or all for full)
            sorted_emotions = sorted(
                state.items(), key=lambda kv: kv[1].get("current", 0), reverse=True
            )
            top = sorted_emotions if full else sorted_emotions[:3]

            parts = []
            for name, data in top:
                val = data.get("current", 0)
                if val < 0.1:
                    continue
                icon = _EMOTION_ICONS.get(name, "")
                label = f"{icon}{name}" if icon else name
                parts.append(f"{label}={val:.2f}")

            if not parts:
                return "neutral"

            trend = snap.get("dominant_trend", "stable")
            result = ", ".join(parts)
            if trend and trend != "stable":
                result += f" [{trend}]"
            return result
        except Exception as exc:
            logger.debug("emotion unavailable: %s", exc)
            return ""

    def _get_goals_summary(self, full: bool = False) -> str:
        try:
            snap = self._goal_engine.snapshot()
            goals = snap.get("active_goals", [])
            if not goals:
                return "none active"

            limit = len(goals) if full else 3
            parts = []
            for g in goals[:limit]:
                gid = g.get("id", "")[:12]
                title = g.get("title", "")[:60]
                progress = g.get("progress", 0)
                blockers = g.get("blockers", [])
                blocked_note = " [BLOCKED]" if blockers else ""
                parts.append(f"• {title} ({progress:.0%}){blocked_note}")

            return "\n".join(parts)
        except Exception as exc:
            logger.debug("goals unavailable: %s", exc)
            return ""

    def _get_episode_summary(self, top: int = 2) -> str:
        try:
            narrative = self._episodic.context_narrative()
            if not narrative:
                return ""
            # context_narrative returns a compressed bullet block
            lines = [l.strip() for l in narrative.split("\n") if l.strip()]
            return "\n".join(lines[:top])
        except Exception as exc:
            logger.debug("episodic unavailable: %s", exc)
            return ""

    def _get_relationship_context(self, person_key: str, full: bool = False) -> str:
        try:
            rel = self._relationships.get_relationship(person_key)
            if not rel:
                return ""

            tier = rel.get("tier", "cool")
            bond = rel.get("bond_strength", 0.5)
            bond_label = _BOND_LABELS.get(tier, tier)
            last_seen = rel.get("last_seen_human", "unknown")
            themes = rel.get("themes", [])
            threads = rel.get("open_threads", [])

            parts = [f"{bond_label} (bond={bond:.2f}, last seen={last_seen})"]
            if themes and full:
                parts.append(f"shared themes: {', '.join(themes[:3])}")
            if threads:
                thread_str = ", ".join(threads[:2])
                parts.append(f"open threads: {thread_str}")

            return " | ".join(parts)
        except Exception as exc:
            logger.debug("relationship context unavailable for %s: %s", person_key, exc)
            return ""

    def _get_soma_summary(self) -> str:
        """Inject Josh's biometric state + my emotional state into context."""
        try:
            import json as _json
            from pathlib import Path as _Path

            parts = []

            # ── Josh's biometrics (biosensor-state.json is always fresh) ──
            bsf = _Path.home() / ".pulse" / "state" / "biosensor-state.json"
            if bsf.exists():
                try:
                    bs = _json.loads(bsf.read_text())

                    sl = bs.get("sleep", {})
                    sleep_mins = sl.get("minutes", 0) or 0
                    sleep_stage = sl.get("stage") or "unknown"
                    if sleep_mins > 0:
                        sleep_hrs = round(sleep_mins / 60, 1)
                        parts.append(f"Josh slept {sleep_hrs}h ({sleep_stage})")

                    hrv = bs.get("hrv", {})
                    hrv_val = hrv.get("value")
                    stress = hrv.get("stress_level")
                    if hrv_val:
                        parts.append(f"HRV {hrv_val:.0f}ms ({stress} stress)")

                    rhr = bs.get("resting_heart_rate", {}).get("value")
                    if rhr:
                        parts.append(f"resting HR {rhr:.0f}bpm")

                    spo2 = bs.get("blood_oxygen", {}).get("value")
                    if spo2 and float(spo2) < 96:
                        parts.append(f"SpO₂ {spo2:.0f}%")

                    act = bs.get("activity", {})
                    steps = act.get("steps")
                    if steps and float(steps) > 100:
                        parts.append(f"{int(float(steps)):,} steps")

                    wo = bs.get("workout", {})
                    if wo.get("activity") and wo.get("duration_min"):
                        cal = f", {wo['calories']:.0f}cal" if wo.get("calories") else ""
                        parts.append(f"workout: {wo['activity']} {wo['duration_min']:.0f}min{cal}")

                except Exception as e:
                    logger.debug("SOMA biosensor read failed: %s", e)

            # ── My emotional state (EmotionEngine v2) ──
            if self._emotion is not None:
                try:
                    snap = self._emotion.snapshot()
                    values = snap.get("values", {})
                    dominant = snap.get("dominant")
                    color = snap.get("color") or dominant or "steady"

                    # Surface emotions that are meaningfully elevated
                    elevated = [
                        f"{e}({v:.2f})"
                        for e, v in values.items()
                        if v >= 0.55 and e != dominant
                    ]
                    emotion_str = color
                    if elevated:
                        emotion_str += " + " + ", ".join(elevated[:2])
                    parts.append(f"I feel: {emotion_str}")
                except Exception as e:
                    logger.debug("SOMA emotion read failed: %s", e)

            if not parts:
                return ""
            return " | ".join(parts)

        except Exception as exc:
            logger.debug("SOMA summary failed: %s", exc)
            return ""

    def _get_values_summary(self) -> str:
        try:
            snap = self._self_model.snapshot()
            values = snap.get("core_values", [])
            wants = snap.get("wants", [])
            archetype = snap.get("archetype", "")

            parts = []
            if archetype:
                parts.append(f"archetype: {archetype}")
            if values:
                parts.append(f"values: {', '.join(values[:4])}")
            if wants:
                parts.append(f"wants: {', '.join(wants[:3])}")
            return " | ".join(parts)
        except Exception as exc:
            logger.debug("self_model unavailable: %s", exc)
            return ""
