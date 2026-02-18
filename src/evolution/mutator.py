"""
Mutator — the self-modification interface.

This is how the agent evolves Pulse from within. The agent writes
mutation commands to a file, and Pulse applies them on the next cycle.

Mutation commands are JSON objects in a "mutations queue" file:

    ~/.pulse/mutations.json

Example:
[
    {
        "type": "adjust_weight",
        "drive": "curiosity",
        "value": 0.8,
        "reason": "I've been neglecting exploration — boosting curiosity drive"
    },
    {
        "type": "add_drive",
        "name": "writing",
        "weight": 0.7,
        "reason": "I want to write more on iamiris.ai — adding a dedicated drive"
    }
]

Supported mutation types:
- adjust_weight: Change a drive's weight
- adjust_threshold: Change trigger threshold
- adjust_rate: Change pressure accumulation rate
- adjust_cooldown: Change min trigger interval
- adjust_turns_per_hour: Change rate limit
- add_drive: Create a new drive
- remove_drive: Remove a non-protected drive
- spike_drive: Manually spike a drive's pressure
- decay_drive: Manually decay a drive's pressure
"""

import fcntl
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING

from pulse.src.evolution.guardrails import Guardrails, GuardrailViolation
from pulse.src.evolution.audit import AuditLog, MutationRecord

if TYPE_CHECKING:
    from pulse.src.core.config import PulseConfig
    from pulse.src.drives.engine import DriveEngine, Drive

logger = logging.getLogger("pulse.evolution.mutator")


class Mutator:
    """Processes self-modification commands from the agent."""

    def __init__(
        self,
        config: "PulseConfig",
        drives: "DriveEngine",
        guardrails: Optional[Guardrails] = None,
        state=None,
    ):
        self.config = config
        self.drives = drives
        self.guardrails = guardrails or Guardrails(state=state)

        state_dir = Path(config.state.dir).expanduser()
        state_dir.mkdir(parents=True, exist_ok=True)
        self.audit = AuditLog(state_dir)

        self.queue_file = state_dir / "mutations.json"

    def process_queue(self) -> List[dict]:
        """
        Check for pending mutations and apply them.
        Called every daemon loop iteration.

        Returns list of applied mutation results.
        """
        if not self.queue_file.exists():
            return []

        try:
            with open(self.queue_file, "r+") as f:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                try:
                    raw = f.read().strip()
                    if not raw or raw == "[]":
                        return []
                    mutations = json.loads(raw)
                    if not isinstance(mutations, list):
                        mutations = [mutations]
                    # Clear queue while holding lock
                    f.seek(0)
                    f.write("[]")
                    f.truncate()
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except BlockingIOError:
            logger.debug("Mutation queue locked by another process, skipping")
            return []
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Invalid mutation queue: {e}")
            return []

        results = []
        for mutation in mutations:
            try:
                result = self._apply_mutation(mutation)
                results.append(result)
            except GuardrailViolation as e:
                logger.warning(f"Mutation blocked by guardrails: {e}")
                results.append({
                    "status": "blocked",
                    "type": mutation.get("type"),
                    "error": str(e),
                })
            except Exception as e:
                logger.error(f"Mutation failed: {e}")
                results.append({
                    "status": "error",
                    "type": mutation.get("type"),
                    "error": str(e),
                })

        if results:
            logger.info(f"Processed {len(results)} mutations: "
                       f"{sum(1 for r in results if r.get('status') == 'applied')} applied, "
                       f"{sum(1 for r in results if r.get('status') == 'blocked')} blocked")

        return results

    # Required fields per mutation type
    _REQUIRED_FIELDS = {
        "adjust_weight": ["drive", "value"],
        "adjust_threshold": ["value"],
        "adjust_rate": ["value"],
        "adjust_cooldown": ["value"],
        "adjust_turns_per_hour": ["value"],
        "add_drive": ["name"],
        "remove_drive": ["drive"],
        "spike_drive": ["drive"],
        "decay_drive": ["drive"],
    }

    def _apply_mutation(self, mutation: dict) -> dict:
        """Apply a single mutation command."""
        self.guardrails.check_mutation_rate()

        mut_type = mutation.get("type", "")
        if not mut_type:
            raise ValueError("Mutation missing 'type' field")

        # Validate required fields
        for field in self._REQUIRED_FIELDS.get(mut_type, []):
            if field not in mutation:
                raise ValueError(f"Mutation '{mut_type}' requires field '{field}'")

        reason = mutation.get("reason", "no reason given")

        if mut_type == "adjust_weight":
            return self._adjust_weight(mutation, reason)
        elif mut_type == "adjust_threshold":
            return self._adjust_threshold(mutation, reason)
        elif mut_type == "adjust_rate":
            return self._adjust_rate(mutation, reason)
        elif mut_type == "adjust_cooldown":
            return self._adjust_cooldown(mutation, reason)
        elif mut_type == "adjust_turns_per_hour":
            return self._adjust_turns_per_hour(mutation, reason)
        elif mut_type == "add_drive":
            return self._add_drive(mutation, reason)
        elif mut_type == "remove_drive":
            return self._remove_drive(mutation, reason)
        elif mut_type == "spike_drive":
            return self._spike_drive(mutation, reason)
        elif mut_type == "decay_drive":
            return self._decay_drive(mutation, reason)
        else:
            raise ValueError(f"Unknown mutation type: {mut_type}")

    def _adjust_weight(self, mutation: dict, reason: str) -> dict:
        drive_name = mutation["drive"]
        proposed = float(mutation["value"])

        if drive_name not in self.drives.drives:
            raise ValueError(f"Drive '{drive_name}' does not exist")

        drive = self.drives.drives[drive_name]
        current = drive.weight
        validated = self.guardrails.validate_weight_change(drive_name, current, proposed)
        clamped = validated != proposed

        drive.weight = validated

        self.audit.record(MutationRecord(
            timestamp=time.time(),
            mutation_type="weight",
            target=f"drives.{drive_name}.weight",
            before=current,
            after=validated,
            reason=reason,
            clamped=clamped,
            clamped_from=proposed if clamped else None,
        ))

        return {"status": "applied", "type": "adjust_weight", "drive": drive_name,
                "before": current, "after": validated, "clamped": clamped}

    def _adjust_threshold(self, mutation: dict, reason: str) -> dict:
        proposed = float(mutation["value"])
        current = self.config.drives.trigger_threshold
        validated = self.guardrails.validate_threshold_change(current, proposed)
        clamped = validated != proposed

        self.config.drives.trigger_threshold = validated

        self.audit.record(MutationRecord(
            timestamp=time.time(),
            mutation_type="threshold",
            target="drives.trigger_threshold",
            before=current,
            after=validated,
            reason=reason,
            clamped=clamped,
            clamped_from=proposed if clamped else None,
        ))

        return {"status": "applied", "type": "adjust_threshold",
                "before": current, "after": validated, "clamped": clamped}

    def _adjust_rate(self, mutation: dict, reason: str) -> dict:
        proposed = float(mutation["value"])
        current = self.config.drives.pressure_rate
        validated = self.guardrails.validate_rate_change(current, proposed)
        clamped = validated != proposed

        self.config.drives.pressure_rate = validated

        self.audit.record(MutationRecord(
            timestamp=time.time(),
            mutation_type="rate",
            target="drives.pressure_rate",
            before=current,
            after=validated,
            reason=reason,
            clamped=clamped,
            clamped_from=proposed if clamped else None,
        ))

        return {"status": "applied", "type": "adjust_rate",
                "before": current, "after": validated, "clamped": clamped}

    def _adjust_cooldown(self, mutation: dict, reason: str) -> dict:
        proposed = int(mutation["value"])
        current = self.config.openclaw.min_trigger_interval
        validated = self.guardrails.validate_cooldown(proposed)

        self.config.openclaw.min_trigger_interval = validated

        self.audit.record(MutationRecord(
            timestamp=time.time(),
            mutation_type="cooldown",
            target="openclaw.min_trigger_interval",
            before=current,
            after=validated,
            reason=reason,
            clamped=validated != proposed,
            clamped_from=proposed if validated != proposed else None,
        ))

        return {"status": "applied", "type": "adjust_cooldown",
                "before": current, "after": validated}

    def _adjust_turns_per_hour(self, mutation: dict, reason: str) -> dict:
        proposed = int(mutation["value"])
        current = self.config.openclaw.max_turns_per_hour
        validated = self.guardrails.validate_turns_per_hour(proposed)

        self.config.openclaw.max_turns_per_hour = validated

        self.audit.record(MutationRecord(
            timestamp=time.time(),
            mutation_type="turns_per_hour",
            target="openclaw.max_turns_per_hour",
            before=current,
            after=validated,
            reason=reason,
            clamped=validated != proposed,
        ))

        return {"status": "applied", "type": "adjust_turns_per_hour",
                "before": current, "after": validated}

    def _add_drive(self, mutation: dict, reason: str) -> dict:
        name = mutation["name"]
        weight = float(mutation.get("weight", 0.5))

        if name in self.drives.drives:
            raise ValueError(f"Drive '{name}' already exists")

        self.guardrails.validate_drive_count(len(self.drives.drives))
        weight = self.guardrails.validate_weight_change(name, 0.5, weight)

        from pulse.src.drives.engine import Drive
        self.drives.drives[name] = Drive(
            name=name,
            category=name,
            weight=weight,
        )

        self.audit.record(MutationRecord(
            timestamp=time.time(),
            mutation_type="drive_create",
            target=f"drives.{name}",
            before=None,
            after={"name": name, "weight": weight},
            reason=reason,
        ))

        return {"status": "applied", "type": "add_drive", "name": name, "weight": weight}

    def _remove_drive(self, mutation: dict, reason: str) -> dict:
        name = mutation["drive"]
        self.guardrails.validate_drive_removal(name)

        if name not in self.drives.drives:
            raise ValueError(f"Drive '{name}' does not exist")

        old_weight = self.drives.drives[name].weight
        del self.drives.drives[name]

        self.audit.record(MutationRecord(
            timestamp=time.time(),
            mutation_type="drive_remove",
            target=f"drives.{name}",
            before={"name": name, "weight": old_weight},
            after=None,
            reason=reason,
        ))

        return {"status": "applied", "type": "remove_drive", "name": name}

    def _spike_drive(self, mutation: dict, reason: str) -> dict:
        name = mutation["drive"]
        amount = float(mutation.get("amount", 0.3))

        if name not in self.drives.drives:
            raise ValueError(f"Drive '{name}' does not exist")

        drive = self.drives.drives[name]
        before = drive.pressure
        drive.spike(amount, self.config.drives.max_pressure)

        self.audit.record(MutationRecord(
            timestamp=time.time(),
            mutation_type="spike",
            target=f"drives.{name}.pressure",
            before=round(before, 4),
            after=round(drive.pressure, 4),
            reason=reason,
        ))

        return {"status": "applied", "type": "spike_drive", "name": name,
                "before": round(before, 4), "after": round(drive.pressure, 4)}

    def _decay_drive(self, mutation: dict, reason: str) -> dict:
        name = mutation["drive"]
        amount = float(mutation.get("amount", 0.3))

        if name not in self.drives.drives:
            raise ValueError(f"Drive '{name}' does not exist")

        drive = self.drives.drives[name]
        before = drive.pressure
        drive.decay(amount)

        self.audit.record(MutationRecord(
            timestamp=time.time(),
            mutation_type="decay",
            target=f"drives.{name}.pressure",
            before=round(before, 4),
            after=round(drive.pressure, 4),
            reason=reason,
        ))

        return {"status": "applied", "type": "decay_drive", "name": name,
                "before": round(before, 4), "after": round(drive.pressure, 4)}

    def get_state(self) -> dict:
        """Get current mutation state for the agent to reason about."""
        return {
            "drives": {
                name: {"weight": d.weight, "pressure": round(d.pressure, 4)}
                for name, d in self.drives.drives.items()
            },
            "trigger_threshold": self.config.drives.trigger_threshold,
            "pressure_rate": self.config.drives.pressure_rate,
            "cooldown": self.config.openclaw.min_trigger_interval,
            "turns_per_hour": self.config.openclaw.max_turns_per_hour,
            "mutations": self.audit.summary(),
            "guardrails": {
                "protected_drives": list(self.guardrails.limits.protected_drives),
                "max_weight_delta": self.guardrails.limits.max_weight_delta,
                "max_threshold_delta": self.guardrails.limits.max_threshold_delta,
                "max_mutations_per_hour": self.guardrails.limits.max_mutations_per_hour,
            },
        }
