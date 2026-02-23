"""Tests for Pulse v0.3.0 Plugin Architecture."""

import sys
import time
import textwrap
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest

from pulse.src.plugin_registry import (
    PulsePlugin,
    PluginRegistry,
    discover_plugins,
    load_plugin_file,
    _find_plugin_classes,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

class EchoPlugin(PulsePlugin):
    name = "ECHO"
    version = "1.0.0"
    description = "Test plugin that echoes sense data."

    def sense(self) -> dict:
        return {"curiosity": 0.5}

    def get_state(self) -> dict:
        return {"active": True}

    def act(self, directive: str) -> bool:
        return directive == "echo"


class NoisyPlugin(PulsePlugin):
    name = "NOISY"

    def sense(self) -> dict:
        raise RuntimeError("sense failed")

    def get_state(self) -> dict:
        raise RuntimeError("get_state failed")

    def act(self, directive: str) -> bool:
        raise RuntimeError("act failed")


@pytest.fixture
def reg():
    """Fresh registry for each test."""
    r = PluginRegistry()
    yield r
    r.clear()


# ── PulsePlugin base class ────────────────────────────────────────────────────

class TestPulsePlugin:

    def test_defaults_return_empty(self):
        p = PulsePlugin()
        assert p.sense() == {}
        assert p.get_state() == {}
        assert p.act("anything") is False

    def test_on_load_and_unload_no_error(self):
        p = PulsePlugin()
        p.on_load()   # should not raise
        p.on_unload() # should not raise

    def test_enabled_by_default(self):
        p = PulsePlugin()
        assert p.enabled is True

    def test_disabled_after_max_errors(self):
        p = PulsePlugin()
        p._max_errors = 2
        p.record_error(RuntimeError("e1"))
        assert p.enabled is True
        p.record_error(RuntimeError("e2"))
        assert p.enabled is False

    def test_reset_errors_re_enables(self):
        p = PulsePlugin()
        p._max_errors = 1
        p.record_error(RuntimeError("e"))
        assert p.enabled is False
        p.reset_errors()
        assert p.enabled is True

    def test_health_dict_structure(self):
        p = EchoPlugin()
        h = p.health()
        assert h["name"] == "ECHO"
        assert h["version"] == "1.0.0"
        assert h["enabled"] is True
        assert h["error_count"] == 0

    def test_repr_includes_name_and_status(self):
        p = EchoPlugin()
        r = repr(p)
        assert "ECHO" in r
        assert "enabled" in r


# ── PluginRegistry ─────────────────────────────────────────────────────────

class TestPluginRegistry:

    def test_register_returns_true_for_new_plugin(self, reg):
        assert reg.register(EchoPlugin()) is True

    def test_register_returns_false_for_duplicate(self, reg):
        reg.register(EchoPlugin())
        assert reg.register(EchoPlugin()) is False

    def test_register_raises_for_non_plugin(self, reg):
        with pytest.raises(TypeError):
            reg.register("not a plugin")

    def test_count_reflects_registered_plugins(self, reg):
        assert reg.count == 0
        reg.register(EchoPlugin())
        assert reg.count == 1

    def test_unregister_removes_plugin(self, reg):
        reg.register(EchoPlugin())
        assert reg.unregister("ECHO") is True
        assert reg.count == 0

    def test_unregister_returns_false_if_not_registered(self, reg):
        assert reg.unregister("MISSING") is False

    def test_contains_check(self, reg):
        reg.register(EchoPlugin())
        assert "ECHO" in reg
        assert "OTHER" not in reg

    def test_clear_removes_all(self, reg):
        reg.register(EchoPlugin())
        reg.clear()
        assert reg.count == 0


# ── sense_all ─────────────────────────────────────────────────────────────────

class TestSenseAll:

    def test_merges_drive_contributions(self, reg):
        class DoublePlugin(PulsePlugin):
            name = "DOUBLE"
            def sense(self): return {"goals": 0.3, "system": 0.2}

        reg.register(EchoPlugin())   # curiosity: 0.5
        reg.register(DoublePlugin()) # goals: 0.3, system: 0.2
        result = reg.sense_all()
        assert result["curiosity"] == pytest.approx(0.5)
        assert result["goals"] == pytest.approx(0.3)

    def test_noisy_plugin_caught_and_disabled(self, reg):
        noisy = NoisyPlugin()
        noisy._max_errors = 1
        reg.register(noisy)
        result = reg.sense_all()  # should not raise
        assert result == {}

    def test_disabled_plugin_skipped(self, reg):
        p = EchoPlugin()
        p._enabled = False
        reg.register(p)
        assert reg.sense_all() == {}

    def test_empty_registry_returns_empty(self, reg):
        assert reg.sense_all() == {}


# ── get_all_states ────────────────────────────────────────────────────────────

class TestGetAllStates:

    def test_returns_state_per_plugin(self, reg):
        reg.register(EchoPlugin())
        states = reg.get_all_states()
        assert "ECHO" in states
        assert states["ECHO"]["active"] is True

    def test_noisy_get_state_recorded_as_error(self, reg):
        noisy = NoisyPlugin()
        reg.register(noisy)
        states = reg.get_all_states()
        # Should contain error key, not raise
        assert "NOISY" in states
        assert "error" in states["NOISY"]


# ── act_all ───────────────────────────────────────────────────────────────────

class TestActAll:

    def test_handled_directive_returns_plugin_name(self, reg):
        reg.register(EchoPlugin())
        handled = reg.act_all("echo")
        assert "ECHO" in handled

    def test_unhandled_directive_returns_empty(self, reg):
        reg.register(EchoPlugin())
        assert reg.act_all("unrecognized_directive") == []

    def test_noisy_act_caught(self, reg):
        reg.register(NoisyPlugin())
        result = reg.act_all("test")  # should not raise
        assert result == []


# ── discover_plugins ──────────────────────────────────────────────────────────

class TestDiscoverPlugins:

    def _write_plugin(self, plugin_dir: Path, name: str, class_name: str, sense_val: float = 0.1):
        code = textwrap.dedent(f"""
            from pulse.src.plugin_registry import PulsePlugin

            class {class_name}(PulsePlugin):
                name = '{name}'
                version = '0.1.0'
                def sense(self):
                    return {{'curiosity': {sense_val}}}
        """)
        plugin_dir.mkdir(parents=True, exist_ok=True)
        fpath = plugin_dir / f"pulse_plugin_{name.lower()}.py"
        fpath.write_text(code)
        return fpath

    def test_discovers_plugin_from_file(self, tmp_path):
        reg = PluginRegistry()
        self._write_plugin(tmp_path, "TEST1", "Test1Plugin")
        n, errors = discover_plugins(plugin_dir=tmp_path, registry=reg)
        assert n == 1
        assert "TEST1" in reg
        # Cleanup sys.modules
        sys.modules.pop("pulse_plugin_test1", None)

    def test_no_plugins_in_empty_dir(self, tmp_path):
        reg = PluginRegistry()
        n, errors = discover_plugins(plugin_dir=tmp_path, registry=reg)
        assert n == 0

    def test_missing_dir_returns_zero(self, tmp_path):
        reg = PluginRegistry()
        n, errors = discover_plugins(plugin_dir=tmp_path / "missing", registry=reg)
        assert n == 0

    def test_invalid_file_reported_in_errors(self, tmp_path):
        bad = tmp_path / "pulse_plugin_bad.py"
        bad.write_text("this is not valid python !!!")
        reg = PluginRegistry()
        n, errors = discover_plugins(plugin_dir=tmp_path, registry=reg)
        assert n == 0
        assert len(errors) > 0

    def test_duplicate_not_re_registered(self, tmp_path):
        reg = PluginRegistry()
        self._write_plugin(tmp_path, "DUP1", "Dup1Plugin")
        discover_plugins(plugin_dir=tmp_path, registry=reg)
        n2, _ = discover_plugins(plugin_dir=tmp_path, registry=reg)
        assert n2 == 0  # already registered
        sys.modules.pop("pulse_plugin_dup1", None)
