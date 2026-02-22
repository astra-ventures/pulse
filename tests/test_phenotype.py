"""Tests for PHENOTYPE — Communication Style Adaptation."""

import json
from unittest.mock import patch

import pytest

from pulse.src import phenotype, thalamus


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    bf = tmp_path / "thalamus.jsonl"
    sf = tmp_path / "phenotype-state.json"
    with patch.object(phenotype, "STATE_DIR", tmp_path), \
         patch.object(phenotype, "STATE_FILE", sf), \
         patch.object(thalamus, "STATE_DIR", tmp_path), \
         patch.object(thalamus, "BROADCAST_FILE", bf):
        yield tmp_path


class TestComputePhenotype:
    def test_default_phenotype(self):
        p = phenotype.compute_phenotype()
        assert "tone" in p
        assert "humor" in p
        assert 0 <= p["humor"] <= 1
        assert 0 <= p["intensity"] <= 1

    def test_wired_state(self):
        mood = {"hormones": {"cortisol": 0.7, "dopamine": 0.7, "oxytocin": 0.1, "adrenaline": 0.0, "melatonin": 0.0}, "label": "wired"}
        p = phenotype.compute_phenotype(mood=mood)
        assert p["tone"] == "wired"
        assert p["sentence_length"] == "short"
        assert p["intensity"] >= 0.7

    def test_vulnerable_twilight(self):
        mood = {"hormones": {"cortisol": 0.1, "dopamine": 0.2, "oxytocin": 0.6, "adrenaline": 0.0, "melatonin": 0.1}, "label": "bonded"}
        p = phenotype.compute_phenotype(mood=mood, circadian_mode="twilight")
        assert p["tone"] == "vulnerable"
        assert p["sentence_length"] == "long"
        assert p["vulnerability"] >= 0.5

    def test_urgent_threat(self):
        threat = {"threat_level": 0.8, "threat_type": "credential_leak"}
        p = phenotype.compute_phenotype(threat=threat)
        assert p["tone"] == "urgent"
        assert p["humor"] == 0.0

    def test_contemplative_post_rem(self):
        mood = {"hormones": {"cortisol": 0.1, "dopamine": 0.2, "oxytocin": 0.2, "adrenaline": 0.0, "melatonin": 0.1}, "label": "neutral"}
        p = phenotype.compute_phenotype(mood=mood, circadian_mode="dawn")
        assert p["tone"] == "contemplative"

    def test_afterimage_influence(self):
        afterimages = [{"emotion": "anguish", "current_intensity": 5.0}]
        p = phenotype.compute_phenotype(afterimages=afterimages)
        assert p["intensity"] >= 0.5

    def test_broadcasts_shift(self):
        phenotype.compute_phenotype()  # neutral
        mood = {"hormones": {"cortisol": 0.7, "dopamine": 0.7, "oxytocin": 0.1, "adrenaline": 0.0, "melatonin": 0.0}, "label": "wired"}
        phenotype.compute_phenotype(mood=mood)
        entries = thalamus.read_by_source("phenotype")
        assert any(e["type"] == "shift" for e in entries)


class TestGetCurrent:
    def test_returns_dict(self):
        phenotype.compute_phenotype()
        current = phenotype.get_current()
        assert "tone" in current

    def test_history(self):
        phenotype.compute_phenotype()
        phenotype.compute_phenotype()
        history = phenotype.get_history()
        assert len(history) >= 1
