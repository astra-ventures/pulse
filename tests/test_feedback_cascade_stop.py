"""Tests for cascade_stop feedback outcome — full drive decay on anti-cascade trigger."""

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Helper: create a minimal fake daemon with drive state
# ---------------------------------------------------------------------------

def _make_drive(pressure: float, weight: float = 1.0):
    """Create a minimal Drive-like object."""
    from src.drives.engine import Drive
    d = Drive(name="test", category="test", pressure=pressure, weight=weight)
    return d


def _make_daemon_with_drives(drives_dict: dict):
    """Return a minimal daemon mock with real drive objects."""
    from src.drives.engine import Drive

    daemon = MagicMock()
    daemon.drives = MagicMock()
    real_drives = {}
    for name, cfg in drives_dict.items():
        d = Drive(
            name=name,
            category=name,
            pressure=cfg["pressure"],
            weight=cfg.get("weight", 1.0),
        )
        real_drives[name] = d
    daemon.drives.drives = real_drives
    daemon.state = MagicMock()
    daemon.daily_sync = None  # disable file logging
    return daemon


# ---------------------------------------------------------------------------
# Unit tests: health.py _handle_feedback route logic
# ---------------------------------------------------------------------------

class TestCascadeStopFeedback:
    """Verify cascade_stop outcome decays ALL drives to zero."""

    def _apply_feedback(self, daemon, outcome: str, drives_addressed: list, summary: str = ""):
        """Simulate the feedback endpoint logic directly (without HTTP)."""
        import time as _time
        now = _time.time()
        results = {}

        if outcome == "cascade_stop":
            for drive_name, drive in daemon.drives.drives.items():
                before = drive.pressure
                drive.decay(drive.pressure)  # full decay
                drive.last_addressed = now
                results[drive_name] = {
                    "before": round(before, 4),
                    "after": round(drive.pressure, 4),
                }
        else:
            for drive_name in drives_addressed:
                if drive_name in daemon.drives.drives:
                    drive = daemon.drives.drives[drive_name]
                    before = drive.pressure
                    if outcome == "success":
                        decay_amount = min(drive.pressure, drive.pressure * 0.7)
                    elif outcome == "partial":
                        decay_amount = min(drive.pressure, drive.pressure * 0.4)
                    else:
                        decay_amount = 0.0
                    drive.decay(decay_amount)
                    drive.last_addressed = now
                    results[drive_name] = {
                        "before": round(before, 4),
                        "after": round(drive.pressure, 4),
                    }

        return results

    def test_cascade_stop_decays_all_drives_to_zero(self):
        """cascade_stop must zero out every drive regardless of drives_addressed."""
        daemon = _make_daemon_with_drives({
            "goals":     {"pressure": 0.200, "weight": 1.00},
            "system":    {"pressure": 0.150, "weight": 1.50},
            "unfinished":{"pressure": 0.090, "weight": 0.90},
            "emotions":  {"pressure": 0.080, "weight": 0.80},
            "social":    {"pressure": 0.077, "weight": 0.40},
            "growth":    {"pressure": 0.075, "weight": 0.50},
            "curiosity": {"pressure": 0.074, "weight": 0.60},
        })

        results = self._apply_feedback(daemon, "cascade_stop", drives_addressed=[])

        for name, drive in daemon.drives.drives.items():
            assert drive.pressure == 0.0, f"Drive '{name}' should be 0.0 after cascade_stop, got {drive.pressure}"

    def test_cascade_stop_decays_all_even_with_drives_addressed_list(self):
        """drives_addressed is ignored for cascade_stop — all drives still decay."""
        daemon = _make_daemon_with_drives({
            "goals":   {"pressure": 0.5, "weight": 1.0},
            "system":  {"pressure": 0.3, "weight": 1.5},
            "growth":  {"pressure": 0.2, "weight": 0.5},
        })

        # Even if only "system" is listed, all should decay
        results = self._apply_feedback(daemon, "cascade_stop", drives_addressed=["system"])

        for name, drive in daemon.drives.drives.items():
            assert drive.pressure == 0.0, f"Drive '{name}' should be 0.0 after cascade_stop"

    def test_cascade_stop_returns_before_after_for_all_drives(self):
        """Results dict should contain every drive, not just addressed ones."""
        daemon = _make_daemon_with_drives({
            "goals":   {"pressure": 0.2, "weight": 1.0},
            "system":  {"pressure": 0.15, "weight": 1.5},
            "growth":  {"pressure": 0.1, "weight": 0.5},
        })

        results = self._apply_feedback(daemon, "cascade_stop", drives_addressed=[])

        assert set(results.keys()) == {"goals", "system", "growth"}
        for name, r in results.items():
            assert r["before"] > 0.0
            assert r["after"] == 0.0

    def test_cascade_stop_with_zero_pressure_drives_is_safe(self):
        """Drives already at zero should not go negative."""
        daemon = _make_daemon_with_drives({
            "goals":   {"pressure": 0.0, "weight": 1.0},
            "system":  {"pressure": 0.15, "weight": 1.5},
        })

        results = self._apply_feedback(daemon, "cascade_stop", drives_addressed=[])

        assert daemon.drives.drives["goals"].pressure == 0.0
        assert daemon.drives.drives["system"].pressure == 0.0

    def test_success_outcome_only_decays_listed_drives(self):
        """success outcome must NOT decay unlisted drives (existing behavior preserved)."""
        daemon = _make_daemon_with_drives({
            "goals":  {"pressure": 0.4, "weight": 1.0},
            "system": {"pressure": 0.3, "weight": 1.5},
            "growth": {"pressure": 0.2, "weight": 0.5},
        })

        original_growth = daemon.drives.drives["growth"].pressure
        self._apply_feedback(daemon, "success", drives_addressed=["goals", "system"])

        # growth should be unchanged
        assert daemon.drives.drives["growth"].pressure == pytest.approx(original_growth)
        # goals and system should have decayed 70%
        assert daemon.drives.drives["goals"].pressure == pytest.approx(0.4 * 0.3, abs=1e-6)
        assert daemon.drives.drives["system"].pressure == pytest.approx(0.3 * 0.3, abs=1e-6)

    def test_combined_pressure_below_threshold_after_cascade_stop(self):
        """After cascade_stop, combined weighted pressure should be well below 0.7."""
        drives_cfg = {
            "goals":     {"pressure": 0.200, "weight": 1.00},
            "system":    {"pressure": 0.150, "weight": 1.50},
            "unfinished":{"pressure": 0.090, "weight": 0.90},
            "emotions":  {"pressure": 0.080, "weight": 0.80},
            "social":    {"pressure": 0.077, "weight": 0.40},
            "growth":    {"pressure": 0.075, "weight": 0.50},
            "curiosity": {"pressure": 0.074, "weight": 0.60},
        }
        daemon = _make_daemon_with_drives(drives_cfg)

        # Verify pre-condition: combined was near threshold
        pre_combined = sum(
            d.pressure * d.weight for d in daemon.drives.drives.values()
        )
        assert pre_combined > 0.5, f"Pre-condition failed: combined={pre_combined}"

        self._apply_feedback(daemon, "cascade_stop", drives_addressed=[])

        post_combined = sum(
            d.pressure * d.weight for d in daemon.drives.drives.values()
        )
        assert post_combined == 0.0, f"Expected 0.0 after cascade_stop, got {post_combined}"

    def test_blocked_outcome_decays_nothing(self):
        """blocked outcome should not decay anything (existing behavior)."""
        daemon = _make_daemon_with_drives({
            "goals":  {"pressure": 0.5, "weight": 1.0},
            "system": {"pressure": 0.3, "weight": 1.5},
        })

        self._apply_feedback(daemon, "blocked", drives_addressed=["goals"])

        assert daemon.drives.drives["goals"].pressure == pytest.approx(0.5)
        assert daemon.drives.drives["system"].pressure == pytest.approx(0.3)

    def test_partial_outcome_decays_40_percent(self):
        """partial outcome decays listed drives by 40% (existing behavior)."""
        daemon = _make_daemon_with_drives({
            "goals":  {"pressure": 0.5, "weight": 1.0},
            "system": {"pressure": 0.3, "weight": 1.5},
        })

        self._apply_feedback(daemon, "partial", drives_addressed=["goals"])

        expected = 0.5 * 0.6  # 0.5 - (0.5 * 0.4) = 0.3
        assert daemon.drives.drives["goals"].pressure == pytest.approx(expected, abs=1e-6)
        # system untouched
        assert daemon.drives.drives["system"].pressure == pytest.approx(0.3)
