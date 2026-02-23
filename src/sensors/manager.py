"""
Sensor Manager — passive environment monitoring.

Sensors watch the world without making model calls.
They feed raw signals into the drive engine.
"""

import asyncio
import fnmatch
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

import aiohttp

from pulse.src.core.config import PulseConfig

logger = logging.getLogger("pulse.sensors")


class SensorManager:
    """Coordinates all sensor modules."""

    def __init__(self, config: PulseConfig):
        self.config = config
        self.sensors: List[BaseSensor] = []
        self._last_readings: Dict[str, dict] = {}

        # Register enabled sensors
        if config.sensors.filesystem.enabled:
            self.sensors.append(FileSystemSensor(config))
        if config.sensors.system.enabled:
            self.sensors.append(SystemSensor(config))
        # Conversation sensor always on (feeds evaluator suppression)
        self.sensors.append(ConversationSensor(config))
        # Stub sensors — log if enabled but not yet implemented
        if getattr(config.sensors, 'discord', None) and config.sensors.discord.enabled:
            logger.warning("Discord sensor enabled in config but not yet implemented")
        # Web and git sensors are Phase 3+

    async def start(self):
        """Initialize all sensors."""
        for sensor in self.sensors:
            await sensor.initialize()
        logger.info(f"Started {len(self.sensors)} sensors")

    async def stop(self):
        """Stop all sensors."""
        for sensor in self.sensors:
            try:
                await sensor.stop()
            except Exception as e:
                logger.warning(f"Error stopping sensor '{sensor.name}': {e}")
        logger.info("All sensors stopped")

    def add_sensor(self, sensor: "BaseSensor"):
        """Dynamically register a new sensor at runtime."""
        self.sensors.append(sensor)
        logger.info(f"PARIETAL: registered sensor '{sensor.name}'")

    async def read(self) -> dict:
        """Read all sensors and return combined data."""
        readings = {}
        for sensor in self.sensors:
            try:
                data = await sensor.read()
                readings[sensor.name] = data
            except Exception as e:
                logger.warning(f"Sensor '{sensor.name}' error: {e}")
                readings[sensor.name] = {"error": str(e)}

        self._last_readings = readings
        return readings


class BaseSensor:
    """Base class for sensors."""
    name: str = "base"

    async def initialize(self):
        pass

    async def read(self) -> dict:
        raise NotImplementedError

    async def stop(self):
        """Cleanup resources on shutdown."""
        pass


class _WatchdogHandler(FileSystemEventHandler):
    """Collects file events from watchdog into a thread-safe buffer."""

    def __init__(self, ignore_patterns: List[str], ignore_self_writes: bool):
        super().__init__()
        self._ignore_patterns = ignore_patterns
        self._ignore_self_writes = ignore_self_writes
        self._lock = threading.Lock()
        self._buffer: List[dict] = []
        # Track paths we wrote ourselves (set by Pulse state persistence)
        self.self_write_paths: set = set()

    def _should_ignore(self, path: str) -> bool:
        name = Path(path).name
        for pattern in self._ignore_patterns:
            if '*' in pattern or '?' in pattern:
                if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(path, pattern):
                    return True
            else:
                if pattern in path:
                    return True
        resolved = str(Path(path).resolve())
        if self._ignore_self_writes and resolved in self.self_write_paths:
            self.self_write_paths.discard(resolved)
            return True
        return False

    def on_any_event(self, event: FileSystemEvent):
        if event.is_directory:
            return
        src = event.src_path
        if self._should_ignore(src):
            return
        # Map watchdog event types to our format
        etype = {
            "created": "created",
            "modified": "modified",
            "deleted": "deleted",
            "moved": "modified",
            "closed": "modified",
        }.get(event.event_type)
        if not etype:
            return
        with self._lock:
            self._buffer.append({"path": src, "type": etype})

    def drain(self) -> List[dict]:
        """Drain buffered events (thread-safe)."""
        with self._lock:
            events = self._buffer
            self._buffer = []
        # Deduplicate: keep last event per path
        seen: Dict[str, dict] = {}
        for e in events:
            seen[e["path"]] = e
        return list(seen.values())


class FileSystemSensor(BaseSensor):
    """Watch filesystem for changes using watchdog (event-driven, not polling)."""
    name = "filesystem"

    def __init__(self, config: PulseConfig):
        self.config = config
        self._observer: Optional[Observer] = None
        self._handler: Optional[_WatchdogHandler] = None

    async def initialize(self):
        """Start watchdog observer on configured paths."""
        fs_cfg = self.config.sensors.filesystem
        self._handler = _WatchdogHandler(
            ignore_patterns=fs_cfg.ignore_patterns,
            ignore_self_writes=fs_cfg.ignore_self_writes,
        )
        self._observer = Observer()

        watched = 0
        for watch_path in fs_cfg.watch_paths:
            resolved = Path(watch_path).expanduser()
            if resolved.exists():
                self._observer.schedule(self._handler, str(resolved), recursive=True)
                watched += 1
            else:
                logger.warning(f"Watch path does not exist: {resolved}")

        self._observer.daemon = True
        self._observer.start()
        logger.info(f"FileSystem sensor watching {watched} paths via watchdog")

    async def read(self) -> dict:
        """Drain buffered file events since last read."""
        if not self._handler:
            return {"changes": []}
        changes = self._handler.drain()
        if changes:
            logger.debug(f"FileSystem: {len(changes)} changes detected")
        return {"changes": changes}

    async def stop(self):
        """Stop the watchdog observer."""
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            logger.info("FileSystem sensor stopped")

    def mark_self_write(self, path: str):
        """Mark a path as written by Pulse (so we don't trigger on our own writes)."""
        if self._handler:
            self._handler.self_write_paths.add(str(Path(path).resolve()))


class ConversationSensor(BaseSensor):
    """Detect when a human is actively chatting with the agent.
    
    Watches OpenClaw's session directory for recent human messages.
    This feeds the evaluator's suppress_during_conversation logic.
    """
    name = "conversation"

    def __init__(self, config: PulseConfig):
        self.config = config
        self._last_human_activity: float = 0.0

    async def initialize(self):
        """Check for OpenClaw session directory."""
        session_dir = self._session_dir()
        if session_dir and session_dir.exists():
            logger.info(f"Conversation sensor watching: {session_dir}")
        else:
            logger.info("Conversation sensor: will use webhook API fallback")

    def _session_dir(self) -> Optional[Path]:
        """Find the OpenClaw data directory."""
        # OpenClaw stores session data in ~/.openclaw/data/
        candidates = [
            Path("~/.openclaw/data").expanduser(),
            Path(self.config.workspace.root).expanduser().parent / "data",
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    async def read(self) -> dict:
        """Check for recent human conversation activity.
        
        Strategy: Hit the OpenClaw webhook status endpoint to check
        if a session is currently active with a human. Falls back to
        checking session file mtimes.
        """
        now = time.time()
        active = False
        last_activity = self._last_human_activity

        # Strategy 1: Check the MAIN session transcript recency
        # Only the main session represents human conversation.
        # Cron, hook, and sub-agent sessions should NOT count as conversation.
        # The main session transcript is the largest .jsonl file and is 
        # typically stored at the workspace root (symlinked from sessions/).
        main_session_candidates = [
            # OpenClaw workspace root — main session transcript lives here
            Path("~/.openclaw/workspace").expanduser(),
            Path("~/.openclaw/agents/main/sessions").expanduser(),
        ]
        try:
            for session_dir in main_session_candidates:
                if not session_dir.exists():
                    continue
                # Find the largest .jsonl file (main session is always biggest)
                largest_file = None
                largest_size = 0
                for f in session_dir.iterdir():
                    if f.is_file() and f.suffix == ".jsonl" and not f.name.startswith("probe-"):
                        try:
                            stat = f.stat()
                            if stat.st_size > largest_size:
                                largest_size = stat.st_size
                                largest_file = f
                        except OSError:
                            continue
                # Only check the main session (largest file, >100KB to filter out small hook sessions)
                if largest_file and largest_size > 100_000:
                    mtime = largest_file.stat().st_mtime
                    if (now - mtime) < 120:  # 2 min window
                        active = True
                        self._last_human_activity = max(last_activity, mtime)
                    break  # Only check one dir
        except OSError:
            pass

        cooldown_sec = self.config.evaluator.rules.conversation_cooldown_minutes * 60
        in_cooldown = (now - self._last_human_activity) < cooldown_sec if self._last_human_activity else False

        return {
            "active": active,
            "in_cooldown": in_cooldown,
            "last_human_activity": self._last_human_activity,
            "seconds_since": round(now - self._last_human_activity) if self._last_human_activity else None,
        }


class SystemSensor(BaseSensor):
    """Monitor system health."""
    name = "system"

    def __init__(self, config: PulseConfig):
        self.config = config

    async def read(self) -> dict:
        """Check system health metrics using async subprocesses."""
        alerts = []

        # Memory pressure check (macOS) — async
        try:
            proc = await asyncio.create_subprocess_exec(
                "vm_stat",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode == 0:
                lines = stdout.decode().strip().split("\n")
                page_size = 16384  # default ARM64
                if lines and "page size of" in lines[0]:
                    m = re.search(r'page size of (\d+)', lines[0])
                    if m:
                        page_size = int(m.group(1))
                for line in lines:
                    if "Pages free" in line:
                        free_pages = int(line.split(":")[1].strip().rstrip("."))
                        free_mb = (free_pages * page_size) / (1024 * 1024)
                        if free_mb < 200:
                            alerts.append({
                                "type": "memory_pressure",
                                "free_mb": round(free_mb),
                                "severity": "high",
                            })
        except (asyncio.TimeoutError, OSError):
            pass

        # Process health check — async
        for proc_name in self.config.sensors.system.watch_processes:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "pgrep", "-f", proc_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.communicate(), timeout=5)
                if proc.returncode != 0:
                    alerts.append({
                        "type": "process_down",
                        "process": proc_name,
                        "severity": "medium",
                    })
            except (asyncio.TimeoutError, OSError):
                pass

        return {"alerts": alerts}
