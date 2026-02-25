"""Tests for SOMA — Physical State Simulator."""

import json
from unittest.mock import patch

import pytest

from pulse.src import soma, thalamus


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    bf = tmp_path / "thalamus.jsonl"
    sf = tmp_path / "soma-state.json"
    with patch.object(soma, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(soma, "_DEFAULT_STATE_FILE", sf), \
         patch.object(thalamus, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(thalamus, "_DEFAULT_BROADCAST_FILE", bf):
        yield tmp_path


class TestEnergy:
    def test_initial_energy(self):
        status = soma.get_status()
        assert status["energy"] == 1.0

    def test_spend_energy(self):
        result = soma.spend_energy(500)
        assert result["energy"] < 1.0
        assert result["energy"] == pytest.approx(0.5, abs=0.01)

    def test_energy_clamps_at_zero(self):
        soma.spend_energy(2000)
        status = soma.get_status()
        assert status["energy"] == 0.0

    def test_replenish(self):
        soma.spend_energy(800)
        result = soma.replenish(0.5, "rem")
        assert result["energy"] > 0.2


class TestPosture:
    def test_leaning_in(self):
        assert soma.update_posture(0.8) == "leaning_in"

    def test_leaning_back(self):
        assert soma.update_posture(0.2) == "leaning_back"

    def test_neutral(self):
        assert soma.update_posture(0.5) == "neutral"


class TestTemperature:
    def test_hot_adrenaline(self):
        assert soma.update_temperature({"adrenaline": 0.6}) == "hot"

    def test_warm_oxytocin(self):
        assert soma.update_temperature({"oxytocin": 0.6, "cortisol": 0.1, "dopamine": 0.1}) == "warm"

    def test_cool_cortisol(self):
        assert soma.update_temperature({"cortisol": 0.6, "dopamine": 0.1, "oxytocin": 0.1, "adrenaline": 0.0}) == "cool"

    def test_cold_all_low(self):
        assert soma.update_temperature({"cortisol": 0.1, "dopamine": 0.1, "oxytocin": 0.1, "adrenaline": 0.0}) == "cold"
