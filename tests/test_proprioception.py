"""Tests for PROPRIOCEPTION — Self-Model / Capability Awareness."""
import json
import pytest
from unittest.mock import MagicMock

from pulse.src import proprioception


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    monkeypatch.setattr(proprioception, "STATE_DIR", tmp_path)
    monkeypatch.setattr(proprioception, "STATE_FILE", tmp_path / "proprioception-state.json")


@pytest.fixture
def mock_thalamus(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(proprioception.thalamus, "append", mock)
    return mock


@pytest.fixture
def configured(mock_thalamus):
    proprioception.update_capabilities(
        model="claude-opus-4-6",
        tools=["read", "write", "exec", "message", "web_search", "browser"],
        context_max=200000,
        context_used=50000,
        skills=["weather", "github"],
        channels=["signal"],
        limitations=["Cannot make phone calls"],
        session_type="main",
    )


# ── can_i checks ────────────────────────────────────────────────────────

def test_can_i_with_available_tool(configured):
    ok, reason = proprioception.can_i("read")
    assert ok is True


def test_can_i_with_action_description(configured):
    ok, reason = proprioception.can_i("send a message")
    assert ok is True
    assert "message" in reason


def test_can_i_unavailable(configured):
    ok, reason = proprioception.can_i("tts")
    assert ok is False


def test_can_i_checks_limitations(configured):
    ok, reason = proprioception.can_i("phone calls")
    assert ok is False
    assert "phone" in reason.lower()


def test_can_i_unknown_action(configured):
    ok, reason = proprioception.can_i("teleport")
    assert ok is False


# ── Limit calculations ─────────────────────────────────────────────────

def test_get_limits(configured):
    limits = proprioception.get_limits()
    assert limits["context_window"] == 200000
    assert limits["context_used"] == 50000
    assert limits["context_remaining"] == 150000
    assert limits["context_percent_used"] == 25.0


# ── Cost estimation ────────────────────────────────────────────────────

def test_estimate_cost_simple():
    cost = proprioception.estimate_cost("say hello")
    assert cost["estimated_tokens"] > 0
    assert cost["complexity"] < 0.5


def test_estimate_cost_complex():
    desc = " ".join(["complex task"] * 50)
    cost = proprioception.estimate_cost(desc)
    assert cost["complexity"] == 1.0
    assert cost["estimated_tokens"] == 5000


# ── would_exceed ────────────────────────────────────────────────────────

def test_would_exceed_false(configured):
    assert proprioception.would_exceed("simple task") is False


def test_would_exceed_true(mock_thalamus):
    proprioception.update_capabilities("test", [], 1000, context_used=999)
    # Even simple tasks estimate 500+ tokens
    assert proprioception.would_exceed("anything at all") is True


# ── Capability update ──────────────────────────────────────────────────

def test_update_capabilities_saves(mock_thalamus):
    proprioception.update_capabilities("opus", ["read"], 100000)
    model = proprioception.get_self_model()
    assert model["model"] == "opus"
    assert "read" in model["tools_available"]


def test_model_switch_broadcasts(mock_thalamus):
    proprioception.update_capabilities("sonnet", ["read"], 100000)
    proprioception.update_capabilities("opus", ["read"], 200000)
    mock_thalamus.assert_called()
    call_data = mock_thalamus.call_args[0][0]
    assert call_data["source"] == "proprioception"
    assert call_data["data"]["event"] == "model_switch"


# ── Identity snapshot ──────────────────────────────────────────────────

def test_identity_snapshot(configured):
    snap = proprioception.get_identity_snapshot()
    assert snap["model"] == "claude-opus-4-6"
    assert snap["session_type"] == "main"
    assert snap["tools_count"] == 6


# ── THALAMUS integration ──────────────────────────────────────────────

def test_thalamus_broadcast_on_model_change(mock_thalamus):
    proprioception.update_capabilities("a", [], 100)
    proprioception.update_capabilities("b", [], 200)
    assert mock_thalamus.called
