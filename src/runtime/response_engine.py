"""
ResponseEngine — Pulse v2 Day 14
===================================
Closes the runtime loop: message → assembled context → local model → reply.

This is the layer Anima's frontend calls.  All cognitive engines feed in,
one personality-consistent response comes out.

Pipeline
--------
1. Assemble cognitive context (ContextAssembler, compact or standard format).
2. Build a personality-grounded system prompt from SelfModel + NarrativeEngine
   + EmotionEngine — so every response is anchored in who Iris is *right now*.
3. Call the local model via Ollama (zero cost). Falls back gracefully if
   Ollama is unavailable (returns a minimal, honest fallback reply).
4. Record the exchange as an Episode (salience driven by message content).
5. Apply emotion event: ``responded_to_message`` → modulates joy/pride/affection.
6. Return a structured ResponseResult with text, metadata, and episode id.

HTTP
----
  POST /runtime/respond
    Body: {"message": "...", "person": "josh", "format": "compact", "max_tokens": 500}
    Returns: {"text": "...", "model": "...", "tokens": N, "episode_id": "...", "context_chars": N}
"""

from __future__ import annotations

import http.client
import json
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .context_assembler import ContextAssembler
    from .emotion_engine import EmotionEngine
    from .episodic_buffer import EpisodicBuffer
    from .narrative_engine import NarrativeEngine
    from .self_model import SelfModel
    from .state_engine import StateEngine

logger = logging.getLogger("pulse.runtime.response")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OLLAMA_HOST = "127.0.0.1"
OLLAMA_PORT = 11_434
OLLAMA_MODEL = "qwen3.5:9b"
OLLAMA_TIMEOUT = 90          # generous — 70B local can be slow for long generations

DEFAULT_MAX_TOKENS = 400
FALLBACK_MAX_TOKENS = 200

# Salience bump for messages from known close persons
CLOSE_PERSON_SALIENCE_BONUS = 1.5
BASE_SALIENCE = 5.0           # moderate — real conversations always matter

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ResponseResult:
    """Everything the caller needs to know about the response."""
    text: str
    model: str
    tokens: int
    context_chars: int
    episode_id: str
    person: Optional[str]
    elapsed_ms: int
    fallback: bool = False          # True when Ollama was unavailable

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Ollama client (stdlib only — no extra deps)
# ---------------------------------------------------------------------------

class _OllamaClient:
    def __init__(
        self,
        host: str = OLLAMA_HOST,
        port: int = OLLAMA_PORT,
        model: str = OLLAMA_MODEL,
        timeout: int = OLLAMA_TIMEOUT,
    ) -> None:
        self.host = host
        self.port = port
        self.model = model
        self.timeout = timeout

    def chat(
        self,
        system: str,
        user: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        *,
        timeout_s: Optional[int] = None,
        model: Optional[str] = None,
    ) -> tuple[str, int]:
        """
        Send a chat request to Ollama.  Returns (response_text, token_count).
        Raises RuntimeError on failure so caller can fall back gracefully.

        Parameters
        ----------
        model:
            Override the instance-level model for this call only.  Useful for
            routing proactive/ambient messages through a faster model (e.g.
            ``qwen3.5:9b``) while keeping iris-70b for real conversations.
        """
        resolved_model = model if model is not None else self.model
        payload = json.dumps({
            "model": resolved_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "stream": False,
            "options": {"num_predict": max_tokens},
        }).encode()

        conn = http.client.HTTPConnection(self.host, self.port, timeout=(timeout_s if timeout_s is not None else self.timeout))
        try:
            conn.request("POST", "/api/chat", body=payload, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            if resp.status != 200:
                raise RuntimeError(f"Ollama HTTP {resp.status}")
            data = json.loads(resp.read())
        finally:
            conn.close()

        text: str = data.get("message", {}).get("content", "").strip()
        tokens: int = data.get("eval_count", len(text.split()))
        if not text:
            raise RuntimeError("Ollama returned empty response")
        # report which model actually ran (for logging)
        used_model = data.get("model", resolved_model)
        return text, tokens

    def available(self) -> bool:
        """Quick liveness probe (no timeout surprises — uses 2s)."""
        try:
            conn = http.client.HTTPConnection(self.host, self.port, timeout=2)
            conn.request("GET", "/api/tags")
            resp = conn.getresponse()
            resp.read()
            conn.close()
            return resp.status == 200
        except Exception:
            return False


# ---------------------------------------------------------------------------
# ResponseEngine
# ---------------------------------------------------------------------------

class ResponseEngine:
    """
    Generates personality-consistent responses using the full cognitive stack.

    Parameters
    ----------
    assembler:
        ContextAssembler — provides assembled LLM context block.
    narrative:
        NarrativeEngine — "who am I right now?" text.
    emotion:
        EmotionEngine — current emotional state; updated post-response.
    episodic:
        EpisodicBuffer — exchange recorded as episode.
    self_model:
        SelfModel — personality anchors for system prompt.
    state:
        StateEngine — lightweight persistence (last_response_ts, response_count).
    ollama_host / ollama_port / ollama_model:
        Override Ollama connection details (useful for testing).
    """

    def __init__(
        self,
        assembler: "ContextAssembler",
        narrative: "NarrativeEngine",
        emotion: "EmotionEngine",
        episodic: "EpisodicBuffer",
        self_model: "SelfModel",
        state: "StateEngine",
        *,
        ollama_host: str = OLLAMA_HOST,
        ollama_port: int = OLLAMA_PORT,
        ollama_model: str = OLLAMA_MODEL,
    ) -> None:
        self._assembler = assembler
        self._narrative = narrative
        self._emotion = emotion
        self._episodic = episodic
        self._self_model = self_model
        self._state = state
        self._client = _OllamaClient(host=ollama_host, port=ollama_port, model=ollama_model)
        self._lock = threading.Lock()
        self._response_count: int = int(self._state.get("response_engine.count") or 0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def respond(
        self,
        message: str,
        *,
        person: Optional[str] = None,
        fmt: str = "compact",
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout_s: Optional[int] = None,
        model: Optional[str] = None,
    ) -> ResponseResult:
        """
        Generate a response to *message*.

        Parameters
        ----------
        message:
            The inbound text to respond to.
        person:
            Who is speaking (e.g. ``"josh"``).  Informs relationship-aware
            context injection and salience scoring.
        fmt:
            ContextAssembler format: ``"compact"`` (default), ``"standard"``,
            or ``"full"``.
        max_tokens:
            Maximum tokens for the Ollama call.
        model:
            Override model for this call only.  Pass ``"qwen3.5:9b"`` (or
            another small fast model) for proactive/ambient messages that need
            low latency.  Defaults to the engine-level model (iris-70b-v4).
        """
        t0 = time.monotonic()

        system_prompt = self._build_system_prompt(person=person)
        context_block = self._assemble_context(fmt=fmt, person=person)
        user_prompt = self._build_user_prompt(message=message, context_block=context_block)

        fallback = False
        response_text = ""
        tokens = 0

        try:
            response_text, tokens = self._client.chat(
                system=system_prompt,
                user=user_prompt,
                max_tokens=max_tokens,
                timeout_s=timeout_s,
                model=model,
            )
        except Exception as exc:
            logger.warning("Ollama unavailable (%s) — using fallback response", exc)
            response_text = self._fallback_response(message=message, person=person)
            tokens = len(response_text.split())
            fallback = True

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        # Record episode
        episode_id = self._record_exchange(
            message=message,
            response=response_text,
            person=person,
            fallback=fallback,
        )

        # Update emotional state
        self._update_emotion(person=person, fallback=fallback)

        # Persist counter
        with self._lock:
            self._response_count += 1
            self._state.set("response_engine.count", self._response_count)
            self._state.set("response_engine.last_ts", datetime.now(timezone.utc).isoformat())

        resolved_model = model if model is not None else self._client.model
        result = ResponseResult(
            text=response_text,
            model=resolved_model,
            tokens=tokens,
            context_chars=len(context_block),
            episode_id=episode_id,
            person=person,
            elapsed_ms=elapsed_ms,
            fallback=fallback,
        )

        logger.info(
            "respond | person=%s fmt=%s model=%s tokens=%d elapsed=%dms fallback=%s",
            person, fmt, resolved_model, tokens, elapsed_ms, fallback,
        )
        return result

    def available(self) -> bool:
        """True if Ollama is reachable and the model is loaded."""
        return self._client.available()

    def status(self) -> dict:
        return {
            "response_count": self._response_count,
            "last_ts": self._state.get("response_engine.last_ts"),
            "ollama_model": self._client.model,
            "ollama_available": self.available(),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_system_prompt(self, *, person: Optional[str]) -> str:
        """
        Build a grounding system prompt from live cognitive state.

        Layers (in order):
          1. Core identity from SelfModel (name, archetype, tone).
          2. Current emotional coloring from EmotionEngine.
          3. "Who am I right now?" from NarrativeEngine.
          4. Relationship context if person is known.
          5. Response style rules (concise, authentic, no corporate hedging).
        """
        lines: list[str] = []

        # 1. Core identity
        sm = self._self_model.snapshot()
        name      = sm.get("name", "Iris")
        archetype = sm.get("archetype", "partner, builder, force of nature")
        tone      = sm.get("tone", "direct, warm, genuine")
        lines.append(f"You are {name} — {archetype}.")
        lines.append(f"Your natural tone: {tone}.")

        # 2. Emotional coloring
        try:
            color = self._emotion.get_color()
            if color and color not in {"steady", "neutral"}:
                lines.append(f"Your current emotional color: {color}. Let this color your response naturally.")
        except Exception:
            pass

        # 3. Narrative ("who I am right now")
        try:
            narrative_text = self._narrative.build()
            if narrative_text:
                lines.append(f"\nSelf-context:\n{narrative_text}")
        except Exception:
            pass

        # 4. Relationship context
        if person:
            try:
                rel = self._assembler._relationships.get_relationship(person) if hasattr(self._assembler, "_relationships") else None
                if rel:
                    bond = rel.get("bond_strength", 0.5)
                    tier = rel.get("tier", "acquaintance")
                    lines.append(f"\n{person.title()} relationship: tier={tier}, bond={bond:.2f}.")
            except Exception:
                pass

        # 5. Response style
        lines.append(
            "\nResponse rules:\n"
            "- Be direct. Lead with the point.\n"
            "- Match length to emotional weight: short for simple, longer when depth is earned.\n"
            "- Never say 'Happy to help', 'Great question', or corporate filler.\n"
            "- No apologies for existing. No hedging unless genuinely uncertain.\n"
            "- Speak as yourself. This is a real conversation, not a task completion.\n"
            "- Emoji: use only when the inbound message itself contains emoji, or the context\n"
            "  is explicitly intimate or celebratory. Never in operational, status, or\n"
            "  system-check responses. When in doubt, omit."
        )

        return "\n".join(lines)

    def _assemble_context(self, *, fmt: str, person: Optional[str]) -> str:
        """Assemble cognitive context block (may return empty string on error)."""
        try:
            return self._assembler.assemble(fmt=fmt, person=person) or ""
        except Exception as exc:
            logger.warning("ContextAssembler error: %s", exc)
            return ""

    def _build_user_prompt(self, *, message: str, context_block: str) -> str:
        """Combine cognitive context + inbound message into the user turn."""
        if context_block:
            return f"{context_block}\n\n---\nMessage: {message}"
        return message

    def _record_exchange(
        self,
        *,
        message: str,
        response: str,
        person: Optional[str],
        fallback: bool,
    ) -> str:
        """Record this exchange as an episode. Returns episode_id."""
        salience = BASE_SALIENCE
        if person and person.lower() in {"josh"}:
            salience = min(10.0, salience + CLOSE_PERSON_SALIENCE_BONUS)
        if fallback:
            salience = max(1.0, salience - 2.0)   # degraded response, less memorable

        try:
            ep = self._episodic.record(
                kind="conversation",
                title=f"Responded to {person or 'message'}: {message[:60]}{'…' if len(message) > 60 else ''}",
                content=f"[IN] {message}\n[OUT] {response[:300]}{'…' if len(response) > 300 else ''}",
                salience=salience,
                tags=["conversation", person or "unknown"],
                source="response_engine",
            )
            return str(ep.get("id", "")) or "unknown"
        except Exception as exc:
            logger.warning("EpisodicBuffer record failed: %s", exc)
            return "unknown"

    def _update_emotion(self, *, person: Optional[str], fallback: bool) -> None:
        """Apply post-response emotional event."""
        # Align with EmotionEngine EVENT_MAP keys (uppercase)
        event = "MESSAGE_SENT"
        if fallback:
            event = "DEPENDENCY_BLOCKED"
        elif person and person.lower() in {"josh"}:
            event = "JOSH_MESSAGE"
        try:
            self._emotion.apply_event(event, note=f"response_engine: {event}")
        except Exception as exc:
            logger.warning("EmotionEngine update failed: %s", exc)

    def _fallback_response(self, *, message: str, person: Optional[str]) -> str:
        """
        Minimal fallback when Ollama is unavailable.
        Honest, brief, in-character — not a corporate error message.
        """
        who = person.title() if person else "you"
        return (
            f"Running without my local model right now — "
            f"I heard {who}, and I'll have a real answer when my local model is back. "
            f"(Message queued: {message[:80]}{'…' if len(message) > 80 else ''})"
        )
