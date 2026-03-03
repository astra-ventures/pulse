"""
TaskRouter — routes Pulse trigger messages to the appropriate model.

Pulse handles many kinds of tasks. Local 70B models (iris-70b-v3) are
great for identity, memory, emotional processing, and coordination.
Cloud models (Sonnet, Opus) are better for complex coding, architecture,
and multi-step implementations.

This router inspects the trigger message and picks the right model
before the webhook fires — so Anthropic only gets called when needed.

Routing tiers:
  opus   — architecture decisions, novel problems, >10-step chains
  sonnet — coding tasks, complex implementations, research synthesis
  local  — everything else (heartbeats, memory, emotional, coordination)
"""

import re
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("pulse.task_router")


# Keywords that signal a coding/implementation task → Sonnet
SONNET_KEYWORDS = [
    # Code generation
    "write code", "write a script", "write a function", "write a class",
    "implement", "refactor", "debug", "fix bug", "fix the bug",
    "typescript", "javascript", "python script", "react component",
    "next.js", "nextjs", "api route", "database migration", "sql",
    "build component", "create component", "add feature",
    "unit test", "write tests", "test suite", "jest", "pytest",
    # Deployment / infra
    "deploy", "vercel", "cloudflare", "docker", "dockerfile",
    "github actions", "ci/cd", "workflow",
    # Complex multi-step
    "step by step", "multi-step", "end-to-end",
    # Data processing
    "parse", "scrape", "extract data", "transform data",
]

# Keywords that signal architectural / deep reasoning → Opus
OPUS_KEYWORDS = [
    "architecture", "system design", "redesign", "from scratch",
    "comprehensive plan", "long-term roadmap", "fundamental",
    "novel approach", "first principles", "tradeoffs",
    "10 steps", "fifteen steps", "twenty steps",
]

# Keywords that are firmly local regardless of other signals
LOCAL_OVERRIDE_KEYWORDS = [
    "heartbeat", "heartbeat_ok", "cascade_stop",
    "how am i feeling", "drive state", "pulse state",
    "send feedback to pulse", "update memory", "update memory file",
    "write to memory", "log to memory",
    "emotional check-in", "read soul.md", "read heartbeat",
]


@dataclass
class RoutingDecision:
    model: str          # Full model string e.g. "ollama/iris-70b-v3-tools:latest"
    tier: str           # "local" | "sonnet" | "opus"
    reason: str         # Why this tier was chosen


class TaskRouter:
    """
    Routes Pulse trigger messages to the appropriate model.
    
    Configuration via pulse.yaml:
      openclaw:
        isolated_model: "ollama/iris-70b-v3-tools:latest"   # default (local)
        routing:
          sonnet_model: "anthropic/claude-sonnet-4-6"
          opus_model: "anthropic/claude-opus-4-6"
          enabled: true
    """

    def __init__(self, config):
        self.enabled = getattr(
            getattr(config.openclaw, "routing", None), "enabled", True
        )
        self.local_model = config.openclaw.isolated_model or "ollama/iris-70b-v3-tools:latest"
        
        routing_cfg = getattr(config.openclaw, "routing", None)
        self.sonnet_model = (
            getattr(routing_cfg, "sonnet_model", None) 
            or "anthropic/claude-sonnet-4-6"
        )
        self.opus_model = (
            getattr(routing_cfg, "opus_model", None) 
            or "anthropic/claude-opus-4-6"
        )

    def route(self, message: str) -> RoutingDecision:
        """
        Inspect a trigger message and return the appropriate model.
        
        Args:
            message: The full trigger message including context
            
        Returns:
            RoutingDecision with model string, tier, and reason
        """
        if not self.enabled:
            return RoutingDecision(
                model=self.local_model,
                tier="local",
                reason="routing disabled"
            )

        msg_lower = message.lower()

        # Local override — always stays local regardless of other signals
        for keyword in LOCAL_OVERRIDE_KEYWORDS:
            if keyword in msg_lower:
                return RoutingDecision(
                    model=self.local_model,
                    tier="local",
                    reason=f"local override keyword: '{keyword}'"
                )

        # Opus tier — architecture and deep reasoning
        for keyword in OPUS_KEYWORDS:
            if keyword in msg_lower:
                logger.info(f"TaskRouter: opus tier (keyword: '{keyword}')")
                return RoutingDecision(
                    model=self.opus_model,
                    tier="opus",
                    reason=f"opus keyword: '{keyword}'"
                )

        # Sonnet tier — coding and implementation
        for keyword in SONNET_KEYWORDS:
            if keyword in msg_lower:
                logger.info(f"TaskRouter: sonnet tier (keyword: '{keyword}')")
                return RoutingDecision(
                    model=self.sonnet_model,
                    tier="sonnet",
                    reason=f"coding keyword: '{keyword}'"
                )

        # Check for file extension patterns → likely a coding task
        code_extensions = re.findall(
            r'\b\w+\.(ts|tsx|js|jsx|py|sql|yaml|yml|json|css|html)\b',
            msg_lower
        )
        if code_extensions:
            ext = code_extensions[0]
            logger.info(f"TaskRouter: sonnet tier (file extension: .{ext})")
            return RoutingDecision(
                model=self.sonnet_model,
                tier="sonnet",
                reason=f"file extension: .{ext}"
            )

        # Default: local
        return RoutingDecision(
            model=self.local_model,
            tier="local",
            reason="default local (no coding/arch signals)"
        )
