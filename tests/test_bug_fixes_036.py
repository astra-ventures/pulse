"""
Tests for two bugs identified in Trigger #35 code review and fixed in Trigger #36.

Bug 1: daemon.py — feedback file unlinked BEFORE processing.
        If drive.decay() raised, feedback was silently lost.
        Fix: unlink moved to `finally` block (after processing).

Bug 2: germinal_tasks.py — DEFAULT_REFLECTION_TASK returned without calling
        _record_category_used(). Consecutive LLM failures cascaded the same
        "Reflect on current state" task indefinitely.
        Fix: _record_category_used() called before returning fallback.
"""

import json
import time
import tempfile
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# ---------------------------------------------------------------------------
# Bug 1: Feedback file unlink ordering in daemon._process_feedback_file
# ---------------------------------------------------------------------------

class TestFeedbackFileUnlinkOrder:
    """Daemon should unlink feedback file AFTER processing, not before."""

    def _make_daemon(self, state_dir: str):
        """Minimal daemon-like object with just what _process_feedback_file needs."""
        from src.core.daemon import PulseDaemon

        cfg = MagicMock()
        cfg.state.dir = state_dir
        cfg.drives = []
        cfg.sensors = []
        cfg.model.name = "test"
        cfg.model.max_tokens = 100
        cfg.model.temperature = 0.7
        cfg.triggers.min_pressure = 1.0
        cfg.triggers.max_turns_per_hour = 10
        cfg.triggers.conversation_suppress_minutes = 30
        cfg.conversation.suppress_during_conversation = True

        # Build a minimal daemon without starting it
        daemon = object.__new__(PulseDaemon)
        daemon.config = cfg
        daemon._turn_timestamps = []

        # Minimal drives stub
        drives_stub = MagicMock()
        drives_stub.drives = {}
        daemon.drives = drives_stub

        return daemon

    def test_file_deleted_after_successful_processing(self, tmp_path):
        """File must be gone after a clean success path."""
        daemon = self._make_daemon(str(tmp_path))

        feedback = {"drives_addressed": [], "outcome": "success", "summary": "ok"}
        feedback_path = tmp_path / "turn_result.json"
        feedback_path.write_text(json.dumps(feedback))

        daemon._process_feedback_file()

        assert not feedback_path.exists(), "Feedback file should be deleted after success"

    def test_file_deleted_even_when_drive_missing(self, tmp_path):
        """File must be deleted even when a drives_addressed name doesn't exist."""
        daemon = self._make_daemon(str(tmp_path))
        daemon.drives.drives = {}  # empty — drive name will be missing

        feedback = {
            "drives_addressed": ["nonexistent_drive"],
            "outcome": "success",
            "summary": "drive not found",
        }
        feedback_path = tmp_path / "turn_result.json"
        feedback_path.write_text(json.dumps(feedback))

        daemon._process_feedback_file()

        assert not feedback_path.exists(), "File should still be deleted even if drive not found"

    def test_file_deleted_on_cascade_stop(self, tmp_path):
        """cascade_stop outcome must also consume the file."""
        daemon = self._make_daemon(str(tmp_path))

        fake_drive = MagicMock()
        fake_drive.pressure = 2.5
        daemon.drives.drives = {"goals": fake_drive}

        feedback = {"drives_addressed": ["goals"], "outcome": "cascade_stop", "summary": "cascade"}
        feedback_path = tmp_path / "turn_result.json"
        feedback_path.write_text(json.dumps(feedback))

        daemon._process_feedback_file()

        assert not feedback_path.exists()

    def test_file_deleted_on_json_decode_error(self, tmp_path):
        """Corrupt JSON must still consume the file (was already the case, regression guard)."""
        daemon = self._make_daemon(str(tmp_path))

        feedback_path = tmp_path / "turn_result.json"
        feedback_path.write_text("{not valid json")

        daemon._process_feedback_file()

        assert not feedback_path.exists(), "Corrupt feedback file should be deleted, not left behind"

    def test_no_crash_when_file_missing(self, tmp_path):
        """No file → no-op, no exception."""
        daemon = self._make_daemon(str(tmp_path))
        daemon._process_feedback_file()  # should not raise


# ---------------------------------------------------------------------------
# Bug 2: DEFAULT_REFLECTION_TASK cascade in germinal_tasks.generate_tasks
# ---------------------------------------------------------------------------

class TestDefaultReflectionTaskCooldown:
    """generate_tasks() must apply category cooldown even on the fallback path."""

    def test_fallback_on_empty_tasks_records_cooldown(self):
        """When LLM returns no usable tasks, _record_category_used must be called."""
        from src import germinal_tasks
        from src.germinal_tasks import DEFAULT_REFLECTION_TASK

        context = {"goals": [], "recent_generated_titles": []}
        config = {"model": "test-model", "max_tasks": 2}

        call_log = []

        def fake_record(titles):
            call_log.extend(titles)

        async def fake_call_llm(prompt, model_cfg):
            return []  # empty → forces fallback

        def fake_parse(raw, goals, max_t, recent_generated_titles, category_cooldowns):
            return []  # empty → forces fallback

        with (
            patch.object(germinal_tasks, "_record_category_used", side_effect=fake_record),
            patch.object(germinal_tasks, "_call_llm", new=AsyncMock(return_value=[])),
            patch.object(germinal_tasks, "_parse_and_filter", return_value=[]),
            patch.object(germinal_tasks, "_load_category_cooldowns", return_value={}),
            patch.object(germinal_tasks, "_build_prompt", return_value="prompt"),
        ):
            result = asyncio.run(germinal_tasks.generate_tasks(context, config))

        assert result == [DEFAULT_REFLECTION_TASK]
        assert DEFAULT_REFLECTION_TASK["title"] in call_log, (
            "_record_category_used must be called with the fallback task title "
            "to prevent infinite cascade loops"
        )

    def test_fallback_on_llm_exception_records_cooldown(self):
        """When LLM raises, _record_category_used must still be called."""
        from src import germinal_tasks
        from src.germinal_tasks import DEFAULT_REFLECTION_TASK

        context = {"goals": [], "recent_generated_titles": []}
        config = {"model": "test-model", "max_tasks": 2}

        call_log = []

        def fake_record(titles):
            call_log.extend(titles)

        with (
            patch.object(germinal_tasks, "_record_category_used", side_effect=fake_record),
            patch.object(germinal_tasks, "_call_llm", new=AsyncMock(side_effect=RuntimeError("LLM down"))),
            patch.object(germinal_tasks, "_load_category_cooldowns", return_value={}),
            patch.object(germinal_tasks, "_build_prompt", return_value="prompt"),
        ):
            result = asyncio.run(germinal_tasks.generate_tasks(context, config))

        assert result == [DEFAULT_REFLECTION_TASK]
        assert DEFAULT_REFLECTION_TASK["title"] in call_log, (
            "Even on LLM exception, cooldown must be recorded to break cascade loops"
        )

    def test_normal_path_still_records_cooldown(self):
        """Happy path: _record_category_used still called for real tasks."""
        from src import germinal_tasks

        fake_task = {"title": "Build something cool", "priority": "high", "description": "...",
                     "category": "build", "estimated_minutes": 30}

        context = {"goals": [], "recent_generated_titles": []}
        config = {"model": "test-model", "max_tasks": 2}

        call_log = []

        def fake_record(titles):
            call_log.extend(titles)

        with (
            patch.object(germinal_tasks, "_record_category_used", side_effect=fake_record),
            patch.object(germinal_tasks, "_call_llm", new=AsyncMock(return_value=[fake_task])),
            patch.object(germinal_tasks, "_parse_and_filter", return_value=[fake_task]),
            patch.object(germinal_tasks, "_load_category_cooldowns", return_value={}),
            patch.object(germinal_tasks, "_build_prompt", return_value="prompt"),
        ):
            result = asyncio.run(germinal_tasks.generate_tasks(context, config))

        assert result == [fake_task]
        assert "Build something cool" in call_log
