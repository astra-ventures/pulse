"""
Guardrails — hard limits on self-modification.

The agent can evolve, but it can't:
- Disable its own safety checks
- Remove rate limiting
- Set infinite trigger rates
- Delete its own audit trail
- Modify guardrails themselves

Think of this as the brainstem — the agent can rewire its cortex,
but it can't stop its own heart.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Set

logger = logging.getLogger("pulse.evolution.guardrails")


@dataclass
class GuardrailLimits:
    """Hard limits that self-modification cannot exceed."""

    # Drive weights: min/max range
    min_drive_weight: float = 0.05  # can't zero out a drive
    max_drive_weight: float = 3.0   # can't make one drive dominate everything

    # Pressure rates
    min_pressure_rate: float = 0.001
    max_pressure_rate: float = 0.1

    # Trigger thresholds
    min_trigger_threshold: float = 0.2   # can't trigger on every tick
    max_trigger_threshold: float = 0.95  # can't make itself unreachable

    # Rate limits (turns per hour)
    min_turns_per_hour: int = 1
    max_turns_per_hour: int = 30

    # Cooldown (seconds)
    min_cooldown: int = 60      # at least 1 minute between triggers
    max_cooldown: int = 3600    # at most 1 hour

    # Max change per mutation (prevents drastic shifts)
    max_weight_delta: float = 0.5      # can't change a weight by more than 0.5 at once
    max_threshold_delta: float = 0.15  # can't shift threshold by more than 0.15 at once
    max_rate_delta: float = 0.02       # pressure rate changes capped

    # Protected drives (cannot be removed)
    protected_drives: Set[str] = field(default_factory=lambda: {"goals", "growth"})

    # Max drives (prevent unbounded growth)
    max_drives: int = 15

    # Max mutations per hour (prevent runaway self-modification)
    max_mutations_per_hour: int = 10


class GuardrailViolation(Exception):
    """Raised when a mutation violates guardrails."""
    pass


class Guardrails:
    """Validates mutations against hard limits."""

    def __init__(self, limits: Optional[GuardrailLimits] = None, state=None):
        self.limits = limits or GuardrailLimits()
        self._state = state  # StatePersistence reference
        self._mutation_timestamps: list = self._load_timestamps()

    def _load_timestamps(self) -> list:
        """Restore mutation timestamps from persisted state."""
        if self._state:
            import time
            saved = self._state.get("guardrail_mutation_timestamps", [])
            now = time.time()
            return [t for t in saved if now - t < 3600]
        return []

    def _save_timestamps(self):
        """Persist mutation timestamps to state."""
        if self._state:
            self._state.set("guardrail_mutation_timestamps", self._mutation_timestamps)

    def validate_weight_change(
        self, drive_name: str, current: float, proposed: float
    ) -> float:
        """Validate and clamp a drive weight change."""
        delta = abs(proposed - current)
        if delta > self.limits.max_weight_delta:
            clamped = current + (self.limits.max_weight_delta * (1 if proposed > current else -1))
            logger.warning(
                f"Weight delta {delta:.2f} exceeds max {self.limits.max_weight_delta}. "
                f"Clamped {drive_name}: {proposed:.2f} → {clamped:.2f}"
            )
            proposed = clamped

        proposed = max(self.limits.min_drive_weight, min(self.limits.max_drive_weight, proposed))
        return round(proposed, 4)

    def validate_threshold_change(self, current: float, proposed: float) -> float:
        """Validate and clamp a trigger threshold change."""
        delta = abs(proposed - current)
        if delta > self.limits.max_threshold_delta:
            clamped = current + (self.limits.max_threshold_delta * (1 if proposed > current else -1))
            logger.warning(
                f"Threshold delta {delta:.2f} exceeds max. Clamped: {proposed:.2f} → {clamped:.2f}"
            )
            proposed = clamped

        proposed = max(self.limits.min_trigger_threshold, min(self.limits.max_trigger_threshold, proposed))
        return round(proposed, 4)

    def validate_rate_change(self, current: float, proposed: float) -> float:
        """Validate pressure rate change."""
        delta = abs(proposed - current)
        if delta > self.limits.max_rate_delta:
            clamped = current + (self.limits.max_rate_delta * (1 if proposed > current else -1))
            proposed = clamped

        proposed = max(self.limits.min_pressure_rate, min(self.limits.max_pressure_rate, proposed))
        return round(proposed, 6)

    def validate_drive_removal(self, drive_name: str):
        """Check if a drive can be removed."""
        if drive_name in self.limits.protected_drives:
            raise GuardrailViolation(
                f"Cannot remove protected drive '{drive_name}'. "
                f"Protected drives: {self.limits.protected_drives}"
            )

    def validate_drive_count(self, current_count: int):
        """Check if we can add another drive."""
        if current_count >= self.limits.max_drives:
            raise GuardrailViolation(
                f"Cannot add drive: at limit ({current_count}/{self.limits.max_drives})"
            )

    def validate_turns_per_hour(self, proposed: int) -> int:
        """Validate turns per hour change."""
        return max(self.limits.min_turns_per_hour, min(self.limits.max_turns_per_hour, proposed))

    def validate_cooldown(self, proposed: int) -> int:
        """Validate cooldown change."""
        return max(self.limits.min_cooldown, min(self.limits.max_cooldown, proposed))

    def check_mutation_rate(self):
        """Ensure we're not mutating too fast."""
        import time
        now = time.time()
        one_hour_ago = now - 3600
        self._mutation_timestamps = [t for t in self._mutation_timestamps if t > one_hour_ago]

        if len(self._mutation_timestamps) >= self.limits.max_mutations_per_hour:
            raise GuardrailViolation(
                f"Mutation rate limit: {len(self._mutation_timestamps)}"
                f"/{self.limits.max_mutations_per_hour} per hour"
            )

        self._mutation_timestamps.append(now)
        self._save_timestamps()
