"""Tests for AURA — Ambient State Broadcast."""

import json
from unittest.mock import patch, MagicMock

import pytest

from pulse.src import aura, thalamus


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    bf = tmp_path / "thalamus.jsonl"
    sf = tmp_path / "aura.json"
    with patch.object(aura, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(aura, "_DEFAULT_STATE_FILE", sf), \
         patch.object(thalamus, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(thalamus, "_DEFAULT_BROADCAST_FILE", bf):
        yield tmp_path


class TestEmit:
    def test_emit_returns_aura(self):
        # Mock the imports inside emit to avoid cross-module dependencies
        with patch("pulse.src.aura.endocrine", create=True) as mock_endo, \
             patch("pulse.src.aura.circadian", create=True) as mock_circ, \
             patch("pulse.src.aura.soma", create=True) as mock_soma, \
             patch("pulse.src.aura.adipose", create=True) as mock_adip:
            # These will fail on import inside emit, which is fine - they're try/excepted
            result = aura.emit()
            assert "mood" in result
            assert "energy" in result
            assert "available" in result
            assert "focus" in result

    def test_emit_broadcasts(self):
        aura.emit()
        entries = thalamus.read_by_source("aura")
        assert any(e["type"] == "ambient" for e in entries)


class TestShouldEmit:
    def test_should_emit_initially(self):
        assert aura.should_emit() is True

    def test_should_not_emit_right_after(self):
        aura.emit()
        assert aura.should_emit() is False


class TestGetAura:
    def test_get_aura(self):
        a = aura.get_aura()
        assert "mood" in a


class TestStatus:
    def test_status(self):
        status = aura.get_status()
        assert "mood" in status
