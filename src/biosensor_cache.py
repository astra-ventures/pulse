"""
BiosensorCache — Thread-safe reader for Apple Watch biometric data.

Reads from ~/.pulse/state/biosensor-state.json which is written by
biosensor_bridge.py when iPhone Shortcuts POSTs HealthKit data.

Design: purely file-based, no coupling to bridge internals.
Freshness: data older than MAX_AGE_SECONDS is treated as stale and ignored.

Usage:
    from pulse.src.biosensor_cache import BiosensorCache
    bio = BiosensorCache()
    data = bio.read()          # returns dict or None if no bridge / stale
    hr = bio.heart_rate()      # returns bpm float or None
    hrv = bio.hrv()            # returns ms float or None
    zone = bio.hr_zone()       # returns "resting"|"relaxed"|"moderate"|"elevated"|"high"|"max" or None
    stress = bio.hrv_stress()  # returns "low"|"moderate"|"elevated"|"high" or None
"""

import json
import threading
import time
from pathlib import Path
from typing import Optional

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_BIOSENSOR_FILE = _DEFAULT_STATE_DIR / "biosensor-state.json"

# Data older than this is treated as stale — no biometric updates
MAX_AGE_SECONDS = 300  # 5 minutes


class BiosensorCache:
    """Thread-safe reader for biosensor-state.json.

    Instantiate once and call read() / helper methods.
    Cache TTL: 10 seconds (re-reads file at most once per 10s).
    """

    _lock = threading.Lock()
    _instance_cache: dict = {"data": None, "ts": 0.0}

    def __init__(
        self,
        state_file: Optional[Path] = None,
        max_age_seconds: int = MAX_AGE_SECONDS,
    ):
        self._file = Path(state_file) if state_file else _DEFAULT_BIOSENSOR_FILE
        self._max_age = max_age_seconds
        self._local_ttl = 10.0  # seconds before re-reading file

    def read(self) -> Optional[dict]:
        """Return current biosensor state dict, or None if missing / stale.

        "Stale" means the bridge hasn't updated the file in > max_age_seconds.
        """
        with BiosensorCache._lock:
            now = time.time()
            # Re-read file if cache is expired
            if now - BiosensorCache._instance_cache["ts"] > self._local_ttl:
                raw = self._read_file()
                BiosensorCache._instance_cache = {"data": raw, "ts": now}
            return BiosensorCache._instance_cache["data"]

    def _read_file(self) -> Optional[dict]:
        """Read and validate biosensor-state.json."""
        if not self._file.exists():
            return None
        try:
            data = json.loads(self._file.read_text())
        except (json.JSONDecodeError, OSError):
            return None

        # Check overall freshness
        last_update = data.get("last_update")
        if last_update is None:
            return None
        if time.time() - last_update > self._max_age:
            return None  # bridge has stopped sending data

        return data

    def is_active(self) -> bool:
        """True if bridge is running and sending fresh data."""
        return self.read() is not None

    def heart_rate(self) -> Optional[float]:
        """Return latest heart rate in BPM, or None."""
        data = self.read()
        if data is None:
            return None
        hr = data.get("heart_rate", {})
        # Individual field freshness check
        ts = hr.get("ts")
        if ts and time.time() - ts > self._max_age:
            return None
        return hr.get("value")

    def hr_zone(self) -> Optional[str]:
        """Return HR zone: resting|relaxed|moderate|elevated|high|max, or None."""
        data = self.read()
        if data is None:
            return None
        return data.get("heart_rate", {}).get("zone")

    def hrv(self) -> Optional[float]:
        """Return latest HRV in milliseconds, or None."""
        data = self.read()
        if data is None:
            return None
        hrv = data.get("hrv", {})
        ts = hrv.get("ts")
        if ts and time.time() - ts > self._max_age:
            return None
        return hrv.get("value")

    def hrv_stress(self) -> Optional[str]:
        """Return HRV stress level: low|moderate|elevated|high, or None."""
        data = self.read()
        if data is None:
            return None
        return data.get("hrv", {}).get("stress_level")

    def activity(self) -> Optional[dict]:
        """Return activity rings dict {move, exercise, stand, goal_move}, or None."""
        data = self.read()
        if data is None:
            return None
        act = data.get("activity", {})
        ts = act.get("ts")
        if ts and time.time() - ts > self._max_age:
            return None
        return act

    def move_ring_pct(self) -> Optional[float]:
        """Return move ring completion 0.0–1.0, or None."""
        act = self.activity()
        if act is None:
            return None
        goal = act.get("goal_move", 0)
        if goal <= 0:
            return None
        return min(1.0, act.get("move", 0) / goal)

    def sleep(self) -> Optional[dict]:
        """Return sleep dict {stage, minutes}, or None."""
        data = self.read()
        if data is None:
            return None
        sleep = data.get("sleep", {})
        if not sleep.get("stage"):
            return None
        return sleep

    def workout(self) -> Optional[dict]:
        """Return workout dict {active, activity}, or None."""
        data = self.read()
        if data is None:
            return None
        w = data.get("workout", {})
        return w if w.get("active") else None

    def invalidate(self):
        """Force re-read on next access (for testing)."""
        with BiosensorCache._lock:
            BiosensorCache._instance_cache = {"data": None, "ts": 0.0}
