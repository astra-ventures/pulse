"""
Event Bus — lightweight internal pub/sub for decoupling side effects.

Instead of the daemon manually coordinating 6 things after each trigger,
modules subscribe to events and react independently.
"""

import logging
from typing import Any, Callable, Dict, List

logger = logging.getLogger("pulse.events")


class EventBus:
    """Simple synchronous event bus."""

    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = {}

    def on(self, event_type: str, handler: Callable):
        """Subscribe to an event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def emit(self, event_type: str, **kwargs):
        """Emit an event. Handlers are called synchronously."""
        handlers = self._handlers.get(event_type, [])
        for handler in handlers:
            try:
                handler(**kwargs)
            except Exception as e:
                logger.error(f"Event handler error ({event_type}): {e}", exc_info=True)

    def clear(self):
        """Remove all handlers."""
        self._handlers.clear()


# Event type constants
TRIGGER_SUCCESS = "trigger_success"
TRIGGER_FAILURE = "trigger_failure"
MUTATION_APPLIED = "mutation_applied"
STATE_SAVED = "state_saved"
