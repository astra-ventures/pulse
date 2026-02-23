"""PARIETAL Dynamic Sensors — auto-generated from world model discovery.

These sensors are registered at runtime by PARIETAL based on what it finds
in the workspace. They watch file ages, file content, HTTP health endpoints,
and git status.
"""

import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Dict

from pulse.src.sensors.manager import BaseSensor

logger = logging.getLogger("pulse.parietal.sensors")


class ParietalFileSensor(BaseSensor):
    """Watches a specific file's age or modification time."""

    def __init__(self, signal):
        self.signal = signal
        self.name = f"parietal.file.{signal.id}"

    async def read(self) -> dict:
        path = Path(self.signal.target)
        if not path.exists():
            return {"signal_id": self.signal.id, "status": "missing", "healthy": False}
        try:
            age_hours = (time.time() - path.stat().st_mtime) / 3600
            healthy = _eval_file_age(self.signal.healthy_if, age_hours)
            return {
                "signal_id": self.signal.id,
                "age_hours": round(age_hours, 2),
                "healthy": healthy,
            }
        except OSError as e:
            return {"signal_id": self.signal.id, "status": "error", "healthy": False, "error": str(e)}


class ParietalFileContentSensor(BaseSensor):
    """Watches a file's content for health indicators."""

    def __init__(self, signal):
        self.signal = signal
        self.name = f"parietal.content.{signal.id}"

    async def read(self) -> dict:
        path = Path(self.signal.target)
        if not path.exists():
            return {"signal_id": self.signal.id, "status": "missing", "healthy": False}
        try:
            content = path.read_text(errors="ignore")
            lines = content.strip().splitlines()
            return {
                "signal_id": self.signal.id,
                "lines": len(lines),
                "healthy": len(lines) > 0,
            }
        except OSError as e:
            return {"signal_id": self.signal.id, "status": "error", "healthy": False, "error": str(e)}


class ParietalHttpSensor(BaseSensor):
    """Hits a health endpoint and checks response."""

    def __init__(self, signal):
        self.signal = signal
        self.name = f"parietal.http.{signal.id}"

    async def read(self) -> dict:
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.signal.target,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as response:
                    return {
                        "signal_id": self.signal.id,
                        "status": response.status,
                        "healthy": response.status == 200,
                    }
        except Exception as e:
            return {
                "signal_id": self.signal.id,
                "status": "error",
                "healthy": False,
                "error": str(e),
            }


class ParietalGitSensor(BaseSensor):
    """Checks git status for uncommitted changes."""

    def __init__(self, signal):
        self.signal = signal
        self.name = f"parietal.git.{signal.id}"

    async def read(self) -> dict:
        try:
            result = subprocess.run(
                ["git", "-C", self.signal.target, "status", "--porcelain"],
                capture_output=True, text=True, timeout=5,
            )
            has_changes = bool(result.stdout.strip())
            return {
                "signal_id": self.signal.id,
                "has_uncommitted": has_changes,
                "healthy": not has_changes,
            }
        except (subprocess.TimeoutExpired, OSError) as e:
            return {
                "signal_id": self.signal.id,
                "status": "error",
                "healthy": True,  # fail-open for git checks
                "error": str(e),
            }


def _eval_file_age(condition: str, age_hours: float) -> bool:
    """Evaluate a simple file-age condition like 'age_hours < 24'."""
    import re
    match = re.match(r'age_hours\s*(<=?|>=?|==|!=)\s*(\d+\.?\d*)', condition)
    if match:
        op, val_str = match.groups()
        val = float(val_str)
        if op == "<":
            return age_hours < val
        elif op == "<=":
            return age_hours <= val
        elif op == ">":
            return age_hours > val
        elif op == ">=":
            return age_hours >= val
        elif op == "==":
            return age_hours == val
        elif op == "!=":
            return age_hours != val
    return True
