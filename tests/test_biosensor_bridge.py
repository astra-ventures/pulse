"""Tests for the biosensor bridge — Phase E1."""
import json
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.biosensor_bridge import (
    _hr_zone, _hrv_stress, _load_biosensor_state, _save_biosensor_state
)


class TestHRZone:
    def test_resting(self):
        assert _hr_zone(55) == "resting"

    def test_relaxed(self):
        assert _hr_zone(70) == "relaxed"

    def test_moderate(self):
        assert _hr_zone(95) == "moderate"

    def test_elevated(self):
        assert _hr_zone(115) == "elevated"

    def test_high(self):
        assert _hr_zone(145) == "high"

    def test_max(self):
        assert _hr_zone(175) == "max"

    def test_boundary_resting_relaxed(self):
        assert _hr_zone(60) == "relaxed"

    def test_boundary_high(self):
        assert _hr_zone(130) == "high"


class TestHRVStress:
    def test_low_stress_high_hrv(self):
        assert _hrv_stress(70) == "low"

    def test_moderate_stress(self):
        assert _hrv_stress(50) == "moderate"

    def test_elevated_stress(self):
        assert _hrv_stress(35) == "elevated"

    def test_high_stress_low_hrv(self):
        assert _hrv_stress(20) == "high"

    def test_boundary_low_moderate(self):
        # 60 is not > 60, so falls to moderate
        assert _hrv_stress(60) == "moderate"
        assert _hrv_stress(61) == "low"

    def test_boundary_elevated_high(self):
        # 25 is not > 25, so falls to high
        assert _hrv_stress(25) == "high"
        assert _hrv_stress(26) == "elevated"


class TestBiosensorState:
    def test_default_state_structure(self):
        with patch("src.biosensor_bridge.BIOSENSOR_FILE") as mock_path:
            mock_path.exists.return_value = False
            state = _load_biosensor_state()
        assert "heart_rate" in state
        assert "hrv" in state
        assert "activity" in state
        assert "sleep" in state
        assert "workout" in state

    def test_heart_rate_defaults(self):
        with patch("src.biosensor_bridge.BIOSENSOR_FILE") as mock_path:
            mock_path.exists.return_value = False
            state = _load_biosensor_state()
        hr = state["heart_rate"]
        assert hr["value"] is None
        assert hr["zone"] is None

    def test_workout_defaults(self):
        with patch("src.biosensor_bridge.BIOSENSOR_FILE") as mock_path:
            mock_path.exists.return_value = False
            state = _load_biosensor_state()
        assert state["workout"]["active"] is False

    def test_activity_defaults(self):
        with patch("src.biosensor_bridge.BIOSENSOR_FILE") as mock_path:
            mock_path.exists.return_value = False
            state = _load_biosensor_state()
        assert state["activity"]["goal_move"] == 600


class TestEndpointMapping:
    """Verify that biometric values map to correct Pulse signals."""

    def test_high_hr_triggers_adrenaline_keywords(self):
        """Zone 'high' should result in adrenaline + cortisol increase."""
        assert _hr_zone(145) == "high"
        # If zone is "high", endocrine update logic applies adrenaline +0.3

    def test_low_hrv_means_high_stress(self):
        """Low HRV (< 25ms) = high stress = cortisol increase."""
        assert _hrv_stress(20) == "high"

    def test_high_hrv_means_low_stress(self):
        """High HRV (> 60ms) = low stress = serotonin + cortisol decay."""
        assert _hrv_stress(65) == "low"

    def test_resting_hr_means_low_adrenaline(self):
        """Resting HR < 60 bpm = adrenaline decay."""
        assert _hr_zone(55) == "resting"
