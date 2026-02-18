"""
Daily Note Sync — writes Pulse events to agent's daily notes.

Appends trigger and mutation events to memory/YYYY-MM-DD.md so
the agent can see what Pulse did when reviewing daily logs.
"""

import logging
from datetime import datetime
from pathlib import Path

from pulse.src.core.config import PulseConfig

logger = logging.getLogger("pulse.daily_sync")


class DailyNoteSync:
    """Appends Pulse events to the agent's daily notes."""

    def __init__(self, config: PulseConfig):
        self.daily_dir = Path(config.workspace.root).expanduser() / config.workspace.daily_notes
        self._last_date: str = ""
        self._header_written: bool = False

    def _get_file(self) -> Path:
        """Get today's daily note path."""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._last_date:
            self._last_date = today
            self._header_written = False
        return self.daily_dir / f"{today}.md"

    def _ensure_header(self, f):
        """Write Pulse section header if not yet written today."""
        if not self._header_written:
            # Check if header already present (from previous run today)
            path = self._get_file()
            try:
                if path.exists() and "### 🫀 Pulse Activity" in path.read_text():
                    self._header_written = True
                    return
            except OSError:
                pass
            f.write("\n### 🫀 Pulse Activity\n")
            self._header_written = True

    def log_trigger(self, turn: int, reason: str, top_drive: str, pressure: float, success: bool):
        """Log a trigger event."""
        try:
            path = self._get_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            now = datetime.now().strftime("%H:%M")
            status = "✅" if success else "❌"
            with open(path, "a") as f:
                self._ensure_header(f)
                f.write(f"- {now} {status} Trigger #{turn}: {reason} "
                        f"(drive: {top_drive}, pressure: {pressure:.2f})\n")
        except OSError as e:
            logger.warning(f"Failed to sync trigger to daily notes: {e}")

    def log_mutation(self, result: dict):
        """Log a mutation event."""
        try:
            path = self._get_file()
            now = datetime.now().strftime("%H:%M")
            mut_type = result.get("type", "unknown")
            detail = ""
            if "drive" in result or "name" in result:
                name = result.get("drive") or result.get("name", "?")
                before = result.get("before", "?")
                after = result.get("after") or result.get("weight", "?")
                detail = f" {name}: {before} → {after}"
            with open(path, "a") as f:
                self._ensure_header(f)
                f.write(f"- {now} 🧬 Mutation: {mut_type}{detail}\n")
        except OSError as e:
            logger.warning(f"Failed to sync mutation to daily notes: {e}")
