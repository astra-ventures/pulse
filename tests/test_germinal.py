"""Tests for GERMINAL — Reproductive System / Self-Spawning Module Generator."""

import json
import time
import pytest
from pathlib import Path
from unittest.mock import patch

from pulse.src import germinal


class TestGerminalBasics:
    def test_default_state(self):
        state = germinal._default_state()
        assert state["total_births"] == 0
        assert state["births"] == []
        assert state["attempts"] == []
        assert state["in_progress"] is None
        assert state["cooldown_until"] == 0

    def test_should_run_interval(self):
        assert not germinal.should_run(0)
        assert not germinal.should_run(1)
        assert not germinal.should_run(199)
        assert germinal.should_run(200)
        assert germinal.should_run(400)
        assert germinal.should_run(600)
        assert not germinal.should_run(201)

    def test_get_status_returns_structure(self):
        status = germinal.get_status()
        assert "total_births" in status
        assert "birth_candidates" in status
        assert "candidates" in status
        assert "cooldown_active" in status
        assert "in_progress" in status


class TestArchetypes:
    def test_known_drives_have_archetypes(self):
        known = [
            "generate_revenue", "connection", "learn_new_skill",
            "ship_something", "reduce_stress", "explore",
            "realign_identity", "new_challenge",
        ]
        for drive in known:
            a = germinal.get_archetype(drive)
            assert a is not None
            assert "name" in a
            assert "purpose" in a
            assert "hook" in a

    def test_unknown_drive_gets_generic_archetype(self):
        a = germinal.get_archetype("some_totally_unknown_drive")
        assert a is not None
        assert len(a["name"]) > 0
        assert "hook" in a

    def test_generate_revenue_is_economic(self):
        a = germinal.get_archetype("generate_revenue")
        assert a["name"] == "ECONOMIC"

    def test_connection_is_nexus(self):
        a = germinal.get_archetype("connection")
        assert a["name"] == "NEXUS"

    def test_all_archetypes_have_valid_hooks(self):
        valid_hooks = {"pre_sense", "pre_evaluate", "pre_respond",
                       "post_trigger", "post_loop", "startup"}
        for drive, arch in germinal.DRIVE_ARCHETYPES.items():
            assert arch["hook"] in valid_hooks, f"{drive} has invalid hook: {arch['hook']}"


class TestSpecBuilding:
    def test_spec_has_required_fields(self):
        arch = germinal.DRIVE_ARCHETYPES["connection"]
        spec = germinal.build_module_spec("connection", arch)
        assert spec["drive"] == "connection"
        assert spec["module_name"] == "NEXUS"
        assert "module_file" in spec
        assert "state_file" in spec
        assert "hook" in spec
        assert "purpose" in spec
        assert "created_ts" in spec

    def test_spec_file_naming(self):
        arch = germinal.DRIVE_ARCHETYPES["generate_revenue"]
        spec = germinal.build_module_spec("generate_revenue", arch)
        assert spec["module_file"].endswith(".py")
        assert spec["state_file"].endswith(".json")

    def test_spec_has_template(self):
        arch = germinal.DRIVE_ARCHETYPES["explore"]
        spec = germinal.build_module_spec("explore", arch)
        assert "template" in spec
        assert len(spec["template"]) > 0


class TestBirthScan:
    def test_scan_returns_list(self):
        candidates = germinal.scan_for_birth_candidates()
        assert isinstance(candidates, list)

    def test_scan_graceful_on_missing_state(self):
        """Should return empty list if hypothalamus state doesn't exist."""
        original = germinal._DEFAULT_STATE_DIR / "hypothalamus-state.json"
        backup = germinal._DEFAULT_STATE_DIR / "hypothalamus-state.json.bak"
        
        if original.exists():
            original.rename(backup)
        try:
            candidates = germinal.scan_for_birth_candidates()
            assert candidates == []
        finally:
            if backup.exists():
                backup.rename(original)

    def test_scan_ignores_young_drives(self):
        """Drives younger than threshold should not be candidates."""
        hypo_file = germinal._DEFAULT_STATE_DIR / "hypothalamus-state.json"
        original = hypo_file.read_text() if hypo_file.exists() else None
        
        try:
            # Write a young drive
            hypo_file.write_text(json.dumps({
                "active_drives": {
                    "generate_revenue": {
                        "weight": 0.9,
                        "born_ts": time.time() - 86400,  # 1 day old, under threshold
                        "at_floor_since": None,
                        "last_active_ts": time.time(),
                        "source_modules": ["endocrine", "adipose", "vestibular"],
                    }
                },
                "pending_signals": {},
                "retired_drives": [],
                "last_scan": 0,
            }))
            candidates = germinal.scan_for_birth_candidates()
            assert not any(c["drive"] == "generate_revenue" for c in candidates)
        finally:
            if original:
                hypo_file.write_text(original)
            elif hypo_file.exists():
                hypo_file.unlink()

    def test_scan_finds_old_strong_drives(self):
        """Old, strong drives without a module should be candidates."""
        hypo_file = germinal._DEFAULT_STATE_DIR / "hypothalamus-state.json"
        original = hypo_file.read_text() if hypo_file.exists() else None
        
        try:
            hypo_file.write_text(json.dumps({
                "active_drives": {
                    "definitely_not_a_real_drive_xyz": {
                        "weight": 0.95,
                        "born_ts": time.time() - (8 * 86400),  # 8 days old
                        "at_floor_since": None,
                        "last_active_ts": time.time(),
                        "source_modules": ["endocrine", "adipose", "vestibular"],
                    }
                },
                "pending_signals": {},
                "retired_drives": [],
                "last_scan": 0,
            }))
            candidates = germinal.scan_for_birth_candidates()
            assert any(c["drive"] == "definitely_not_a_real_drive_xyz" for c in candidates)
        finally:
            if original:
                hypo_file.write_text(original)
            elif hypo_file.exists():
                hypo_file.unlink()


class TestAttemptBirth:
    def test_attempt_birth_blocked_by_cooldown(self):
        state = germinal._default_state()
        state["cooldown_until"] = time.time() + 86400  # 1 day from now
        germinal._save_state(state)
        
        result = germinal.attempt_birth("generate_revenue")
        assert result["ok"] is False
        assert "cooldown" in result["reason"]

    def test_attempt_birth_blocked_when_in_progress(self):
        state = germinal._default_state()
        state["in_progress"] = {"module_name": "ECONOMIC", "drive": "generate_revenue"}
        germinal._save_state(state)
        
        result = germinal.attempt_birth("connection")
        assert result["ok"] is False
        assert "in progress" in result["reason"]

    def test_record_birth_updates_state(self):
        state = germinal._default_state()
        germinal._save_state(state)
        
        germinal.record_birth("connection", "NEXUS", "nexus.py")
        status = germinal.get_status()
        assert status["total_births"] >= 1
        assert "NEXUS" in status["recent_births"]

    def test_record_failure_clears_in_progress(self):
        state = germinal._default_state()
        state["in_progress"] = {"module_name": "TEST"}
        germinal._save_state(state)
        
        germinal.record_failure("connection", "test failure")
        loaded = germinal._load_state()
        assert loaded["in_progress"] is None
        assert len(loaded["attempts"]) >= 1
