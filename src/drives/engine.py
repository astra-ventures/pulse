"""
Drive Engine — internal motivation system.

Drives accumulate pressure over time based on:
- Unfulfilled goals (the longer ignored, the louder they get)
- Curiosity (open questions create exploration urges)  
- Emotions (strong feelings amplify related drives)
- Unfinished business (untested hypotheses nag)
- External signals (sensor events spike relevant drives)

This is the synthetic equivalent of "wanting to do something."
"""

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from pulse.src.core.config import PulseConfig
from pulse.src.state.persistence import StatePersistence

logger = logging.getLogger("pulse.drives")


@dataclass
class Drive:
    """A single drive — an internal motivation with accumulating pressure."""
    name: str
    category: str
    pressure: float = 0.0
    weight: float = 1.0
    last_addressed: float = 0.0  # timestamp
    source_data: dict = field(default_factory=dict)
    
    @property
    def weighted_pressure(self) -> float:
        return self.pressure * self.weight

    def tick(self, dt: float, rate: float, max_pressure: float):
        """Accumulate pressure over time. Rate is per-minute."""
        self.pressure = min(max_pressure, self.pressure + (rate * (dt / 60.0) * self.weight))

    def decay(self, amount: float):
        """Reduce pressure (after being addressed)."""
        self.pressure = max(0.0, self.pressure - amount)

    def spike(self, amount: float, max_pressure: float):
        """Immediate pressure increase from external event."""
        self.pressure = min(max_pressure, self.pressure + amount)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "pressure": round(self.pressure, 4),
            "weight": self.weight,
            "last_addressed": self.last_addressed,
        }


@dataclass
class DriveState:
    """Snapshot of all drives at a point in time."""
    drives: List[Drive]
    timestamp: float
    total_pressure: float = 0.0
    top_drive: Optional[Drive] = None

    def __post_init__(self):
        if self.drives:
            self.total_pressure = sum(d.weighted_pressure for d in self.drives)
            self.top_drive = max(self.drives, key=lambda d: d.weighted_pressure)


class DriveEngine:
    """Manages all drives and their pressure accumulation."""

    def __init__(self, config: PulseConfig, state: StatePersistence):
        self.config = config
        self.state = state
        self.drives: Dict[str, Drive] = {}
        self.last_tick_time = time.time()
        self._source_cache: Dict[str, tuple] = {}  # path -> (mtime, data)
        
        # Initialize drives from config categories
        for name, cat in config.drives.categories.items():
            self.drives[name] = Drive(
                name=name,
                category=name,
                weight=cat.weight,
            )

    def tick(self, sensor_data: dict) -> DriveState:
        """
        Update all drives. Called every loop iteration.
        Pure state transitions + sensor spikes. File I/O is separate.
        """
        now = time.time()
        dt = now - self.last_tick_time
        self.last_tick_time = now

        # Base pressure accumulation (time-based)
        for drive in self.drives.values():
            drive.tick(
                dt=dt,
                rate=self.config.drives.pressure_rate,
                max_pressure=self.config.drives.max_pressure,
            )

        # Sensor-driven spikes
        self._apply_sensor_spikes(sensor_data)

        # Build state snapshot
        return DriveState(
            drives=list(self.drives.values()),
            timestamp=now,
        )

    def refresh_sources(self):
        """Read workspace source files and apply drive adjustments. 
        Separated from tick() to isolate I/O from state transitions."""
        self._refresh_sources()

    def _apply_sensor_spikes(self, sensor_data: dict):
        """Apply pressure spikes from sensor events."""
        # File changes → goal/curiosity drives
        if sensor_data.get("filesystem", {}).get("changes"):
            if "goals" in self.drives:
                self.drives["goals"].spike(0.1, self.config.drives.max_pressure)

        # Discord silence → social drive
        if sensor_data.get("discord", {}).get("silent_agents"):
            if "social" in self.drives:
                self.drives["social"].spike(0.2, self.config.drives.max_pressure)

        # System health issues → spike system drive (max once per min_trigger_interval)
        system_alerts = sensor_data.get("system", {}).get("alerts", [])
        if system_alerts:
            if "system" not in self.drives:
                self.drives["system"] = Drive(
                    name="system", category="system", weight=1.5
                )
            now = time.time()
            cooldown = getattr(self.config.openclaw, 'min_trigger_interval', 300)
            since_addressed = now - self.drives["system"].last_addressed
            if since_addressed > cooldown and self.drives["system"].pressure < 1.0:
                self.drives["system"].spike(0.5, self.config.drives.max_pressure)
                logger.debug(f"System alert spike: {[a.get('type') for a in system_alerts]}")
            else:
                logger.debug(f"System alert suppressed (addressed {since_addressed:.0f}s ago, pressure={self.drives['system'].pressure:.2f})")

    def _read_cached_json(self, path: Path) -> tuple[Optional[dict], bool]:
        """Read a JSON file with mtime caching. Returns (data, changed) tuple.
        changed=True only on first read or when file mtime differs from cache."""
        if not path.exists():
            return None, False
        try:
            mtime = path.stat().st_mtime
            cached = self._source_cache.get(str(path))
            if cached and cached[0] == mtime:
                return cached[1], False  # same data, not changed
            data = json.loads(path.read_text())
            self._source_cache[str(path)] = (mtime, data)
            return data, True  # new or changed
        except Exception:
            return None, False

    def _refresh_sources(self):
        """Read workspace files to update drive context.
        Source-based spikes ONLY fire when the source file actually changes,
        not on every tick. This prevents runaway pressure accumulation."""
        workspace = self.config.workspace

        # Hypotheses — spike unfinished only when hypotheses file changes
        data, changed = self._read_cached_json(workspace.resolve_path("hypotheses"))
        if data and changed:
            items = data if isinstance(data, list) else data.get("hypotheses", [])
            untested = [h for h in items if isinstance(h, dict) and not h.get("outcome")]
            if untested and "unfinished" in self.drives:
                boost = min(0.1, len(untested) * 0.02)
                self.drives["unfinished"].spike(boost, self.config.drives.max_pressure)
                logger.debug(f"Hypotheses changed: {len(untested)} untested, spiked unfinished +{boost:.3f}")

        # Emotions — spike only when emotional state file changes
        data, changed = self._read_cached_json(workspace.resolve_path("emotions"))
        if data and changed and isinstance(data, dict) and data.get("intensity", 0) > 0.7 and "emotions" in self.drives:
            self.drives["emotions"].spike(0.15, self.config.drives.max_pressure)
            logger.debug(f"Emotional state changed: intensity={data.get('intensity')}, spiked emotions +0.15")

    def on_trigger_success(self, decision):
        """Called after a successful agent turn. Decay all drives proportionally."""
        decay_total = self.config.drives.success_decay
        now = time.time()

        # Scale decay proportionally when total pressure is high
        if self.config.drives.adaptive_decay and decision.total_pressure > 5.0:
            pressure_multiplier = min(3.0, decision.total_pressure / 5.0)
            decay_total = decay_total * pressure_multiplier

        if decision.total_pressure > 0:
            for drive in self.drives.values():
                if drive.pressure > 0:
                    # Proportional decay — higher pressure drives lose more
                    proportion = drive.weighted_pressure / decision.total_pressure
                    drive.decay(decay_total * proportion * 2)

        # Mark top drive as addressed
        if decision.top_drive and decision.top_drive.name in self.drives:
            self.drives[decision.top_drive.name].last_addressed = now
            logger.info(
                f"Drives decayed after successful turn. "
                f"Top drive '{decision.top_drive.name}' addressed."
            )

    def on_trigger_failure(self, decision):
        """Called after a failed trigger. Boost frustration."""
        if decision.top_drive and decision.top_drive.name in self.drives:
            drive = self.drives[decision.top_drive.name]
            drive.spike(
                self.config.drives.failure_boost,
                self.config.drives.max_pressure,
            )
            logger.warning(
                f"Drive '{drive.name}' boosted to {drive.pressure:.2f} "
                f"after failed trigger (frustration)"
            )

    def restore_state(self):
        """Restore drive pressures and runtime-added drives from persisted state."""
        saved = self.state.get("drives", {})
        for name, data in saved.items():
            if name in self.drives:
                self.drives[name].pressure = data.get("pressure", 0.0)
                self.drives[name].weight = data.get("weight", self.drives[name].weight)
                self.drives[name].last_addressed = data.get("last_addressed", 0.0)
            else:
                # Restore runtime-added drives (from mutations)
                self.drives[name] = Drive(
                    name=name,
                    category=data.get("category", name),
                    pressure=data.get("pressure", 0.0),
                    weight=data.get("weight", 0.5),
                    last_addressed=data.get("last_addressed", 0.0),
                )
                logger.info(f"Restored runtime drive: {name} (weight={data.get('weight', 0.5)})")
        logger.info(f"Restored {len(saved)} drive states")

    def save_state(self) -> dict:
        """Serialize drive state for persistence."""
        return {
            name: drive.to_dict()
            for name, drive in self.drives.items()
        }
