"""
Iris Integration — custom wiring for Iris's cognitive architecture.

Connects Pulse to:
- CORTEX.md loop (SENSE → THINK → ACT → MEASURE → EVOLVE)
- Hippocampus memory system
- Inner systems (goals, curiosity, emotions, hypotheses, etc.)
- Working memory for cross-session continuity
- Work discovery (TIERS.md + recent memory + hippocampus)

This is Layer 2 — specific to how Iris thinks and acts.
Other agents would write their own integration or use DefaultIntegration.
"""

import json
import logging
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

from pulse.src.integrations import Integration

logger = logging.getLogger("pulse.iris")

# Max chars per context section to keep trigger message reasonable
_MAX_TIERS = 2000
_MAX_MEMORY = 1500
_MAX_HIPPO = 1000
_MAX_WORKING_MEM = 500


class IrisIntegration(Integration):
    """Iris-specific integration with CORTEX.md and hippocampus."""

    name = "iris"

    # ── context loaders ──────────────────────────────────────────

    def _load_working_memory(self, config) -> str:
        """Load working memory snapshot for context in isolated sessions."""
        wm_path = Path(config.workspace.root).expanduser() / "memory" / "self" / "working-memory.json"
        try:
            if wm_path.exists():
                data = json.loads(wm_path.read_text())
                threads = data.get("activeThreads", [])
                if threads:
                    lines = ["**Working memory threads:**"]
                    for t in threads[:5]:
                        status = t.get("status", "unknown")
                        topic = t.get("topic", "unknown")
                        lines.append(f"  - {topic}: {status}")
                    return "\n".join(lines)[:_MAX_WORKING_MEM]
        except Exception as e:
            logger.debug(f"Could not load working memory: {e}")
        return ""

    def _load_tiers(self, config) -> str:
        """Load TIERS.md project roadmap for work discovery."""
        tiers_path = Path(config.workspace.root).expanduser() / "TIERS.md"
        try:
            if tiers_path.exists():
                content = tiers_path.read_text()
                if content.strip():
                    return content[:_MAX_TIERS]
        except Exception as e:
            logger.debug(f"Could not load TIERS.md: {e}")
        return ""

    def _load_recent_memory(self, config) -> str:
        """Load today's and yesterday's daily memory notes."""
        mem_dir = Path(config.workspace.root).expanduser() / "memory"
        lines = []
        today = datetime.now()
        for delta in (0, 1):
            day = today - timedelta(days=delta)
            path = mem_dir / f"{day.strftime('%Y-%m-%d')}.md"
            try:
                if path.exists():
                    content = path.read_text()
                    if content.strip():
                        label = "Today" if delta == 0 else "Yesterday"
                        # Take last portion — most recent entries are at the bottom
                        trimmed = content[-(_MAX_MEMORY // 2):]
                        # Find first newline to avoid cutting mid-line
                        nl = trimmed.find("\n")
                        if nl > 0:
                            trimmed = trimmed[nl + 1:]
                        lines.append(f"**{label}'s memory ({path.name}):**")
                        lines.append(trimmed)
            except Exception as e:
                logger.debug(f"Could not load {path}: {e}")

        return "\n".join(lines)[:_MAX_MEMORY] if lines else ""

    def _load_hippocampus(self, config) -> str:
        """Recall recent hippocampus memories via recall.sh."""
        script = (
            Path(config.workspace.root).expanduser()
            / "skills" / "hippocampus-memory" / "scripts" / "recall.sh"
        )
        if not script.exists():
            return ""
        try:
            result = subprocess.run(
                ["bash", str(script), "recent work ideas projects", "--top", "5"],
                capture_output=True, text=True, timeout=10,
                env={
                    "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                    "HOME": str(Path.home()),
                    "WORKSPACE": str(Path(config.workspace.root).expanduser()),
                },
            )
            output = result.stdout.strip()
            if output:
                return f"**Hippocampus recall (recent/relevant):**\n{output}"[:_MAX_HIPPO]
        except Exception as e:
            logger.debug(f"Hippocampus recall failed: {e}")
        return ""

    # ── trigger message builder ──────────────────────────────────

    def build_trigger_message(self, decision, config) -> str:
        prefix = config.openclaw.message_prefix
        is_isolated = config.openclaw.session_mode == "isolated"

        parts = [
            f"{prefix} Self-initiated turn.",
            f"Trigger reason: {decision.reason}",
        ]

        if decision.top_drive:
            parts.append(
                f"Top drive: {decision.top_drive.name} "
                f"(pressure: {decision.top_drive.pressure:.2f})"
            )
        else:
            parts.append(f"Total pressure: {decision.total_pressure:.2f}")

        if decision.sensor_context:
            parts.append(f"Suggested focus: {decision.sensor_context}")

        # ── Work Discovery Context (isolated sessions) ──
        if is_isolated:
            parts.append("")
            parts.append("=" * 50)
            parts.append("WORK DISCOVERY CONTEXT")
            parts.append("=" * 50)
            parts.append(
                "If active goals are blocked, DO NOT just report 'standing by'. "
                "Use the context below to find NEW productive work: research, "
                "content creation, competitor analysis, learning, building, "
                "or assigning tasks to Scout/Edge/Forge."
            )

            # 1. Working memory
            wm = self._load_working_memory(config)
            if wm:
                parts.append("")
                parts.append(wm)

            # 2. TIERS.md — full project roadmap
            tiers = self._load_tiers(config)
            if tiers:
                parts.append("")
                parts.append("**Project roadmap (TIERS.md):**")
                parts.append(tiers)

            # 3. Recent daily memory
            mem = self._load_recent_memory(config)
            if mem:
                parts.append("")
                parts.append(mem)

            # 4. Hippocampus recall
            hippo = self._load_hippocampus(config)
            if hippo:
                parts.append("")
                parts.append(hippo)

            parts.append("")
            parts.append("=" * 50)

        # Iris-specific: invoke the full CORTEX.md cognitive loop
        parts.append("")
        parts.append(
            "Run your CORTEX.md loop: "
            "SENSE → THINK → ACT → MEASURE → EVOLVE."
        )
        parts.append(
            "IMPORTANT: 'Blocked on external deps' is NOT an excuse to do nothing. "
            "Find unblocked work from the context above. Research, build, create, learn."
        )

        # Feedback instructions
        parts.append("")
        parts.append(
            "After completing work, send feedback to Pulse so drives decay properly:"
        )
        parts.append(
            '  curl -s -X POST http://127.0.0.1:9720/feedback '
            '-H "Content-Type: application/json" '
            '-d \'{"drives_addressed": ["<drive>"], "outcome": "success", '
            '"summary": "<what you did>"}\''
        )

        parts.append("")
        parts.append("Log what you do to memory/YYYY-MM-DD.md.")

        # In isolated mode, remind about announcement behavior and audit logging
        if is_isolated:
            parts.append("")
            parts.append(
                "This is an isolated Pulse session. After completing your work:"
            )
            parts.append(
                "1. Post a log entry to Discord #pulse-log (channel ID: 1473418272551469240) "
                "with: trigger reason, what you did, drives addressed, and result."
            )
            parts.append(
                "2. If you completed meaningful work, your summary will also be "
                "announced to Signal. If nothing notable, respond with NO_REPLY."
            )

        return "\n".join(parts)
