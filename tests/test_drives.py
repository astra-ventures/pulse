"""Tests for Drive Engine — pressure accumulation, decay, and state snapshots."""

import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.drives.engine import Drive, DriveState


class TestDrive:
    """Test individual drive mechanics."""

    def test_initial_pressure_is_zero(self):
        d = Drive(name="goals", category="goals")
        assert d.pressure == 0.0

    def test_tick_increases_pressure(self):
        d = Drive(name="goals", category="goals", weight=1.0)
        d.tick(dt=60.0, rate=0.5, max_pressure=5.0)
        assert d.pressure > 0.0

    def test_tick_respects_max_pressure(self):
        d = Drive(name="goals", category="goals", weight=1.0, pressure=4.9)
        d.tick(dt=600.0, rate=1.0, max_pressure=5.0)
        assert d.pressure == 5.0

    def test_decay_reduces_pressure(self):
        d = Drive(name="goals", category="goals", pressure=3.0)
        d.decay(1.5)
        assert d.pressure == 1.5

    def test_decay_cannot_go_negative(self):
        d = Drive(name="goals", category="goals", pressure=1.0)
        d.decay(5.0)
        assert d.pressure == 0.0

    def test_spike_increases_pressure(self):
        d = Drive(name="goals", category="goals", pressure=1.0)
        d.spike(2.0, max_pressure=5.0)
        assert d.pressure == 3.0

    def test_spike_capped_at_max(self):
        d = Drive(name="goals", category="goals", pressure=4.0)
        d.spike(3.0, max_pressure=5.0)
        assert d.pressure == 5.0

    def test_weighted_pressure(self):
        d = Drive(name="goals", category="goals", pressure=2.0, weight=1.5)
        assert d.weighted_pressure == 3.0

    def test_to_dict_roundtrip(self):
        d = Drive(name="goals", category="goals", pressure=1.234, weight=0.8)
        data = d.to_dict()
        assert data["name"] == "goals"
        assert data["pressure"] == 1.234
        assert data["weight"] == 0.8


class TestDriveState:
    """Test drive state snapshots."""

    def test_total_pressure_sum(self):
        drives = [
            Drive(name="goals", category="goals", pressure=2.0, weight=1.0),
            Drive(name="curiosity", category="curiosity", pressure=1.0, weight=1.0),
        ]
        state = DriveState(drives=drives, timestamp=time.time())
        assert state.total_pressure == 3.0

    def test_top_drive_selection(self):
        drives = [
            Drive(name="goals", category="goals", pressure=1.0, weight=1.0),
            Drive(name="curiosity", category="curiosity", pressure=3.0, weight=1.0),
        ]
        state = DriveState(drives=drives, timestamp=time.time())
        assert state.top_drive.name == "curiosity"

    def test_top_drive_considers_weight(self):
        drives = [
            Drive(name="goals", category="goals", pressure=2.0, weight=2.0),  # weighted=4
            Drive(name="curiosity", category="curiosity", pressure=3.0, weight=1.0),  # weighted=3
        ]
        state = DriveState(drives=drives, timestamp=time.time())
        assert state.top_drive.name == "goals"

    def test_empty_drives(self):
        state = DriveState(drives=[], timestamp=time.time())
        assert state.total_pressure == 0.0
        assert state.top_drive is None

    def test_pressure_accumulation_over_time(self):
        """Simulate multiple ticks and verify monotonic increase."""
        d = Drive(name="goals", category="goals", weight=1.0)
        pressures = []
        for _ in range(10):
            d.tick(dt=30.0, rate=0.5, max_pressure=5.0)
            pressures.append(d.pressure)
        # Should be monotonically increasing
        assert all(pressures[i] <= pressures[i + 1] for i in range(len(pressures) - 1))
