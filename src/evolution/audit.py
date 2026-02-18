"""
Audit Log — immutable record of every self-modification.

Every mutation is logged with:
- What changed (before → after)
- Why (the agent's reasoning)
- When
- Whether guardrails clamped the change

This is append-only JSONL. The agent cannot delete or modify past entries.
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("pulse.evolution.audit")


@dataclass
class MutationRecord:
    """A single self-modification event."""
    timestamp: float
    mutation_type: str          # "weight", "threshold", "drive_add", "drive_remove", "rate", "cooldown", "drive_create"
    target: str                 # what was changed (e.g., "drives.goals.weight")
    before: Any                 # value before
    after: Any                  # value after
    reason: str                 # agent's explanation
    clamped: bool = False       # whether guardrails modified the request
    clamped_from: Any = None    # original request before clamping
    source: str = "agent"       # "agent" or "evaluator" or "manual"


class AuditLog:
    """Append-only mutation audit log."""

    def __init__(self, state_dir: Path):
        self.log_file = state_dir / "mutations.jsonl"
        self._count = 0

        self._cached_summary = None
        self._last_hash = "genesis"

        # Count existing entries and recover last hash for chain integrity
        if self.log_file.exists():
            with open(self.log_file) as f:
                for line in f:
                    self._count += 1
                    try:
                        entry = json.loads(line)
                        if "hash" in entry:
                            self._last_hash = entry["hash"]
                    except json.JSONDecodeError:
                        pass

    def record(self, mutation: MutationRecord):
        """Record a mutation. Append-only with size-based rotation."""
        entry = asdict(mutation)
        # Add hash chain for tamper detection
        entry["prev_hash"] = self._last_hash
        chain_str = json.dumps(entry, sort_keys=True, default=str)
        entry["hash"] = hashlib.sha256(chain_str.encode()).hexdigest()[:16]
        self._last_hash = entry["hash"]
        
        try:
            # Rotate if > 5MB
            self._rotate_if_needed()
            with open(self.log_file, "a") as f:
                f.write(json.dumps(entry, default=str) + "\n")
            self._count += 1
            self._cached_summary = None  # Invalidate cache
            logger.info(
                f"MUTATION #{self._count}: {mutation.mutation_type} "
                f"{mutation.target}: {mutation.before} → {mutation.after} "
                f"({'clamped' if mutation.clamped else 'clean'}) "
                f"reason: {mutation.reason}"
            )
        except OSError as e:
            logger.error(f"Failed to write audit log: {e}")

    def recent(self, n: int = 10) -> list:
        """Get the N most recent mutations efficiently using a deque."""
        if not self.log_file.exists():
            return []

        from collections import deque
        try:
            ring = deque(maxlen=n)
            with open(self.log_file) as f:
                for line in f:
                    try:
                        ring.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            return list(ring)
        except OSError as e:
            logger.warning(f"Error reading audit log: {e}")
            return []

    def _rotate_if_needed(self, max_bytes: int = 5 * 1024 * 1024):
        """Rotate log file if it exceeds max_bytes."""
        try:
            if self.log_file.exists() and self.log_file.stat().st_size > max_bytes:
                old = self.log_file.with_suffix(".jsonl.old")
                if old.exists():
                    old.unlink()
                self.log_file.rename(old)
                self._count = 0
                logger.info(f"Rotated mutations.jsonl ({max_bytes // 1024}KB cap)")
        except OSError as e:
            logger.warning(f"Rotation failed: {e}")

    @property
    def total_mutations(self) -> int:
        return self._count

    def summary(self) -> dict:
        """Get a cached summary of mutation history."""
        if self._cached_summary is not None:
            return self._cached_summary

        if not self.log_file.exists():
            return {"total": 0, "by_type": {}, "recent": []}

        by_type = {}
        entries = []
        try:
            with open(self.log_file) as f:
                for line in f:
                    entry = json.loads(line)
                    entries.append(entry)
                    mt = entry.get("mutation_type", "unknown")
                    by_type[mt] = by_type.get(mt, 0) + 1
        except (OSError, json.JSONDecodeError):
            pass

        self._cached_summary = {
            "total": len(entries),
            "by_type": by_type,
            "clamped_count": sum(1 for e in entries if e.get("clamped")),
            "recent": entries[-5:],
        }
        return self._cached_summary
