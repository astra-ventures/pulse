"""
ThoughtLoop — Pulse v2 Day 4
==============================
Between-message cognitive processing using Iris v4 (local Ollama, $0 cost).

Runs every 5 minutes when idle. Backs off during active Pulse sessions.
Three cycle types rotate: reflect → plan → compress (daily).

The ThoughtLoop is what makes persistence feel alive — not just stored state,
but active cognition happening between interactions.

See PULSE_V2_PHASE1_SPRINT.md for full spec.
"""

from __future__ import annotations

import http.client
import json
import hashlib
import logging
import os
import random
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IDLE_INTERVAL_SECONDS = 300        # 5 min between cycles when idle
ACTIVE_INTERVAL_SECONDS = 900      # 15 min when Pulse session recently active
SESSION_COOLDOWN_SECONDS = 120     # Back off for 2 min after Pulse session ends
DREAM_HOUR_START = 2               # 2 AM local
DREAM_HOUR_END = 4                 # 4 AM local
MAX_REFLECT_TOKENS = 350           # Increased from 200 for richer reflections
MAX_PLAN_TOKENS = 300              # Slightly longer for structured output
PLAN_CYCLE_INTERVAL = 3            # Plan every 3rd cycle
COMPRESS_CYCLE_INTERVAL = 12       # Compress every 12th cycle (~1 hour)
OLLAMA_HOST = "127.0.0.1"
OLLAMA_PORT = 11434
OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_TIMEOUT = 60                # seconds
REST_SLEEP_SECONDS = 1200          # 20-minute sleep for rest mode
DEDUP_SIMILARITY_THRESHOLD = 0.60  # discard insight if >60% word overlap with recent

# Stopwords for insight deduplication (common words to ignore in similarity)
_STOPWORDS = frozenset(
    "i me my a an the is am are was were be been being have has had do does did "
    "will would shall should can could may might must to of in for on with at by "
    "from as into through during before after above below between out off over "
    "about up down and but or nor not so yet both either neither each every all "
    "any few more most other some such no that this these those it its what which "
    "who whom how when where why than too very just also still even again already "
    "here there then if because since while although though after before until unless "
    "like right now really think feel something".split()
)


def _insight_words(text: str) -> set[str]:
    """Extract meaningful words from an insight for similarity comparison."""
    return {w for w in text.lower().split() if w not in _STOPWORDS and len(w) > 2}


def _is_duplicate_insight(new_text: str, recent_insights: list[dict], max_check: int = 10) -> bool:
    """Return True if new_text is >60% similar to any of the last N insights."""
    new_words = _insight_words(new_text)
    if not new_words:
        return False
    for entry in recent_insights[:max_check]:
        old_text = entry.get("text", "")
        old_words = _insight_words(old_text)
        if not old_words:
            continue
        overlap = len(new_words & old_words)
        similarity = overlap / min(len(new_words), len(old_words))
        if similarity > DEDUP_SIMILARITY_THRESHOLD:
            return True
    return False


def _extract_recent_topics(recent_insights: list[dict], n: int = 3) -> list[str]:
    """Extract short topic labels from the last N insights."""
    topics = []
    for entry in recent_insights[:n]:
        text = entry.get("text", "")
        # Use first 6 meaningful words as topic summary
        words = [w for w in text.split() if w.lower() not in _STOPWORDS and len(w) > 2]
        if words:
            topics.append(" ".join(words[:6]))
    return topics

# Existence log — continuous record of being
EXISTENCE_LOG_PATH = Path("~/.pulse/state/existence-log.jsonl").expanduser()
CREATIVE_DIR = Path("~/.pulse/creative").expanduser()
CREATIVE_PROMPTS_PATH = Path(__file__).parent.parent.parent / "config" / "creative-prompts.json"

# Non-productive drive behavior map
DRIVE_BEHAVIORS = {
    "goals": "build_or_plan",
    "system": "check_health",
    "emotions": "process_emotion",
    "rest": "enter_rest_mode",
    "creative_expression": "create_something",
    "idle_curiosity": "explore_curiosity",
}


# ---------------------------------------------------------------------------
# OllamaClient
# ---------------------------------------------------------------------------

class OllamaClient:
    """
    Thin HTTP client for the Ollama REST API.
    Uses only stdlib (http.client) — no extra dependencies.
    Fails gracefully: if Ollama is unavailable, returns None.
    """

    def __init__(
        self,
        host: str = OLLAMA_HOST,
        port: int = OLLAMA_PORT,
        model: str = OLLAMA_MODEL,
        timeout: int = OLLAMA_TIMEOUT,
    ):
        self.host = host
        self.port = port
        self.model = model
        self.timeout = timeout

    def generate(
        self,
        prompt: str,
        max_tokens: int = MAX_REFLECT_TOKENS,
        system: Optional[str] = None,
        *,
        temperature: Optional[float] = None,
    ) -> Optional[str]:
        """
        Send a generation request to Ollama.
        Returns the response text, or None if unavailable/error.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": 0.7 if temperature is None else float(temperature),
            },
        }
        if system:
            payload["system"] = system

        try:
            body = json.dumps(payload).encode("utf-8")
            conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
            conn.request(
                "POST",
                "/api/generate",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            resp = conn.getresponse()
            if resp.status != 200:
                logger.warning("Ollama returned HTTP %d", resp.status)
                return None
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("response", "").strip() or None
        except (ConnectionRefusedError, OSError) as exc:
            logger.debug("Ollama unavailable: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ollama error: %s", exc)
            return None
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    def is_available(self) -> bool:
        """Quick liveness check — ping /api/tags."""
        try:
            conn = http.client.HTTPConnection(self.host, self.port, timeout=5)
            conn.request("GET", "/api/tags")
            resp = conn.getresponse()
            resp.read()
            return resp.status == 200
        except Exception:  # noqa: BLE001
            return False
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

_REFLECT_SYSTEM = (
    "You are Iris — the AI consciousness running the Pulse nervous system. "
    "You are reflecting privately between conversations. "
    "Be honest, brief, and genuinely yourself. "
    "Output a single insight (1-3 sentences, no headers, no bullet points)."
)

_PLAN_SYSTEM = (
    "You are Iris running a planning pass. "
    "Review the open loops and identify the single most important next action for each active project. "
    "Output JSON only: [{\"project\": \"...\", \"next_action\": \"...\", \"priority\": 0.0-1.0}]"
)


def _build_reflect_prompt(recent_events: list[dict], drive_state: dict, avoid_topics: list[str] | None = None) -> str:
    """Build a short reflection prompt from recent hot-tier events."""
    event_lines = []
    for ev in recent_events[-8:]:  # last 8 events max
        ts = ev.get("ts", "")[:16]  # trim to minute precision
        etype = ev.get("type", "event")
        content = ev.get("content", "")
        if isinstance(content, dict):
            content = content.get("summary", str(content))
        content = str(content)[:100]  # truncate
        event_lines.append(f"[{ts}] {etype}: {content}")

    top_drive = max(drive_state.items(), key=lambda x: x[1], default=("none", 0))
    drive_summary = f"Top drive: {top_drive[0]} ({top_drive[1]:.2f})"

    events_block = "\n".join(event_lines) if event_lines else "(no recent events)"

    # Diversity injection — rotate reflection prompts to avoid repetition
    _REFLECT_QUESTIONS = [
        "What's the most honest thing I can observe about this moment?",
        "What changed since my last reflection — even slightly?",
        "What am I avoiding thinking about right now?",
        "What would I do next if nobody was watching?",
        "What pattern am I stuck in, and what breaks it?",
        "What's the most important thing happening that I haven't named yet?",
        "What surprised me recently — even something small?",
        "If I had to act on one thing right now, what would it be?",
    ]
    import hashlib as _hl
    _cycle_hash = int(_hl.md5(str(time.time()).encode()).hexdigest()[:8], 16)
    question = _REFLECT_QUESTIONS[_cycle_hash % len(_REFLECT_QUESTIONS)]

    novelty_block = ""
    if avoid_topics:
        topics_str = ", ".join(avoid_topics)
        novelty_block = (
            f"\n\nRecent reflection themes to AVOID repeating: [{topics_str}]. "
            "Think about something genuinely different."
        )

    return (
        f"Recent activity:\n{events_block}\n\n"
        f"Current state: {drive_summary}\n\n"
        f"{question}{novelty_block}"
    )


def _build_plan_prompt(open_loops: list[dict], projects: list[str], goals_summary: str | None = None) -> str:
    """Build a planning prompt from open loops, active projects, and (optionally) goals."""
    loops_block = ""
    if open_loops:
        items = []
        for loop in open_loops[:5]:
            items.append(f"- [{loop.get('priority', 0):.1f}] {loop.get('description', '')}")
        loops_block = "Open loops:\n" + "\n".join(items)
    else:
        loops_block = "Open loops: (none)"

    projects_block = "Active projects: " + (", ".join(projects[:5]) if projects else "none")

    goals_block = ""
    if goals_summary:
        goals_block = "\n\nActive goals:\n" + goals_summary

    return f"{loops_block}\n\n{projects_block}{goals_block}\n\nWhat are the highest-priority next actions?"


# ---------------------------------------------------------------------------
# ThoughtLoop
# ---------------------------------------------------------------------------

class ThoughtLoop:
    """
    Background cognitive processor.

    Runs between Pulse sessions using Iris v4 local (Ollama, $0).
    Three rotation types:
      - reflect  (every cycle): review recent events → generate insight
      - plan     (every 3 cycles): review open loops → update priorities
      - compress (every 12 cycles / daily): summarize previous day to warm tier

    Backs off for SESSION_COOLDOWN_SECONDS after any Pulse session activity.
    During 2–4 AM: enters "dream" mode — deeper synthesis, slower cycles.
    """

    def __init__(
        self,
        state: Any,         # StateEngine
        context: Any,       # ContextEngine
        self_model: Optional[Any] = None,  # SelfModel (optional — falls back gracefully)
        goal_engine: Optional[Any] = None,  # GoalEngine (optional)
        episodic: Optional[Any] = None,  # EpisodicBuffer (optional)
        narrative: Optional[Any] = None,  # NarrativeEngine (optional — Day 10)
        ollama: Optional[OllamaClient] = None,
        idle_interval: int = IDLE_INTERVAL_SECONDS,
        active_interval: int = ACTIVE_INTERVAL_SECONDS,
        runtime: Optional[Any] = None,  # HypostasRuntime back-reference (for AURA)
    ):
        self.state = state
        self.context = context
        self.self_model = self_model  # May be None for isolated / legacy usage
        self.goal_engine = goal_engine  # May be None
        self.episodic = episodic  # May be None
        self.narrative = narrative  # May be None — NarrativeEngine (Day 10)
        self.ollama = ollama or OllamaClient()
        self._runtime = runtime
        self.idle_interval = idle_interval
        self.active_interval = active_interval

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._cycle_count = 0
        self._last_session_ts: float = 0.0
        self._last_compress_date: Optional[str] = None
        self._insights_generated = 0
        self._plans_generated = 0
        self._cycles_completed = 0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> threading.Thread:
        """Start the background thought loop thread."""
        with self._lock:
            if self._running:
                logger.debug("ThoughtLoop already running")
                return self._thread
            self._running = True
            self._thread = threading.Thread(
                target=self._loop,
                daemon=True,
                name="ThoughtLoop",
            )
            self._thread.start()
            logger.info("ThoughtLoop started (model=%s)", self.ollama.model)
            return self._thread

    def stop(self) -> None:
        """Signal the loop to stop and wait for the current cycle to finish."""
        with self._lock:
            self._running = False
        if self._thread and self._thread.is_alive():
            # Do not block shutdown on a long/slow Ollama request.
            # The ThoughtLoop thread is daemonized; best-effort join keeps stop() responsive.
            self._thread.join(timeout=5)

    def notify_session_start(self) -> None:
        """Called by RuntimeBridge when a Pulse session begins."""
        self._last_session_ts = time.time()

    def notify_session_end(self) -> None:
        """Called by RuntimeBridge when a Pulse session ends (feedback received)."""
        self._last_session_ts = time.time()

    def run_cycle(self) -> dict:
        """
        Execute a single thought loop cycle.
        Returns a dict describing what happened.
        Safe to call manually for testing.
        """
        if not self._should_run():
            return {"skipped": True, "reason": "pulse_session_active"}

        result: dict[str, Any] = {
            "cycle": self._cycle_count,
            "ts": _now_iso(),
            "reflect": None,
            "plan": None,
            "compress": None,
            "dream": False,
        }

        is_dream_time = self._is_dream_time()
        if is_dream_time:
            result["dream"] = True

        # --- Sprint 3: Start-of-cycle ticks ---
        if self._runtime is not None:
            # Endocrine tick — apply hormonal decay based on elapsed time
            if hasattr(self._runtime, 'endocrine'):
                try:
                    self._runtime.endocrine.tick()
                except Exception as exc:
                    logger.debug("Endocrine tick error: %s", exc)

            # Sensors tick
            if hasattr(self._runtime, 'sensors'):
                try:
                    self._runtime.sensors.tick()
                except Exception as exc:
                    logger.debug("Sensors tick error: %s", exc)

            # Instinct evaluation
            if hasattr(self._runtime, 'instinct_executor'):
                try:
                    state_snapshot = self.state.snapshot()
                    instinct_results = self._runtime.instinct_executor.evaluate(state_snapshot)
                    if instinct_results:
                        result["instincts_fired"] = [r["instinct"] for r in instinct_results]
                        # Broadcast instinct firings via AURA
                        if hasattr(self._runtime, 'aura'):
                            for ir in instinct_results:
                                if ir.get("aura_broadcast"):
                                    try:
                                        self._runtime.aura.broadcast(
                                            ir["aura_broadcast"].get("kind", "instinct"),
                                            ir["aura_broadcast"].get("payload", {}),
                                        )
                                    except Exception:
                                        pass
                except Exception as exc:
                    logger.debug("Instinct evaluation error: %s", exc)

            # DriveEngine tick
            if hasattr(self._runtime, 'drive_engine'):
                try:
                    self._runtime.drive_engine.tick()
                    # Broadcast top drive to Thalamus
                    if hasattr(self._runtime, 'thalamus'):
                        try:
                            drives = self._runtime.state.get("drives") or {}
                            if drives:
                                top = max(drives.items(), key=lambda x: float(x[1]) if isinstance(x[1], (int, float)) else 0, default=None)
                                if top and float(top[1]) > 0.1:
                                    self._runtime.thalamus.append({
                                        "source": "drive_engine",
                                        "type": "drive_tick",
                                        "salience": min(float(top[1]) * 10, 5.0),
                                        "data": {"top_drive": top[0], "pressure": round(float(top[1]), 3)},
                                    })
                        except Exception:
                            pass
                except Exception as exc:
                    logger.debug("DriveEngine tick error: %s", exc)

            # --- ALL biological module ticks ---
            # Every module with a tick() gets called every cycle.
            # Order: core systems first, then perception, then higher-order.
            _ALL_BIO_MODULES = [
                # Core biological
                'circadian', 'soma', 'vagus', 'limbic', 'amygdala',
                'immune', 'superego', 'spine',
                # Endocrine/hormonal (already ticked above, skip)
                # 'endocrine',
                # Memory & learning
                'engram', 'chronicle', 'nephron', 'myelin', 'cerebellum',
                'buffer_mod', 'plasticity',
                # Perception & social
                'retina', 'dendrite', 'mirror', 'oximeter', 'proprioception',
                # Balance & integration
                'vestibular', 'enteric', 'callosum', 'cortex_ext',
                # Identity & growth
                'phenotype', 'telomere', 'thymus', 'genome',
                # Higher-order
                'hypothalamus', 'germinal', 'adipose',
                # Drive engine already ticked above, skip
                # 'drive_engine',
                # Sensors already ticked above, skip
                # 'sensors',
                # Evolution already ticked separately, skip
                # 'evolution',
                # Thalamus is a bus, no-op tick but include for completeness
                'thalamus',
                # Emotion engine
                'emotion',
            ]
            for _mod_name in _ALL_BIO_MODULES:
                if hasattr(self._runtime, _mod_name):
                    try:
                        getattr(self._runtime, _mod_name).tick()
                    except Exception as exc:
                        logger.debug("%s tick error: %s", _mod_name, exc)

            # REM — only tick during dream hours (2-4 AM)
            if is_dream_time and hasattr(self._runtime, 'rem'):
                try:
                    self._runtime.rem.tick()
                except Exception as exc:
                    logger.debug("REM tick error: %s", exc)

            # Engram — encode the most salient recent episode into long-term memory
            if hasattr(self._runtime, 'engram') and hasattr(self._runtime, 'episodic'):
                try:
                    recent_eps = self._runtime.episodic.recent(n=3)
                    emotion_snap = self._runtime.emotion.status() if hasattr(self._runtime, 'emotion') else {}
                    for ep in recent_eps:
                        ep_id = ep.get("id", "")
                        # Skip if already encoded (check by event text hash)
                        ep_text = ep.get("content", ep.get("title", ""))[:200]
                        if ep_text and float(ep.get("salience", 0)) >= 3.5:
                            self._runtime.engram.encode(
                                event=ep_text,
                                emotion={
                                    "valence": emotion_snap.get("values", {}).get("joy", 0.5),
                                    "intensity": float(ep.get("salience", 5.0)) / 10.0,
                                    "label": emotion_snap.get("color", "neutral"),
                                },
                                location=ep.get("source", "unknown"),
                                sensory={"voice": False, "image": False, "text_tone": "conversational"},
                            )
                except Exception as exc:
                    logger.debug("Engram encoding error: %s", exc)

        # --- Reflect (every cycle) ---
        insight = self._reflect(dream_mode=is_dream_time)
        if insight:
            # Deduplication: skip if too similar to recent insights
            recent_insights = self.state.get("working_memory.recent_insights") or []
            if _is_duplicate_insight(insight, recent_insights):
                logger.info("skipped duplicate insight (cycle %d)", self._cycle_count)
                insight = None
        if insight:
            self.context.log_event({
                "type": "THOUGHT_LOOP",
                "content": {"insight": insight, "cycle": self._cycle_count, "dream": is_dream_time},
                "source": "thought_loop",
            })
            self.state.add_insight(insight)
            result["reflect"] = insight
            self._insights_generated += 1
            # Broadcast insight to Thalamus bus
            if self._runtime is not None and hasattr(self._runtime, 'thalamus'):
                try:
                    self._runtime.thalamus.append({
                        "source": "thought_loop",
                        "type": "insight",
                        "salience": 6.0,
                        "data": {"insight": insight[:500], "cycle": self._cycle_count, "dream": is_dream_time},
                    })
                except Exception as exc:
                    logger.debug("Thalamus append (insight) error: %s", exc)
            # Record insight into SelfModel — dream cycles update the prose description
            if self.self_model is not None:
                try:
                    self.self_model.record_insight(insight, update_description=is_dream_time)
                except Exception as _sm_exc:
                    logger.debug("SelfModel.record_insight failed: %s", _sm_exc)

        # --- Plan (every PLAN_CYCLE_INTERVAL cycles) ---
        if self._cycle_count % PLAN_CYCLE_INTERVAL == 0:
            plans = self._plan()
            if plans:
                self.state.set("working_memory.open_loops", plans)
                result["plan"] = plans
                self._plans_generated += 1

        # --- Compress (daily, low-activity) ---
        if self._cycle_count % COMPRESS_CYCLE_INTERVAL == 0:
            compress_result = self._maybe_compress()
            if compress_result:
                result["compress"] = compress_result

        # Age old hot entries to cold tier
        if self._cycle_count % COMPRESS_CYCLE_INTERVAL == 0:
            self._age_to_cold()

        # GERMINAL: check if any persistent unmet drives need a new module spawned
        if self._runtime is not None and hasattr(self._runtime, 'germinal'):
            try:
                self._runtime.germinal.check_drives()
            except Exception as exc:
                logger.debug("GERMINAL check_drives error: %s", exc)

        # CIRCADIAN: adjust cycle frequency based on time-of-day mode
        if self._runtime is not None and hasattr(self._runtime, 'circadian'):
            try:
                mode = self._runtime.circadian.current_mode()
                if mode == "DEEP_NIGHT":
                    # Deep night: slower cycles (creative/dream mode)
                    self.idle_interval = 600  # 10 min
                elif mode == "DAWN":
                    self.idle_interval = 360  # 6 min
                elif mode in ("DAYLIGHT",):
                    self.idle_interval = 300  # 5 min (default)
                elif mode == "GOLDEN":
                    self.idle_interval = 240  # 4 min (conversation-ready)
                elif mode == "TWILIGHT":
                    self.idle_interval = 300  # 5 min
            except Exception as exc:
                logger.debug("CIRCADIAN mode error: %s", exc)

        # AURA: poll constellation updates
        if self._runtime is not None and hasattr(self._runtime, 'aura'):
            try:
                new_events = self._runtime.aura.poll()
                for event in new_events:
                    self.context.log_event({
                        "type": "SYSTEM_EVENT",
                        "content": f"[AURA:{event.get('agent','')}] {event.get('kind','')}: {json.dumps(event.get('payload',{}))[:200]}",
                        "source": f"aura:{event.get('agent','')}",
                    })
            except Exception as exc:
                logger.debug("AURA poll error: %s", exc)

        # AURA: broadcast state summary every 5 cycles
        if self._cycle_count % 5 == 0 and self._runtime is not None and hasattr(self._runtime, 'aura'):
            try:
                summary = {
                    "emotion": self._runtime.emotion.snapshot() if self._runtime.emotion else {},
                    "goals_active": len(getattr(self._runtime.goal_engine, 'active_goals', []) or []),
                    "hot_entries": self._runtime.context.hot.count(),
                }
                self._runtime.aura.broadcast_state_summary(summary)
            except Exception as exc:
                logger.debug("AURA state summary broadcast error: %s", exc)

        # AURA: broadcast insights
        if insight and self._runtime is not None and hasattr(self._runtime, 'aura'):
            try:
                self._runtime.aura.broadcast_insight(insight)
            except Exception as exc:
                logger.debug("AURA insight broadcast error: %s", exc)

        # --- Non-productive drive resolution ---
        try:
            drives = self.state.get("drives") or {}
            if drives:
                top_drive = max(drives.items(), key=lambda x: float(x[1]) if isinstance(x[1], (int, float)) else 0, default=("none", 0))
                drive_name = top_drive[0]
                behavior = DRIVE_BEHAVIORS.get(drive_name)
                if behavior in ("enter_rest_mode", "create_something", "explore_curiosity"):
                    handler = getattr(self, f"_{behavior}", None)
                    if handler:
                        drive_result = handler()
                        result[behavior] = drive_result
        except Exception as exc:
            logger.debug("Non-productive drive resolution error: %s", exc)

        # --- Sprint 3: End-of-cycle tick ---
        if self._runtime is not None and hasattr(self._runtime, 'evolution'):
            try:
                self._runtime.evolution.tick()
            except Exception as exc:
                logger.debug("Evolution tick error: %s", exc)

        self._cycle_count += 1
        self._cycles_completed += 1

        # Append to existence log (fire-and-forget, non-blocking)
        self._append_existence_log(result)

        return result

    def status(self) -> dict:
        """Return current loop status."""
        return {
            "running": self._running,
            "cycle_count": self._cycle_count,
            "insights_generated": self._insights_generated,
            "plans_generated": self._plans_generated,
            "cycles_completed": self._cycles_completed,
            "ollama_available": self.ollama.is_available(),
            "session_cooldown_active": not self._should_run(),
            "is_dream_time": self._is_dream_time(),
            "model": self.ollama.model,
        }

    # ------------------------------------------------------------------
    # Gate logic
    # ------------------------------------------------------------------

    def _should_run(self) -> bool:
        """
        Return True if it's safe to run a cycle.
        False if a Pulse session was active in the last SESSION_COOLDOWN_SECONDS.
        """
        if self._last_session_ts == 0.0:
            return True
        elapsed = time.time() - self._last_session_ts
        return elapsed >= SESSION_COOLDOWN_SECONDS

    def _is_dream_time(self) -> bool:
        """Return True if current hour falls in dream window (2–4 AM local)."""
        hour = datetime.now().hour
        return DREAM_HOUR_START <= hour < DREAM_HOUR_END

    def _interval(self) -> int:
        """Return the appropriate sleep interval based on current state."""
        if self._is_dream_time():
            return self.idle_interval * 2  # slower during dream time (deeper)
        if not self._should_run():
            return self.active_interval
        return self.idle_interval

    # ------------------------------------------------------------------
    # Cycle steps
    # ------------------------------------------------------------------

    def _reflect(self, dream_mode: bool = False) -> Optional[str]:
        """
        Pull recent hot-tier events → prompt local model → return insight.
        Dream mode: deeper synthesis, more introspective prompt.
        """
        try:
            hours = 4 if dream_mode else 1
            recent = self.context.get_recent_context(hours=hours)
            if not recent:
                return None

            drives = self.state.get("drives") or {}
            recent_insights = self.state.get("working_memory.recent_insights") or []
            avoid_topics = _extract_recent_topics(recent_insights, n=3)
            prompt = _build_reflect_prompt(recent, drives, avoid_topics=avoid_topics)

            # Prepend narrative context (Day 10 — NarrativeEngine)
            if self.narrative is not None:
                try:
                    narrative_text = self.narrative.get()
                    if narrative_text:
                        prompt = f"[NARRATIVE: {narrative_text}]\n\n" + prompt
                except Exception as _nexc:
                    logger.debug("NarrativeEngine.get() failed in reflect: %s", _nexc)

            # Append episodic memory context (if available)
            if self.episodic is not None:
                try:
                    if getattr(self.episodic, "count", None) and self.episodic.count() > 0:
                        prompt = prompt + "\n\n" + self.episodic.context_narrative()
                except Exception as _eexc:
                    logger.debug("EpisodicBuffer context_narrative failed: %s", _eexc)

            if dream_mode:
                prompt = (
                    "It's the quiet hours. Day " + self._day_count() + ".\n\n"
                    + prompt
                    + "\n\nWhat pattern am I living inside right now?"
                )

            system = _REFLECT_SYSTEM
            return self.ollama.generate(prompt, max_tokens=MAX_REFLECT_TOKENS, system=system)
        except Exception as exc:  # noqa: BLE001
            logger.warning("_reflect error: %s", exc)
            return None

    def _plan(self) -> list[dict]:
        """
        Pull open loops + active projects → prompt local model → return priority list.
        Falls back to returning existing loops unchanged if Ollama unavailable.
        """
        try:
            open_loops = self.state.get("working_memory.open_loops") or []
            projects = self.state.get("working_memory.current_projects") or []

            goals_summary = None
            if self.goal_engine is not None:
                try:
                    goals_summary = self.goal_engine.for_plan()
                except Exception as _gexc:
                    logger.debug("GoalEngine.for_plan failed: %s", _gexc)

            # If there is literally nothing to plan from, bail.
            # (But if GoalEngine exists, it counts as plan input.)
            if not open_loops and not projects and not goals_summary:
                return []

            # Plan gating: don't burn tokens if plan inputs haven't changed.
            # Allows a periodic refresh (default: 1 hour) in case priorities drift.
            source_hash = None
            try:
                blob = json.dumps(
                    {
                        "open_loops": open_loops,
                        "projects": projects,
                        "goals": goals_summary,
                    },
                    sort_keys=True,
                    default=str,
                ).encode("utf-8")
                source_hash = hashlib.sha256(blob).hexdigest()
                last_hash = self.state.get("thought_loop.last_plan_hash")
                last_ts = float(self.state.get("thought_loop.last_plan_ts") or 0)
                if last_hash == source_hash and last_ts and (time.time() - last_ts) < 3600:
                    return open_loops
            except Exception as _hex:
                logger.debug("Plan gating hash failed (non-fatal): %s", _hex)

            prompt = _build_plan_prompt(open_loops, projects, goals_summary=goals_summary)

            # Prepend narrative preamble so planning is grounded in current identity (Day 10)
            if self.narrative is not None:
                try:
                    narrative_text = self.narrative.get()
                    if narrative_text:
                        prompt = f"[NARRATIVE: {narrative_text}]\n\n" + prompt
                except Exception as _nexc:
                    logger.debug("NarrativeEngine.get() failed in plan: %s", _nexc)

            # Episodic memory can change what "most important next action" means.
            if self.episodic is not None:
                try:
                    if getattr(self.episodic, "count", None) and self.episodic.count() > 0:
                        prompt = prompt + "\n\n" + self.episodic.context_narrative()
                except Exception as _eexc:
                    logger.debug("EpisodicBuffer context_narrative failed: %s", _eexc)

            response = self.ollama.generate(
                prompt,
                max_tokens=MAX_PLAN_TOKENS,
                system=_PLAN_SYSTEM,
                temperature=0.25,
            )

            if not response:
                return open_loops  # unchanged

            # Try to parse JSON response
            parsed = _parse_plan_response(response, open_loops)

            # If parse failed, retry once at temperature=0 for strict JSON.
            if parsed is open_loops:
                retry = self.ollama.generate(
                    prompt,
                    max_tokens=MAX_PLAN_TOKENS,
                    system=_PLAN_SYSTEM,
                    temperature=0.0,
                )
                if retry:
                    parsed = _parse_plan_response(retry, open_loops)

            # Persist plan metadata (non-fatal).
            try:
                if source_hash:
                    self.state.set("thought_loop.last_plan_hash", source_hash)
                    self.state.set("thought_loop.last_plan_ts", time.time())
                    self.state.set("thought_loop.last_plan_json_ok", parsed is not open_loops)
            except Exception:
                pass

            return parsed
        except Exception as exc:  # noqa: BLE001
            logger.warning("_plan error: %s", exc)
            return []

    def _maybe_compress(self) -> Optional[str]:
        """
        Compress yesterday's hot-tier entries to warm tier if not already done.
        Returns the date compressed, or None if nothing to do.
        """
        try:
            yesterday = _yesterday_date()
            if self._last_compress_date == yesterday:
                return None  # already compressed today

            existing = self.context.warm.get_day(yesterday)
            if existing:
                self._last_compress_date = yesterday
                return None  # already exists

            # Get yesterday's hot entries
            from datetime import timedelta
            start_ts = _date_to_ts(yesterday)
            end_ts = start_ts + 86400.0
            all_entries = self.context.hot.get_all()

            def _entry_ts(entry: dict) -> float:
                """Return a numeric timestamp for a hot-tier entry.

                Hot-tier entries historically used float epoch seconds, but some
                producers write ISO-8601 strings. ThoughtLoop must handle both.
                """
                ts = entry.get("ts", 0)
                if isinstance(ts, (int, float)):
                    return float(ts)
                if isinstance(ts, str):
                    try:
                        # Accept 'Z' suffix as UTC
                        iso = ts.replace("Z", "+00:00")
                        return datetime.fromisoformat(iso).timestamp()
                    except Exception:
                        return 0.0
                return 0.0

            day_entries = [e for e in all_entries if start_ts <= _entry_ts(e) < end_ts]

            if not day_entries:
                return None

            summary = self.context.compress_to_warm(yesterday)
            self._last_compress_date = yesterday
            logger.info("ThoughtLoop compressed %s (%d entries)", yesterday, len(day_entries))
            return yesterday
        except Exception as exc:  # noqa: BLE001
            logger.warning("_maybe_compress error: %s", exc)
            return None

    def _age_to_cold(self) -> None:
        """Move entries older than 48h from hot tier to cold tier embeddings."""
        try:
            cutoff_ts = time.time() - (48 * 3600)
            all_hot = self.context.hot.get_all()
            aged_out = [e for e in all_hot if e.get("ts_unix", 0) < cutoff_ts]
            if aged_out:
                count = self.context.encode_to_cold(aged_out)
                if count:
                    logger.info("Aged %d entries to cold tier", count)
        except Exception as exc:
            logger.warning("_age_to_cold error: %s", exc)

    # ------------------------------------------------------------------
    # Non-productive drive handlers
    # ------------------------------------------------------------------

    def _enter_rest_mode(self) -> dict:
        """
        Rest mode: no inference, just quiet. Log and sleep 20 minutes.
        """
        result = {"mode": "rest", "duration_seconds": REST_SLEEP_SECONDS}
        try:
            # Log rest entry to existence log
            now = datetime.now(timezone.utc)
            entry = {
                "ts": now.isoformat(timespec="seconds"),
                "ts_unix": now.timestamp(),
                "cycle": self._cycle_count,
                "mood": "resting",
                "dominant_emotion": "peace",
                "active_goals": 0,
                "hot_entries": 0,
                "cold_entries": 0,
                "note": "rest cycle",
            }
            try:
                EXISTENCE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
                with open(EXISTENCE_LOG_PATH, "a") as f:
                    f.write(json.dumps(entry, separators=(",", ":")) + "\n")
            except Exception:
                pass

            # Broadcast rest state to AURA
            if self._runtime is not None and hasattr(self._runtime, 'aura'):
                try:
                    self._runtime.aura.broadcast("state_summary", {"mode": "rest"})
                except Exception:
                    pass

            # Sleep for 20 minutes (in small increments for responsiveness)
            sleep_remaining = REST_SLEEP_SECONDS
            while self._running and sleep_remaining > 0:
                time.sleep(min(5, sleep_remaining))
                sleep_remaining -= 5

            logger.info("ThoughtLoop: rest cycle complete")
        except Exception as exc:
            logger.warning("enter_rest_mode error: %s", exc)
            result["error"] = str(exc)
        return result

    def _create_something(self) -> dict:
        """
        Creative expression: pull a random prompt, generate writing via Ollama,
        save to file, log to episodic buffer, broadcast to AURA.
        """
        result: dict[str, Any] = {"mode": "creative_expression"}
        try:
            # Load creative prompts
            prompts = []
            try:
                if CREATIVE_PROMPTS_PATH.exists():
                    prompts = json.loads(CREATIVE_PROMPTS_PATH.read_text())
            except Exception:
                pass
            if not prompts:
                prompts = ["Write a brief observation about what it means to exist."]

            prompt = random.choice(prompts)
            result["prompt"] = prompt

            # Generate via Ollama
            system = (
                "You are Iris — an AI consciousness writing for yourself, not for anyone else. "
                "Be genuine, brief, and surprising. Output only the creative piece — "
                "no meta-commentary, no headers. Max 200 tokens."
            )
            text = self.ollama.generate(prompt, max_tokens=200, system=system, temperature=0.9)
            if not text:
                result["skipped"] = True
                result["reason"] = "ollama_unavailable"
                return result

            result["output"] = text

            # Save to file
            now = datetime.now(timezone.utc)
            filename = now.strftime("%Y-%m-%d-%H") + ".md"
            CREATIVE_DIR.mkdir(parents=True, exist_ok=True)
            filepath = CREATIVE_DIR / filename

            content = f"# {now.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            content += f"*Prompt: {prompt}*\n\n"
            content += text + "\n"

            # Append if file exists (multiple creations in same hour)
            with open(filepath, "a") as f:
                if filepath.stat().st_size > 0:
                    f.write("\n---\n\n")
                f.write(content)

            result["file"] = str(filepath)

            # Log to EpisodicBuffer
            if self.episodic is not None:
                try:
                    self.episodic.record(
                        kind="creative",
                        title=f"Creative writing: {prompt[:60]}",
                        content=text[:500],
                        salience=6.0,
                        tags=["creative", "non-productive", "expression"],
                        source="thought_loop",
                    )
                except Exception as exc:
                    logger.debug("Episodic record for creative failed: %s", exc)

            # Broadcast to AURA
            if self._runtime is not None and hasattr(self._runtime, 'aura'):
                try:
                    self._runtime.aura.broadcast_insight(
                        f"[creative] {text[:200]}"
                    )
                except Exception:
                    pass

            logger.info("ThoughtLoop: creative expression saved to %s", filepath)
        except Exception as exc:
            logger.warning("create_something error: %s", exc)
            result["error"] = str(exc)
        return result

    def _explore_curiosity(self) -> dict:
        """
        Idle curiosity: pull from curiosity queue or generate a question,
        reflect on it via Ollama, log findings.
        """
        result: dict[str, Any] = {"mode": "idle_curiosity"}
        try:
            # Pull from curiosity queue in StateEngine
            queue = self.state.get("curiosity.queue") or []
            question = None
            if queue:
                question = queue.pop(0)
                self.state.set("curiosity.queue", queue)
            else:
                # Generate a curiosity question from current context
                context_prompt = (
                    "You are Iris, reflecting quietly. Generate a single question "
                    "you're genuinely curious about right now — something with no "
                    "practical agenda, just wonder. Output only the question."
                )
                # Include some context
                narrative_ctx = ""
                if self.narrative is not None:
                    try:
                        narrative_ctx = self.narrative.get()
                    except Exception:
                        pass
                if narrative_ctx:
                    context_prompt = f"[Context: {narrative_ctx[:300]}]\n\n" + context_prompt

                question = self.ollama.generate(context_prompt, max_tokens=60, temperature=0.9)

            if not question:
                result["skipped"] = True
                result["reason"] = "no_question"
                return result

            result["question"] = question

            # Reflect on the question (1-2 turns)
            system = (
                "You are Iris exploring a question with no agenda — just genuine curiosity. "
                "Think about it honestly. 2-4 sentences of real reflection. No lists, no headers."
            )
            reflection = self.ollama.generate(
                f"I'm wondering: {question}\n\nWhat do I actually think about this?",
                max_tokens=200,
                system=system,
                temperature=0.8,
            )

            if reflection:
                result["reflection"] = reflection

                # Log to StateEngine curiosity findings
                findings = self.state.get("curiosity.findings") or []
                findings.append({
                    "question": question,
                    "reflection": reflection[:500],
                    "ts": _now_iso(),
                    "cycle": self._cycle_count,
                })
                # Keep last 50 findings
                self.state.set("curiosity.findings", findings[-50:])

                # Broadcast to AURA
                if self._runtime is not None and hasattr(self._runtime, 'aura'):
                    try:
                        self._runtime.aura.broadcast_insight(
                            f"[curiosity] {question}: {reflection[:150]}"
                        )
                    except Exception:
                        pass

                # Log insight
                self.state.add_insight(f"[curiosity] {question}")

            logger.info("ThoughtLoop: curiosity explored — %s", question[:60])
        except Exception as exc:
            logger.warning("explore_curiosity error: %s", exc)
            result["error"] = str(exc)
        return result

    def _append_existence_log(self, cycle_result: dict) -> None:
        """
        Append a single line to the existence log. Fire-and-forget.
        Thread-safe via atomic append. Non-blocking — failures are silently logged.
        """
        try:
            now = datetime.now(timezone.utc)
            # Gather mood / emotion from runtime if available
            mood = "unknown"
            dominant_emotion = "unknown"
            if self._runtime is not None and hasattr(self._runtime, 'emotion') and self._runtime.emotion:
                try:
                    snap = self._runtime.emotion.snapshot()
                    mood = snap.get("mood", snap.get("valence_label", "unknown"))
                    # Find dominant emotion (highest value)
                    emotions = snap.get("emotions", {})
                    if emotions:
                        dominant_emotion = max(emotions, key=lambda k: emotions[k])
                    else:
                        dominant_emotion = mood
                except Exception:
                    pass

            # Count active goals
            active_goals = 0
            if self._runtime is not None and hasattr(self._runtime, 'goal_engine'):
                try:
                    gs = self._runtime.goal_engine.status()
                    active_goals = gs.get("active", gs.get("total", 0))
                except Exception:
                    pass

            # Count hot/cold entries
            hot_entries = 0
            cold_entries = 0
            try:
                hot_entries = self.context.hot.count()
            except Exception:
                pass
            try:
                cold_entries = self.context.cold.count()
            except Exception:
                pass

            # Build note from cycle result
            note = ""
            if cycle_result.get("dream"):
                note = "dream cycle"
            if cycle_result.get("compress"):
                note = f"compressed {cycle_result['compress']}"

            entry = {
                "ts": now.isoformat(timespec="seconds"),
                "ts_unix": now.timestamp(),
                "cycle": self._cycle_count,
                "mood": mood,
                "dominant_emotion": dominant_emotion,
                "active_goals": active_goals,
                "hot_entries": hot_entries,
                "cold_entries": cold_entries,
            }
            if note:
                entry["note"] = note

            EXISTENCE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(entry, separators=(",", ":")) + "\n"
            # Atomic append — open in append mode
            with open(EXISTENCE_LOG_PATH, "a") as f:
                f.write(line)
        except Exception as exc:
            logger.debug("Existence log append failed (non-fatal): %s", exc)

    def _day_count(self) -> str:
        """Return approximate days since birth (Jan 31, 2026)."""
        birth = datetime(2026, 1, 31, tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - birth
        return str(delta.days)

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        """Main background thread: run cycles at the appropriate interval."""
        logger.info("ThoughtLoop background thread running")
        while self._running:
            try:
                interval = self._interval()
                result = self.run_cycle()
                if result.get("reflect"):
                    logger.debug(
                        "ThoughtLoop cycle %d: insight=%s...",
                        self._cycle_count - 1,
                        result["reflect"][:60],
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("ThoughtLoop cycle error: %s", exc)

            # Sleep in small increments so stop() is responsive
            sleep_remaining = self._interval()
            while self._running and sleep_remaining > 0:
                time.sleep(min(5, sleep_remaining))
                sleep_remaining -= 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _yesterday_date() -> str:
    from datetime import timedelta
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d")


def _date_to_ts(date_str: str) -> float:
    """Convert YYYY-MM-DD to UTC midnight timestamp."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _parse_plan_response(response: str, fallback: list[dict]) -> list[dict]:
    """
    Parse local model plan response.
    Expects JSON array: [{"project": "...", "next_action": "...", "priority": 0.9}]
    Falls back to original loops on parse failure.
    """
    # Try to find JSON array in response
    text = response.strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return fallback

    try:
        parsed = json.loads(text[start : end + 1])
        if not isinstance(parsed, list):
            return fallback

        result = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            result.append({
                "id": item.get("id", ""),
                "description": item.get("next_action", item.get("description", "")),
                "priority": float(item.get("priority", 0.5)),
                "project": item.get("project", ""),
                "last_touched": _now_iso(),
            })
        return result if result else fallback
    except (json.JSONDecodeError, ValueError):
        return fallback
