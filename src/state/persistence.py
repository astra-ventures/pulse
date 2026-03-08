"""
State Persistence — synthetic continuity.

This is what makes Pulse feel continuous even though the daemon
and the agent are separate processes. State survives restarts,
migrations, and hardware changes.

State files are plain JSON — human-readable, git-friendly, portable.
"""

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

from pulse.src import __version__
from pulse.src.core.config import PulseConfig

logger = logging.getLogger("pulse.state")


class StatePersistence:
    """Manages persistent state across daemon restarts."""

    def __init__(self, config: PulseConfig):
        self.config = config
        self.state_dir = Path(config.state.dir).expanduser()
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self._data: Dict[str, Any] = {}
        self._dirty = False
        self._last_save = time.time()
        self._trigger_history: list = []
        self._consecutive_write_failures: int = 0

    @property
    def state_file(self) -> Path:
        return self.state_dir / "pulse-state.json"

    @property
    def history_file(self) -> Path:
        return self.state_dir / "trigger-history.jsonl"

    def load(self):
        """Load state from disk."""
        if self.state_file.exists():
            try:
                self._data = json.loads(self.state_file.read_text())
                logger.info(f"Loaded state from {self.state_file}")
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load state: {e}. Starting fresh.")
                self._data = {}
        else:
            self._data = {}
            logger.info("No existing state — starting fresh")

    def save(self):
        """Save state to disk atomically (write to temp, then rename)."""
        self._data["_saved_at"] = time.time()
        self._data["_version"] = __version__

        try:
            content = json.dumps(self._data, indent=2, default=str)
            # Atomic write: temp file → fsync → rename
            fd, tmp_path = tempfile.mkstemp(dir=str(self.state_dir), suffix=".tmp")
            try:
                os.write(fd, content.encode())
                os.fsync(fd)
                os.close(fd)
                os.rename(tmp_path, str(self.state_file))
            except Exception:
                os.close(fd)
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            self._dirty = False
            self._last_save = time.time()
            self._consecutive_write_failures = 0
        except OSError as e:
            self._consecutive_write_failures += 1
            logger.error(
                f"Failed to save state ({self._consecutive_write_failures} consecutive): {e}"
            )
            if self._consecutive_write_failures >= 3:
                logger.critical(
                    f"DISK WRITE FAILURE x{self._consecutive_write_failures} — "
                    "state persistence degraded. Check disk space!"
                )

    def maybe_save(self):
        """Save if dirty and enough time has passed."""
        if self._dirty and (
            time.time() - self._last_save > self.config.state.save_interval
        ):
            self.save()
            self._maybe_prune_history()

    def _maybe_prune_history(self):
        """Prune trigger history older than retention_days. Runs at most once per hour."""
        last_prune = self._data.get("_last_prune", 0)
        now = time.time()
        if now - last_prune < 3600:
            return

        retention_seconds = self.config.state.history_retention_days * 86400
        cutoff = now - retention_seconds

        if self.history_file.exists():
            try:
                kept = []
                pruned = 0
                with open(self.history_file) as f:
                    for line in f:
                        try:
                            entry = json.loads(line)
                            if entry.get("timestamp", 0) >= cutoff:
                                kept.append(line)
                            else:
                                pruned += 1
                        except json.JSONDecodeError:
                            continue
                if pruned > 0:
                    with open(self.history_file, "w") as f:
                        f.writelines(kept)
                    logger.info(
                        f"Pruned {pruned} trigger history entries older than {self.config.state.history_retention_days}d"
                    )
            except OSError as e:
                logger.warning(f"History prune failed: {e}")

        self._data["_last_prune"] = now

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from state."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any):
        """Set a value in state."""
        self._data[key] = value
        self._dirty = True

    def log_trigger(self, decision, success: bool):
        """Log a trigger event to history."""
        entry = {
            "timestamp": time.time(),
            "reason": decision.reason,
            "pressure": round(decision.total_pressure, 4),
            "top_drive": decision.top_drive.name if decision.top_drive else None,
            "success": success,
        }

        # Append to JSONL history (rotate if > 5MB)
        try:
            self._rotate_if_needed(self.history_file, max_bytes=5 * 1024 * 1024)
            with open(self.history_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as e:
            logger.warning(f"Failed to log trigger: {e}")

        # Update state
        self._data["last_trigger"] = entry
        trigger_count = self._data.get("total_triggers", 0)
        self._data["total_triggers"] = trigger_count + 1

        if success:
            success_count = self._data.get("successful_triggers", 0)
            self._data["successful_triggers"] = success_count + 1

        self._dirty = True

    def _rotate_if_needed(self, filepath: Path, max_bytes: int = 5 * 1024 * 1024):
        """Rotate a file if it exceeds max_bytes. Keeps one .old backup."""
        try:
            if filepath.exists() and filepath.stat().st_size > max_bytes:
                old = filepath.with_suffix(filepath.suffix + ".old")
                if old.exists():
                    old.unlink()
                filepath.rename(old)
                logger.info(f"Rotated {filepath.name} ({max_bytes // 1024}KB cap)")
        except OSError as e:
            logger.warning(f"Rotation failed for {filepath}: {e}")

    def get_trigger_stats(self) -> dict:
        """Get trigger statistics."""
        return {
            "total": self._data.get("total_triggers", 0),
            "successful": self._data.get("successful_triggers", 0),
            "last": self._data.get("last_trigger"),
        }
