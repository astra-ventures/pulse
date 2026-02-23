"""
Model-Based Evaluator — Phase 3.

Instead of threshold math, an LLM reasons about whether the agent
should think right now. This is a GATE — a tiny, fast model call
that decides "yes/no/why" before we spend a full agent turn.

Supports any OpenAI-compatible API:
- Anthropic (via proxy or direct)
- Ollama (local, free, no API key)
- OpenAI, Together, Groq, etc.

The evaluator prompt includes:
- Current drive states (what wants attention)
- Sensor readings (what changed in the world)
- Recent trigger history (what worked, what didn't)
- Time context (how long since last turn, time of day)
- Working memory snapshot (what the agent was last thinking about)

The model returns a structured decision, not free-form text.
"""

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

from pulse.src.core.config import PulseConfig
from pulse.src.drives.engine import Drive, DriveState
from pulse.src.evaluator.priority import TriggerDecision

logger = logging.getLogger("pulse.evaluator.model")


@dataclass
class ModelConfig:
    """Configuration for the evaluation model."""
    base_url: str = "http://127.0.0.1:11434/v1"  # ollama default
    api_key: str = "ollama"  # ollama doesn't need a real key
    model: str = "llama3.2:3b"  # small, fast, good enough for gate decisions
    max_tokens: int = 512
    temperature: float = 0.3  # low temp = consistent decisions
    timeout_seconds: int = 10


EVALUATOR_SYSTEM_PROMPT = """\
You are the priority evaluator for an autonomous AI agent named Iris.
Your ONLY job is to decide: should the agent wake up and think right now?

You will receive:
- Drive states (internal motivations with pressure levels 0.0-5.0)
- Sensor readings (what changed in the environment)
- Recent trigger history (past decisions and outcomes)
- Time context
- Working memory (what the agent was last focused on)

Respond with ONLY valid JSON (no markdown, no explanation):
{
  "trigger": true/false,
  "reason": "brief explanation (1 sentence)",
  "urgency": 0.0-1.0,
  "suggested_focus": "what the agent should focus on if triggered",
  "suppress_minutes": 0
}

HARD RULES (override everything else):
1. If "Human conversation ACTIVE" appears in sensors → trigger=false, suppress_minutes=10. ALWAYS. No exceptions.
2. If "Human conversation cooldown" appears → trigger=false, suppress_minutes=5.
3. If the last trigger was less than 15 minutes ago AND no new sensor changes → trigger=false, suppress_minutes=10.
4. If you triggered for the same suggested_focus in the last 3 history entries → trigger=false, suppress_minutes=15. Do NOT repeat the same focus.
5. NEVER suggest a focus on completed tasks. If working memory or goals mention something is "COMPLETE" or "done" or "perfect score", skip it entirely.

Decision guidelines (only apply after hard rules pass):
- trigger=true ONLY when there is a SPECIFIC, ACTIONABLE task the agent can do RIGHT NOW
- trigger=false is the DEFAULT. When in doubt, don't trigger.
- EXCEPTION: If total pressure exceeds 10.0 AND the highest individual drive exceeds 1.5 AND last trigger was more than 30 minutes ago, trigger=true with suggested_focus from working memory or highest-pressure drive. High pressure means the agent has been genuinely idle too long — not just ambient floor accumulation.
- Below pressure 10.0, "pressure accumulated" alone is NOT sufficient — you must name a concrete action
- urgency reflects how soon this needs attention (1.0 = NOW, 0.5 = soon, 0.1 = whenever)
- suppress_minutes: when not triggering, suggest 10-30 minutes to avoid rapid re-evaluation
- Sensor changes (new files, system alerts) are the strongest trigger signals
- Pure time passage with no new information = suppress, don't trigger
- Overnight (11 PM - 7 AM): only trigger for genuine autonomous work opportunities, not routine checks
"""


class ModelEvaluator:
    """LLM-powered evaluation gate."""

    def __init__(self, config: PulseConfig, model_config: Optional[ModelConfig] = None):
        self.config = config
        self.model_config = model_config or ModelConfig()
        self._session: Optional[aiohttp.ClientSession] = None
        self._trigger_history: List[dict] = []
        self._max_history = 20
        self._consecutive_failures = 0
        self._max_consecutive_failures = 3  # fall back to rules after this many
        self._last_failure_time: float = 0.0
        self._model_retry_interval: float = 300.0  # retry model every 5 min after degradation
        self._suppress_until: float = 0.0  # suppress evaluation until this timestamp

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def evaluate(
        self,
        drive_state: DriveState,
        sensor_data: dict,
        working_memory: Optional[dict] = None,
    ) -> TriggerDecision:
        """Async evaluation — called from the daemon's async loop."""
        return await self._evaluate_async(drive_state, sensor_data, working_memory)

    async def _evaluate_async(
        self,
        drive_state: DriveState,
        sensor_data: dict,
        working_memory: Optional[dict] = None,
    ) -> TriggerDecision:
        """Call the model and parse its decision."""
        now = time.time()

        # Honor suppress_minutes from previous model response
        if now < self._suppress_until:
            return TriggerDecision(
                should_trigger=False,
                reason=f"model_suppressed (until {int(self._suppress_until - now)}s)",
                total_pressure=drive_state.total_pressure,
                top_drive=drive_state.top_drive,
            )

        # Auto-recover: periodically retry model after degradation
        use_model = True
        if self._consecutive_failures >= self._max_consecutive_failures:
            if now - self._last_failure_time < self._model_retry_interval:
                use_model = False
            else:
                logger.info("Retrying model evaluator after cooldown...")

        if not use_model:
            return self._fallback_evaluate(drive_state, sensor_data)

        # Build the context message
        user_prompt = self._build_prompt(drive_state, sensor_data, working_memory)

        try:
            session = await self._get_session()
            response = await self._call_model(session, user_prompt)
            decision = self._parse_response(response, drive_state)
            if self._consecutive_failures > 0:
                logger.info("Model evaluator recovered!")
            self._consecutive_failures = 0

            # Handle suppress_minutes from model response
            max_suppress = self.config.evaluator.model.max_suppress_minutes
            suppress_min = min(self._extract_suppress_minutes(response), max_suppress)
            if suppress_min > 0 and not decision.should_trigger:
                self._suppress_until = now + (suppress_min * 60)
                logger.debug(f"Model requested suppress={suppress_min}min (cap={max_suppress})")

            return decision

        except Exception as e:
            self._consecutive_failures += 1
            self._last_failure_time = now
            logger.warning(
                f"Model evaluator failed ({self._consecutive_failures}/"
                f"{self._max_consecutive_failures}): {e}"
            )

            # Fall back to threshold-based decision
            return self._fallback_evaluate(drive_state, sensor_data)

    def _extract_suppress_minutes(self, response: str) -> int:
        """Extract suppress_minutes from a model response."""
        try:
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()
            data = json.loads(cleaned)
            return int(data.get("suppress_minutes", 0))
        except Exception:
            return 0

    async def _call_model(self, session: aiohttp.ClientSession, user_prompt: str) -> str:
        """Make the API call to the model."""
        url = f"{self.model_config.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.model_config.api_key}",
        }

        payload = {
            "model": self.model_config.model,
            "messages": [
                {"role": "system", "content": EVALUATOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": self.model_config.max_tokens,
            "temperature": self.model_config.temperature,
        }

        async with session.post(
            url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=self.model_config.timeout_seconds),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Model API returned {resp.status}: {body[:200]}")

            data = await resp.json()
            content = data["choices"][0]["message"]["content"]
            return content

    def _build_prompt(
        self,
        drive_state: DriveState,
        sensor_data: dict,
        working_memory: Optional[dict] = None,
    ) -> str:
        """Build the evaluation prompt from current state."""
        now = time.time()
        parts = []

        # Time context
        from datetime import datetime
        dt = datetime.now()
        parts.append(f"## Time Context")
        parts.append(f"Current time: {dt.strftime('%A, %B %d, %Y — %I:%M %p')}")
        parts.append(f"")

        # Drive states
        parts.append("## Drive States")
        for drive in sorted(drive_state.drives, key=lambda d: d.weighted_pressure, reverse=True):
            bar = "█" * int(drive.pressure * 10) + "░" * (10 - int(drive.pressure * 10))
            last = ""
            if drive.last_addressed:
                ago = round((now - drive.last_addressed) / 60)
                last = f" (last addressed {ago}m ago)"
            parts.append(
                f"- {drive.name}: [{bar}] {drive.pressure:.2f} "
                f"(weight: {drive.weight}){last}"
            )
        parts.append(f"- **Combined pressure: {drive_state.total_pressure:.2f}**")
        parts.append("")

        # Sensor readings
        parts.append("## Sensor Readings")

        fs = sensor_data.get("filesystem", {})
        changes = fs.get("changes", [])
        if changes:
            parts.append(f"File changes ({len(changes)}):")
            for c in changes[:10]:  # cap at 10
                parts.append(f"  - {c['type']}: {c['path']}")
            if len(changes) > 10:
                parts.append(f"  - ... and {len(changes) - 10} more")
        else:
            parts.append("File changes: none")

        convo = sensor_data.get("conversation", {})
        if convo.get("active"):
            parts.append(f"⚠️ Human conversation ACTIVE (last activity {convo.get('seconds_since', '?')}s ago)")
        elif convo.get("in_cooldown"):
            parts.append(f"Human conversation cooldown ({convo.get('seconds_since', '?')}s since last activity)")
        else:
            parts.append("Human conversation: inactive")

        system = sensor_data.get("system", {})
        alerts = system.get("alerts", [])
        if alerts:
            parts.append(f"System alerts: {json.dumps(alerts)}")
        else:
            parts.append("System alerts: none")
        parts.append("")

        # Recent trigger history
        if self._trigger_history:
            parts.append("## Recent Trigger History (last 5)")
            for entry in self._trigger_history[-5:]:
                ago = round((now - entry["timestamp"]) / 60)
                status = "✅" if entry["success"] else "❌"
                parts.append(
                    f"- {ago}m ago: {status} {entry['reason']} "
                    f"(pressure: {entry['pressure']:.2f})"
                )
            parts.append("")

        # Working memory
        if working_memory:
            parts.append("## Working Memory (agent's last known state)")
            # Truncate to keep prompt small
            wm_str = json.dumps(working_memory, indent=2, default=str)
            if len(wm_str) > 500:
                wm_str = wm_str[:500] + "\n... (truncated)"
            parts.append(wm_str)
            parts.append("")

        return "\n".join(parts)

    def _parse_response(self, response: str, drive_state: DriveState) -> TriggerDecision:
        """Parse the model's JSON response into a TriggerDecision."""
        # Strip markdown fences if present
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.warning(f"Model returned invalid JSON: {response[:200]}")
            raise ValueError(f"Invalid JSON from model: {e}")

        should_trigger = bool(data.get("trigger", False))
        reason = data.get("reason", "model decision")
        urgency = float(data.get("urgency", 0.5))

        # Enrich reason with model's suggested focus
        focus = data.get("suggested_focus", "")
        if focus and should_trigger:
            reason = f"{reason} → Focus: {focus}"

        # Recommend GENERATE when model says don't trigger but pressure is high
        # This means drives want attention but there's nothing actionable
        recommend_generate = (
            not should_trigger
            and drive_state.total_pressure >= self.config.drives.trigger_threshold
        )

        return TriggerDecision(
            should_trigger=should_trigger,
            reason=f"model: {reason}",
            total_pressure=drive_state.total_pressure,
            top_drive=drive_state.top_drive,
            sensor_context=focus,
            recommend_generate=recommend_generate,
        )

    def _fallback_evaluate(
        self, drive_state: DriveState, sensor_data: dict
    ) -> TriggerDecision:
        """Rules-based fallback when model is unavailable."""
        rules = self.config.evaluator.rules

        if self._consecutive_failures >= self._max_consecutive_failures:
            logger.warning("Model evaluator degraded — using rules fallback")

        # Same logic as PriorityEvaluator.evaluate()
        if drive_state.top_drive:
            if drive_state.top_drive.weighted_pressure >= rules.single_drive_threshold:
                return TriggerDecision(
                    should_trigger=True,
                    reason=f"fallback_rules: {drive_state.top_drive.name} above threshold",
                    total_pressure=drive_state.total_pressure,
                    top_drive=drive_state.top_drive,
                )

        if drive_state.total_pressure >= rules.combined_threshold:
            return TriggerDecision(
                should_trigger=True,
                reason="fallback_rules: combined threshold",
                total_pressure=drive_state.total_pressure,
                top_drive=drive_state.top_drive,
            )

        recommend = drive_state.total_pressure >= self.config.drives.trigger_threshold
        return TriggerDecision(
            should_trigger=False,
            reason="fallback_rules: below threshold",
            total_pressure=drive_state.total_pressure,
            top_drive=drive_state.top_drive,
            recommend_generate=recommend,
        )

    def record_trigger(self, decision: TriggerDecision, success: bool):
        """Record a trigger for history context in future evaluations."""
        self._trigger_history.append({
            "timestamp": time.time(),
            "reason": decision.reason,
            "pressure": decision.total_pressure,
            "success": success,
        })
        # Trim history
        if len(self._trigger_history) > self._max_history:
            self._trigger_history = self._trigger_history[-self._max_history:]

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
