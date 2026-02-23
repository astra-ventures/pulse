"""Tests for evaluator model — EXCEPTION rule guards."""

import pytest

from pulse.src.evaluator.model import EVALUATOR_SYSTEM_PROMPT


class TestExceptionRulePrompt:
    """Verify the EXCEPTION rule requires individual drive > 1.5."""

    def test_exception_requires_individual_drive_threshold(self):
        """EXCEPTION line must require highest individual drive exceeds 1.5."""
        assert "the highest individual drive exceeds 1.5" in EVALUATOR_SYSTEM_PROMPT

    def test_exception_not_just_total_pressure(self):
        """EXCEPTION must NOT fire on total pressure alone."""
        # Find the EXCEPTION line
        for line in EVALUATOR_SYSTEM_PROMPT.splitlines():
            if line.strip().startswith("- EXCEPTION:"):
                # Must contain the individual-drive guard
                assert "highest individual drive exceeds 1.5" in line
                # Must mention ambient floor accumulation caveat
                assert "ambient floor" in line.lower() or "not just ambient" in line.lower()
                break
        else:
            pytest.fail("EXCEPTION rule not found in EVALUATOR_SYSTEM_PROMPT")

    def test_exception_still_requires_total_above_10(self):
        """EXCEPTION must still require total pressure > 10.0."""
        for line in EVALUATOR_SYSTEM_PROMPT.splitlines():
            if "EXCEPTION" in line:
                assert "10.0" in line
                break

    def test_exception_still_requires_30_minutes(self):
        """EXCEPTION must still require 30+ minutes since last trigger."""
        for line in EVALUATOR_SYSTEM_PROMPT.splitlines():
            if "EXCEPTION" in line:
                assert "30 minutes" in line
                break


class TestExceptionSemantics:
    """Test that the prompt semantics prevent floor-only triggers."""

    def test_floor_drives_described_as_insufficient(self):
        """Nine drives at floor (~1.24 each) = ~11.2 total.
        The rule must NOT fire because no individual drive exceeds 1.5."""
        # The prompt text explicitly says "not just ambient floor accumulation"
        assert "not just ambient floor accumulation" in EVALUATOR_SYSTEM_PROMPT

    def test_genuine_idle_scenario_described(self):
        """The prompt must describe the exception as 'genuinely idle'."""
        assert "genuinely idle" in EVALUATOR_SYSTEM_PROMPT
