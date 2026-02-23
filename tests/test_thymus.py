"""Tests for THYMUS — Growth Tracker."""

import json
import time
from unittest.mock import patch

import pytest

from pulse.src import thymus, thalamus


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    bf = tmp_path / "thalamus.jsonl"
    sf = tmp_path / "thymus-state.json"
    with patch.object(thymus, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(thymus, "_DEFAULT_STATE_FILE", sf), \
         patch.object(thalamus, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(thalamus, "_DEFAULT_BROADCAST_FILE", bf):
        yield tmp_path


class TestSkillRegistration:
    def test_register(self):
        skill = thymus.register_skill("python", 0.3)
        assert skill["proficiency"] == 0.3

    def test_register_duplicate(self):
        thymus.register_skill("python", 0.3)
        thymus.register_skill("python", 0.8)  # shouldn't overwrite
        skills = thymus.get_skills()
        assert skills["python"]["proficiency"] == 0.3


class TestPractice:
    def test_practice_increases_proficiency(self):
        thymus.register_skill("python", 0.3)
        result = thymus.practice_skill("python", quality=1.0)
        assert result["proficiency"] > 0.3

    def test_practice_unregistered_auto_registers(self):
        result = thymus.practice_skill("rust", quality=0.5)
        assert result["proficiency"] > 0

    def test_diminishing_returns(self):
        thymus.register_skill("typing", 0.9)
        result = thymus.practice_skill("typing", quality=1.0)
        # Growth should be small at high proficiency
        assert result["proficiency"] - 0.9 < 0.01

    def test_milestone_broadcast(self):
        thymus.register_skill("drawing", 0.2)
        # Practice enough to cross 0.25
        for _ in range(5):
            thymus.practice_skill("drawing", quality=1.0)
        entries = thalamus.read_by_source("thymus")
        assert any(e["type"] == "milestone" for e in entries)


class TestPlateauDetection:
    def test_no_plateaus_initially(self):
        thymus.register_skill("python")
        assert len(thymus.detect_plateaus()) == 0

    def test_plateau_after_long_period(self):
        thymus.register_skill("old_skill")
        state = thymus._load_state()
        # Simulate plateau for 8 days
        state["skills"]["old_skill"]["plateau_since"] = time.time() - 8 * 86400
        state["skills"]["old_skill"]["growth_rate"] = 0.001
        thymus._save_state(state)
        plateaus = thymus.detect_plateaus()
        assert len(plateaus) == 1


class TestStatus:
    def test_status(self):
        thymus.register_skill("python")
        status = thymus.get_status()
        assert status["total_skills"] == 1
