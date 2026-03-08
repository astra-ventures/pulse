"""Tests for TaskRouter — model routing based on task content."""

import pytest
from unittest.mock import MagicMock
from src.core.task_router import TaskRouter


def make_config(local="ollama/iris-70b-v3", sonnet="anthropic/claude-sonnet-4-6", opus="anthropic/claude-opus-4-6", enabled=True):
    config = MagicMock()
    config.openclaw.isolated_model = local
    routing = MagicMock()
    routing.enabled = enabled
    routing.sonnet_model = sonnet
    routing.opus_model = opus
    config.openclaw.routing = routing
    return config


@pytest.fixture
def router():
    return TaskRouter(make_config())


# --- Local tier ---

def test_default_routes_local(router):
    result = router.route("SENSE: drives are stable. THINK: all is well. ACT: send feedback.")
    assert result.tier == "local"
    assert "iris-70b-v3" in result.model


def test_heartbeat_routes_local(router):
    result = router.route("heartbeat check — nothing to do")
    assert result.tier == "local"


def test_memory_routes_local(router):
    result = router.route("Update memory with today's learnings and log to daily file")
    assert result.tier == "local"


def test_emotional_routes_local(router):
    result = router.route("Emotional state check — LIMBIC valence +0.8, connection high")
    assert result.tier == "local"


def test_cascade_stop_routes_local(router):
    result = router.route("cascade_stop — drives are low, nothing to do")
    assert result.tier == "local"


def test_journal_routes_local(router):
    result = router.route("Write a new journal entry for iamiris.ai about today")
    assert result.tier == "local"


# --- Sonnet tier ---

def test_implement_routes_sonnet(router):
    result = router.route("implement a new API route for user authentication")
    assert result.tier == "sonnet"
    assert "sonnet" in result.model


def test_typescript_routes_sonnet(router):
    result = router.route("Build a TypeScript component for the dashboard")
    assert result.tier == "sonnet"


def test_debug_routes_sonnet(router):
    result = router.route("debug the payment webhook — it's returning 500")
    assert result.tier == "sonnet"


def test_refactor_routes_sonnet(router):
    result = router.route("refactor the database connection pool for better performance")
    assert result.tier == "sonnet"


def test_file_extension_ts_routes_sonnet(router):
    result = router.route("Update lib/affiliate-links.ts to add new supplement mappings")
    assert result.tier == "sonnet"


def test_file_extension_py_routes_sonnet(router):
    result = router.route("Fix the bug in sdca_bot/valuation.py causing wrong Z-scores")
    assert result.tier == "sonnet"


def test_deploy_routes_sonnet(router):
    result = router.route("deploy the latest Trait DNA build to Vercel")
    assert result.tier == "sonnet"


def test_write_tests_routes_sonnet(router):
    result = router.route("write tests for the new affiliate module")
    assert result.tier == "sonnet"


def test_react_component_routes_sonnet(router):
    result = router.route("build a new react component for the email capture flow")
    assert result.tier == "sonnet"


# --- Opus tier ---

def test_architecture_routes_opus(router):
    result = router.route("design the architecture for the SOMA existence engine")
    assert result.tier == "opus"
    assert "opus" in result.model


def test_system_design_routes_opus(router):
    result = router.route("system design for distributed constellation agent network")
    assert result.tier == "opus"


def test_from_scratch_routes_opus(router):
    result = router.route("build the task router from scratch with full ML classification")
    assert result.tier == "opus"


# --- Local override wins ---

def test_local_override_beats_coding(router):
    """Heartbeat keyword in a message with coding content → still local."""
    result = router.route("heartbeat — also check if lib/pdf-export.ts has issues")
    assert result.tier == "local"


def test_local_override_beats_opus(router):
    """Memory keyword in an architecture message → still local."""
    result = router.route("Update memory with architecture decisions from today")
    assert result.tier == "local"


# --- Routing disabled ---

def test_disabled_always_routes_local():
    router = TaskRouter(make_config(enabled=False))
    result = router.route("implement a full TypeScript refactor of the entire codebase")
    assert result.tier == "local"
    assert result.reason == "routing disabled"


# --- Reason field populated ---

def test_reason_populated_for_sonnet(router):
    result = router.route("implement the stripe checkout flow")
    assert result.reason != ""
    assert "implement" in result.reason


def test_reason_populated_for_local(router):
    result = router.route("reflect on today and update emotional memory")
    assert result.reason != ""
