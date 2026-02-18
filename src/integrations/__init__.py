"""
Integrations — pluggable post-trigger behavior.

An integration defines:
1. How to build the trigger message sent to the agent
2. What drives map to (optional workspace-specific source reading)
3. How feedback flows back

Core Pulse (drives, sensors, evaluator, webhook) is generic.
Integrations customize what happens after a trigger decision.
"""

from abc import ABC, abstractmethod
from typing import Optional


class Integration(ABC):
    """Base class for Pulse integrations."""

    name: str = "base"

    @abstractmethod
    def build_trigger_message(self, decision, config) -> str:
        """Build the message sent to OpenClaw when a trigger fires.
        
        Args:
            decision: TriggerDecision with reason, top_drive, pressure, etc.
            config: PulseConfig for access to prefix and other settings.
            
        Returns:
            String message to send via webhook.
        """
        ...

    def on_startup(self, daemon) -> None:
        """Called when daemon starts. Override to initialize integration-specific resources."""
        pass

    def on_shutdown(self, daemon) -> None:
        """Called when daemon stops."""
        pass
