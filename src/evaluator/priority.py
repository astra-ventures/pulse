"""
Priority Evaluator — the decision layer.

"Should I think about this right now?"

This is the gatekeeper between drives/sensors and agent turns.
Too sensitive = noisy, expensive. Too conservative = inert.
Calibration is everything.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

from pulse.src.core.config import PulseConfig
from pulse.src.drives.engine import Drive, DriveState

logger = logging.getLogger("pulse.evaluator")


@dataclass
class TriggerDecision:
    """The evaluator's decision on whether to trigger an agent turn."""
    should_trigger: bool
    reason: str
    total_pressure: float
    top_drive: Optional[Drive] = None
    sensor_context: str = ""
    timestamp: float = 0.0
    recommend_generate: bool = False  # True when drives high but no actionable work
    top_drive_pressure_snapshot: float = 0.0  # immutable snapshot of top_drive.pressure at decision time

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()
        if self.top_drive and not self.top_drive_pressure_snapshot:
            self.top_drive_pressure_snapshot = self.top_drive.pressure


class PriorityEvaluator:
    """Decides when the agent should think."""

    def __init__(self, config: PulseConfig):
        self.config = config

    def evaluate(self, drive_state: DriveState, sensor_data: dict) -> TriggerDecision:
        """
        Evaluate whether to trigger an agent turn.
        
        Decision factors:
        1. Any single drive above threshold?
        2. Combined weighted pressure above threshold?
        3. Critical sensor alerts?
        4. Currently in conversation? (suppress if so)
        """
        rules = self.config.evaluator.rules

        # Check conversation suppression (fed by ConversationSensor)
        if rules.suppress_during_conversation:
            convo = sensor_data.get("conversation", {})
            if convo.get("active") or convo.get("in_cooldown"):
                return TriggerDecision(
                    should_trigger=False,
                    reason=f"suppressed_conversation (last activity {convo.get('seconds_since', '?')}s ago)",
                    total_pressure=drive_state.total_pressure,
                    top_drive=drive_state.top_drive,
                )

        # Check for critical system alerts (bypass thresholds)
        system_alerts = sensor_data.get("system", {}).get("alerts", [])
        critical = [a for a in system_alerts if a.get("severity") == "high"]
        if critical:
            return TriggerDecision(
                should_trigger=True,
                reason=f"critical_alert: {critical[0].get('type')}",
                total_pressure=drive_state.total_pressure,
                top_drive=drive_state.top_drive,
                sensor_context=str(critical[0]),
            )

        # Check single drive threshold
        if drive_state.top_drive:
            if drive_state.top_drive.weighted_pressure >= rules.single_drive_threshold:
                return TriggerDecision(
                    should_trigger=True,
                    reason=f"single_drive_threshold: {drive_state.top_drive.name}",
                    total_pressure=drive_state.total_pressure,
                    top_drive=drive_state.top_drive,
                )

        # Check combined threshold
        if drive_state.total_pressure >= rules.combined_threshold:
            return TriggerDecision(
                should_trigger=True,
                reason="combined_threshold",
                total_pressure=drive_state.total_pressure,
                top_drive=drive_state.top_drive,
            )

        # No trigger — but if pressure is significant, recommend GENERATE
        # so the daemon can synthesize new tasks instead of idle-looping
        recommend = drive_state.total_pressure >= (rules.combined_threshold * 0.8)
        return TriggerDecision(
            should_trigger=False,
            reason="below_threshold",
            total_pressure=drive_state.total_pressure,
            top_drive=drive_state.top_drive,
            recommend_generate=recommend,
        )

    # Conversation detection is now handled by ConversationSensor
    # feeding data through sensor_data["conversation"] in evaluate()
