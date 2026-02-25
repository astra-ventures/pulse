"""Tests for GERMINAL TASKS — Generative Task Synthesis."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch

from pulse.src.germinal_tasks import (
    generate_tasks,
    _build_prompt,
    _parse_and_filter,
    DEFAULT_REFLECTION_TASK,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _base_context():
    return {
        "goals": ["Ship pulse v0.3", "Write documentation"],
        "recent_memory": "Recently worked on evaluator model integration",
        "drives": {"goals": 0.8, "curiosity": 0.5, "growth": 0.3},
        "thalamus_recent": [
            {"source": "limbic", "type": "emotion", "salience": 0.6, "data": {"mood": "focused"}},
        ],
    }


def _base_config(enabled=True):
    return {
        "enabled": enabled,
        "roadmap_files": [],
        "max_tasks": 3,
        "model": {
            "base_url": "http://localhost:11434/v1",
            "api_key": "ollama",
            "model": "llama3.2:3b",
            "max_tokens": 512,
            "temperature": 0.3,
            "timeout_seconds": 10,
        },
    }


def _make_task(title="Test task", requires_external=False, effort="low", drive="goals"):
    return {
        "title": title,
        "description": f"Description for {title}",
        "rationale": f"Rationale for {title}",
        "drive": drive,
        "effort": effort,
        "requires_external": requires_external,
    }


# ─── Tests: generate_tasks ───────────────────────────────────────────────────

class TestGenerateTasks:
    def test_disabled_returns_empty(self):
        result = asyncio.run(generate_tasks(_base_context(), _base_config(enabled=False)))
        assert result == []

    def test_llm_failure_returns_fallback(self):
        """When LLM call fails, should return the default reflection task."""
        config = _base_config()
        config["model"]["base_url"] = "http://127.0.0.1:1"
        config["model"]["timeout_seconds"] = 1

        result = asyncio.run(generate_tasks(_base_context(), config))
        assert len(result) == 1
        assert result[0]["title"] == DEFAULT_REFLECTION_TASK["title"]
        assert result[0]["requires_external"] is False

    def test_successful_generation(self):
        """When LLM returns valid tasks, they should be parsed and returned."""
        tasks = [_make_task("Refactor config module"), _make_task("Write unit tests")]

        async def _run():
            with patch("pulse.src.germinal_tasks._call_llm", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = tasks
                return await generate_tasks(_base_context(), _base_config())

        result = asyncio.run(_run())
        assert len(result) == 2
        assert result[0]["title"] == "Refactor config module"
        assert result[1]["title"] == "Write unit tests"

    def test_filters_external_deps(self):
        """Tasks requiring external dependencies should be filtered out."""
        tasks = [
            _make_task("Internal task", requires_external=False),
            _make_task("External task", requires_external=True),
        ]

        async def _run():
            with patch("pulse.src.germinal_tasks._call_llm", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = tasks
                return await generate_tasks(_base_context(), _base_config())

        result = asyncio.run(_run())
        assert len(result) == 1
        assert result[0]["title"] == "Internal task"

    def test_deduplication_with_goals(self):
        """Tasks that match existing goals should be filtered out."""
        tasks = [
            _make_task("Ship pulse v0.3"),  # matches existing goal
            _make_task("New unique task"),
        ]

        async def _run():
            with patch("pulse.src.germinal_tasks._call_llm", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = tasks
                return await generate_tasks(_base_context(), _base_config())

        result = asyncio.run(_run())
        assert len(result) == 1
        assert result[0]["title"] == "New unique task"

    def test_respects_max_tasks(self):
        """Should not return more than max_tasks."""
        tasks = [_make_task(f"Task {i}") for i in range(5)]
        config = _base_config()
        config["max_tasks"] = 2

        async def _run():
            with patch("pulse.src.germinal_tasks._call_llm", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = tasks
                return await generate_tasks(_base_context(), config)

        result = asyncio.run(_run())
        assert len(result) <= 2

    def test_empty_llm_response_returns_fallback(self):
        """When LLM returns no usable tasks, should return fallback."""
        async def _run():
            with patch("pulse.src.germinal_tasks._call_llm", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = []
                return await generate_tasks(_base_context(), _base_config())

        result = asyncio.run(_run())
        assert len(result) == 1
        assert result[0]["title"] == DEFAULT_REFLECTION_TASK["title"]


# ─── Tests: _build_prompt ────────────────────────────────────────────────────

class TestBuildPrompt:
    def test_includes_goals(self):
        prompt = _build_prompt(_base_context(), _base_config())
        assert "Ship pulse v0.3" in prompt
        assert "Write documentation" in prompt

    def test_includes_drives(self):
        prompt = _build_prompt(_base_context(), _base_config())
        assert "goals" in prompt
        assert "0.80" in prompt

    def test_includes_recent_memory(self):
        prompt = _build_prompt(_base_context(), _base_config())
        assert "evaluator model integration" in prompt

    def test_includes_thalamus(self):
        prompt = _build_prompt(_base_context(), _base_config())
        assert "limbic" in prompt

    def test_handles_empty_context(self):
        empty = {"goals": [], "recent_memory": "", "drives": {}, "thalamus_recent": []}
        prompt = _build_prompt(empty, _base_config())
        assert "no goals currently set" in prompt

    def test_roadmap_files_missing_gracefully(self):
        """Non-existent roadmap files should be silently skipped."""
        config = _base_config()
        config["roadmap_files"] = ["NONEXISTENT_FILE.md"]
        config["workspace_root"] = "/tmp/pulse_test_nonexistent"
        prompt = _build_prompt(_base_context(), config)
        assert "NONEXISTENT_FILE" not in prompt


# ─── Tests: _parse_and_filter ────────────────────────────────────────────────

class TestParseAndFilter:
    def test_filters_external_deps(self):
        tasks = [
            _make_task("Internal", requires_external=False),
            _make_task("External", requires_external=True),
        ]
        result = _parse_and_filter(tasks, [], 3)
        assert len(result) == 1
        assert result[0]["title"] == "Internal"

    def test_deduplicates_against_goals(self):
        tasks = [_make_task("Existing goal"), _make_task("New task")]
        result = _parse_and_filter(tasks, ["Existing goal"], 3)
        assert len(result) == 1
        assert result[0]["title"] == "New task"

    def test_dedup_case_insensitive(self):
        tasks = [_make_task("SHIP PULSE V0.3")]
        result = _parse_and_filter(tasks, ["ship pulse v0.3"], 3)
        assert len(result) == 0

    def test_caps_at_max(self):
        tasks = [_make_task(f"Task {i}") for i in range(10)]
        result = _parse_and_filter(tasks, [], 2)
        assert len(result) == 2

    def test_skips_invalid_tasks(self):
        tasks = [
            {"title": "Missing fields"},  # missing required fields
            _make_task("Valid task"),
            "not a dict",
        ]
        result = _parse_and_filter(tasks, [], 3)
        assert len(result) == 1
        assert result[0]["title"] == "Valid task"

    def test_normalizes_invalid_effort(self):
        task = _make_task("Task", effort="extreme")
        result = _parse_and_filter([task], [], 3)
        assert result[0]["effort"] == "medium"

    def test_output_excludes_requires_external(self):
        """Output tasks should not contain the requires_external field."""
        task = _make_task("Clean task")
        result = _parse_and_filter([task], [], 3)
        assert "requires_external" not in result[0]

    def test_empty_input_returns_empty(self):
        result = _parse_and_filter([], [], 3)
        assert result == []


# ─── Tests: DEFAULT_REFLECTION_TASK ──────────────────────────────────────────

class TestDefaultReflectionTask:
    def test_has_required_fields(self):
        required = {"title", "description", "rationale", "drive", "effort", "requires_external"}
        assert required.issubset(DEFAULT_REFLECTION_TASK.keys())

    def test_not_external(self):
        assert DEFAULT_REFLECTION_TASK["requires_external"] is False

    def test_low_effort(self):
        assert DEFAULT_REFLECTION_TASK["effort"] == "low"
