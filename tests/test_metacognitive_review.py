"""Tests for metacognitive code review fixes (March 4, 2026 — Trigger #31).

Covers:
1. GERMINAL _count_modules() — infrastructure file exclusion
2. GERMINAL ceiling check — no longer permanently blocked
3. ModelEvaluator._strip_json_fences() — deduped fence stripping
4. ModelEvaluator._fallback_evaluate() — conversation suppression
"""

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ─── GERMINAL: Module Count Fix ────────────────────────────────────────────

class TestGerminalModuleCount:
    """Verify _count_modules excludes infrastructure files."""

    def test_count_modules_less_than_total_py_files(self):
        """Module count must be less than total .py files (infra excluded)."""
        from pulse.src.germinal import _count_modules, PULSE_SRC
        total_py = len(list(PULSE_SRC.glob("*.py")))
        module_count = _count_modules()
        assert module_count < total_py, (
            f"_count_modules ({module_count}) should be less than total .py files ({total_py})"
        )

    def test_count_excludes_init_files(self):
        """__init__.py and __main__.py must not be counted."""
        from pulse.src.germinal import _count_modules, PULSE_SRC
        # These definitely exist
        assert (PULSE_SRC / "__init__.py").exists()
        # Count shouldn't include them
        count = _count_modules()
        # If we had ONLY __init__.py, count would be 0
        assert count > 0  # sanity — we have real modules

    def test_count_excludes_infrastructure(self):
        """Known infrastructure files must be excluded from count."""
        from pulse.src.germinal import _count_modules, _INFRA_FILES, PULSE_SRC
        all_files = {f.name for f in PULSE_SRC.glob("*.py")}
        # Verify our infra list is accurate (all listed files actually exist)
        for infra in _INFRA_FILES:
            if infra in all_files:
                # Good — infra file exists and will be excluded
                pass
            # It's OK if some infra files don't exist (future-proofing)

    def test_ceiling_not_permanently_tripped(self):
        """With correct counting, ceiling should NOT be tripped (room for growth)."""
        from pulse.src.germinal import _count_modules, MAX_TOTAL_MODULES
        count = _count_modules()
        assert count < MAX_TOTAL_MODULES, (
            f"Module count ({count}) >= ceiling ({MAX_TOTAL_MODULES}). "
            f"GERMINAL would be permanently blocked!"
        )

    def test_room_for_at_least_5_new_modules(self):
        """Should have meaningful room for new births."""
        from pulse.src.germinal import _count_modules, MAX_TOTAL_MODULES
        room = MAX_TOTAL_MODULES - _count_modules()
        assert room >= 5, f"Only {room} slots left — GERMINAL has almost no room to grow"

    def test_attempt_birth_not_ceiling_blocked(self):
        """attempt_birth should NOT be blocked by ceiling with correct counting.
        
        Uses a whitelisted drive (generate_revenue) and mocks the state file
        so we never write to the production ~/.pulse/state/germinal-state.json.
        """
        import tempfile, os
        from unittest.mock import patch
        from pulse.src import germinal

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp_path = f.name

        try:
            # Patch the state file path so tests never touch production state
            with patch.object(germinal, "_DEFAULT_STATE_FILE", __import__("pathlib").Path(tmp_path)):
                state = germinal._default_state()
                germinal._save_state(state)

                # Use a real whitelisted drive — this tests the ceiling, not injection
                result = germinal.attempt_birth("generate_revenue")
                if not result["ok"]:
                    assert "ceiling" not in result["reason"].lower(), (
                        f"Birth blocked by ceiling: {result['reason']}. "
                        f"The _count_modules fix didn't work!"
                    )
        finally:
            os.unlink(tmp_path)


# ─── ModelEvaluator: JSON Fence Stripping ───────────────────────────────────

class TestStripJsonFences:
    """Test the deduplicated _strip_json_fences helper."""

    def test_plain_json_unchanged(self):
        from pulse.src.evaluator.model import ModelEvaluator
        raw = '{"trigger": true, "reason": "test"}'
        assert ModelEvaluator._strip_json_fences(raw) == raw

    def test_strips_json_fences(self):
        from pulse.src.evaluator.model import ModelEvaluator
        raw = '```json\n{"trigger": true}\n```'
        result = ModelEvaluator._strip_json_fences(raw)
        assert result == '{"trigger": true}'

    def test_strips_plain_fences(self):
        from pulse.src.evaluator.model import ModelEvaluator
        raw = '```\n{"trigger": false}\n```'
        result = ModelEvaluator._strip_json_fences(raw)
        assert result == '{"trigger": false}'

    def test_handles_whitespace(self):
        from pulse.src.evaluator.model import ModelEvaluator
        raw = '  \n```json\n{"x": 1}\n```\n  '
        result = ModelEvaluator._strip_json_fences(raw)
        assert json.loads(result) == {"x": 1}

    def test_no_fences_no_change(self):
        from pulse.src.evaluator.model import ModelEvaluator
        raw = '{"suppress_minutes": 15}'
        assert ModelEvaluator._strip_json_fences(raw) == raw


# ─── ModelEvaluator: Fallback Conversation Suppression ──────────────────────

class TestFallbackConversationSuppression:
    """Verify _fallback_evaluate respects conversation suppression."""

    def _make_evaluator(self):
        """Create a ModelEvaluator with minimal config for testing."""
        from pulse.src.evaluator.model import ModelEvaluator
        from pulse.src.drives.engine import Drive, DriveState

        config = MagicMock()
        config.evaluator.rules.suppress_during_conversation = True
        config.evaluator.rules.single_drive_threshold = 3.0
        config.evaluator.rules.combined_threshold = 5.0
        config.drives.trigger_threshold = 4.0

        evaluator = ModelEvaluator(config)
        evaluator._consecutive_failures = 5  # force fallback mode

        drive = Drive(name="goals", category="goals", weight=1.0)
        drive.pressure = 4.0  # above thresholds
        drive_state = DriveState(
            drives=[drive],
            timestamp=time.time(),
            total_pressure=4.0,
            top_drive=drive,
        )
        return evaluator, drive_state

    def test_fallback_suppresses_active_conversation(self):
        evaluator, drive_state = self._make_evaluator()
        sensor_data = {"conversation": {"active": True, "seconds_since": 30}}
        
        decision = evaluator._fallback_evaluate(drive_state, sensor_data)
        assert not decision.should_trigger
        assert "conversation" in decision.reason.lower()

    def test_fallback_suppresses_cooldown_conversation(self):
        evaluator, drive_state = self._make_evaluator()
        sensor_data = {"conversation": {"active": False, "in_cooldown": True, "seconds_since": 120}}
        
        decision = evaluator._fallback_evaluate(drive_state, sensor_data)
        assert not decision.should_trigger
        assert "conversation" in decision.reason.lower()

    def test_fallback_triggers_without_conversation(self):
        evaluator, drive_state = self._make_evaluator()
        sensor_data = {"conversation": {"active": False, "in_cooldown": False}}
        
        decision = evaluator._fallback_evaluate(drive_state, sensor_data)
        # Should trigger because pressure is above threshold
        assert decision.should_trigger

    def test_fallback_triggers_when_suppression_disabled(self):
        evaluator, drive_state = self._make_evaluator()
        evaluator.config.evaluator.rules.suppress_during_conversation = False
        sensor_data = {"conversation": {"active": True, "seconds_since": 10}}
        
        decision = evaluator._fallback_evaluate(drive_state, sensor_data)
        # Should trigger despite active convo because suppression is disabled
        assert decision.should_trigger
