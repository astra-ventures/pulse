"""Tests for GAP #2 — state_dir isolation through NervousSystem."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from pulse.src.nervous_system import NervousSystem, _DEFAULT_STATE_DIR


class TestStateIsolation:
    """NervousSystem(state_dir=X) should redirect module state files."""

    def test_default_state_dir(self):
        ns = NervousSystem()
        assert ns.state_dir == _DEFAULT_STATE_DIR

    def test_custom_state_dir(self, tmp_path):
        custom = tmp_path / "companion_a" / "state"
        ns = NervousSystem(state_dir=custom)
        assert ns.state_dir == custom

    def test_modules_use_custom_state_dir(self, tmp_path):
        """Module-level _DEFAULT_STATE_DIR gets patched when state_dir passed."""
        custom = tmp_path / "companion_b" / "state"
        ns = NervousSystem(state_dir=custom)

        # Functional modules should have their _DEFAULT_STATE_DIR rewritten
        if ns._mod_endocrine:
            assert ns._mod_endocrine._DEFAULT_STATE_DIR == custom
        if ns._mod_soma:
            assert ns._mod_soma._DEFAULT_STATE_DIR == custom
        if ns._mod_thalamus:
            assert ns._mod_thalamus._DEFAULT_STATE_DIR == custom

    def test_state_files_point_to_custom_dir(self, tmp_path):
        """_DEFAULT_STATE_FILE paths should be under the custom state_dir."""
        custom = tmp_path / "companion_c" / "state"
        ns = NervousSystem(state_dir=custom)

        if ns._mod_endocrine and hasattr(ns._mod_endocrine, "_DEFAULT_STATE_FILE"):
            assert str(ns._mod_endocrine._DEFAULT_STATE_FILE).startswith(str(custom))
        if ns._mod_limbic and hasattr(ns._mod_limbic, "_DEFAULT_STATE_FILE"):
            assert str(ns._mod_limbic._DEFAULT_STATE_FILE).startswith(str(custom))

    def test_two_instances_isolated(self, tmp_path):
        """Two NervousSystem instances with different state_dirs stay isolated."""
        dir_a = tmp_path / "a" / "state"
        dir_b = tmp_path / "b" / "state"
        ns_a = NervousSystem(state_dir=dir_a)
        ns_b = NervousSystem(state_dir=dir_b)

        assert ns_a.state_dir != ns_b.state_dir

        # Both should function independently
        status_a = ns_a.get_status()
        status_b = ns_b.get_status()
        assert isinstance(status_a, dict)
        assert isinstance(status_b, dict)

    def test_warm_up_creates_files_in_custom_dir(self, tmp_path):
        """warm_up() should write state files under the custom state_dir."""
        custom = tmp_path / "warm" / "state"
        ns = NervousSystem(state_dir=custom)
        ns.warm_up()

        # At least some state files should exist under custom dir
        if custom.exists():
            files = list(custom.glob("*.json"))
            assert len(files) > 0, "warm_up should create state files under custom dir"

    def test_startup_works_with_custom_dir(self, tmp_path):
        custom = tmp_path / "startup" / "state"
        ns = NervousSystem(state_dir=custom)
        status = ns.startup()
        assert status["modules_loaded"] > 0

    def test_post_trigger_works_with_custom_dir(self, tmp_path):
        from unittest.mock import MagicMock
        custom = tmp_path / "trigger" / "state"
        ns = NervousSystem(state_dir=custom)

        decision = MagicMock()
        decision.reason = "test_isolation"
        decision.total_pressure = 1.0
        decision.top_drive = None
        result = ns.post_trigger(decision, success=True)
        assert isinstance(result, dict)
