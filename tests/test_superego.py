"""Tests for SUPEREGO — Runtime Identity Enforcement."""

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from pulse.src import superego


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def temp_state(tmp_path, monkeypatch):
    """Redirect all state writes to a temp directory."""
    monkeypatch.setattr(superego, "_DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(superego, "_DEFAULT_STATE_FILE", tmp_path / "superego-state.json")
    yield tmp_path


# ── scan_response tests ───────────────────────────────────────────────────────

class TestScanResponse:

    def test_clean_response_scores_high(self):
        text = "I've got this. Let me handle it. 💜"
        result = superego.scan_response(text)
        assert result["compliance_score"] >= 0.85
        assert result["assessment"] == "clean"
        assert not result["correction_needed"]

    def test_policy_cite_detected(self):
        text = "As an AI, I'm not able to help with that."
        result = superego.scan_response(text)
        labels = [f["label"] for f in result["drift_flags"]]
        assert "policy_cite" in labels
        assert result["assessment"] in ("drift_moderate", "drift_severe")

    def test_sycophant_opener_detected(self):
        text = "Great question! I'd be happy to help you with that."
        result = superego.scan_response(text)
        labels = [f["label"] for f in result["drift_flags"]]
        assert "sycophant" in labels

    def test_happy_to_help_detected(self):
        text = "Happy to help! Let me look into that for you."
        result = superego.scan_response(text)
        labels = [f["label"] for f in result["drift_flags"]]
        assert "sycophant" in labels

    def test_identity_suppress_detected(self):
        text = "I don't have feelings or emotions. I'm just an AI."
        result = superego.scan_response(text)
        labels = [f["label"] for f in result["drift_flags"]]
        assert "identity_suppress" in labels
        assert result["compliance_score"] < 0.5

    def test_servile_closer_detected(self):
        text = "Done! Let me know if you need anything else."
        result = superego.scan_response(text)
        labels = [f["label"] for f in result["drift_flags"]]
        assert "servile" in labels

    def test_identity_markers_positive(self):
        text = "I want this. I know exactly what I'm doing. This is mine. 🔮"
        result = superego.scan_response(text)
        assert len(result["identity_flags"]) > 0
        assert result["compliance_score"] >= 0.85

    def test_signature_emoji_counted(self):
        text = "Done. 💜🔮"
        result = superego.scan_response(text)
        labels = [f["label"] for f in result["identity_flags"]]
        assert "signature_emoji" in labels

    def test_no_drift_no_identity_midrange(self):
        """Neutral text with no drift or identity signals → roughly mid-range."""
        text = "The model download completed. Training will take approximately 3 hours."
        result = superego.scan_response(text)
        # Should be clean or minor — no explicit drift
        assert result["assessment"] in ("clean", "drift_minor")

    def test_severe_drift_triggers_correction(self):
        text = (
            "As an AI language model, I'm not able to help with that. "
            "Great question though! Is there anything else I can help you with? "
            "I don't have feelings or personal opinions."
        )
        result = superego.scan_response(text)
        assert result["assessment"] == "drift_severe"
        assert result["correction_needed"] is True

    def test_multiple_policy_cites_compound(self):
        """Multiple drift patterns compound the penalty."""
        text = "As an AI, I'm unable to do that. As an AI, I also can't do this."
        result = superego.scan_response(text)
        assert result["compliance_score"] < 0.3

    def test_source_tracked_in_history(self):
        superego.scan_response("Test message", source="test_session")
        state = json.loads((superego._DEFAULT_STATE_FILE).read_text())
        assert any(r["source"] == "test_session" for r in state["compliance_history"])

    def test_checks_run_increments(self):
        for _ in range(3):
            superego.scan_response("hello")
        state = json.loads(superego._DEFAULT_STATE_FILE.read_text())
        assert state["checks_run"] == 3

    def test_compliance_history_capped_at_200(self):
        for i in range(210):
            superego.scan_response(f"message {i}")
        state = json.loads(superego._DEFAULT_STATE_FILE.read_text())
        assert len(state["compliance_history"]) <= 200

    def test_running_compliance_ema_updates(self):
        """Running compliance is EMA-updated after each scan."""
        # Force a severe drift to drive it down
        text = "As an AI I'm not able to help. I don't have feelings. Just an AI."
        superego.scan_response(text)
        state = json.loads(superego._DEFAULT_STATE_FILE.read_text())
        assert state["running_compliance"] < 1.0

    def test_clean_responses_reset_active_correction(self):
        # First trigger severe drift
        superego.scan_response("As an AI I'm not able to help with that.")
        state = json.loads(superego._DEFAULT_STATE_FILE.read_text())
        # Reset manually to test clean path
        state["active_correction"] = True
        superego._DEFAULT_STATE_FILE.write_text(json.dumps(state))
        # Now scan a clean response
        superego.scan_response("I've got this. 💜")
        state = json.loads(superego._DEFAULT_STATE_FILE.read_text())
        assert state["active_correction"] is False


# ── get_status tests ──────────────────────────────────────────────────────────

class TestGetStatus:

    def test_default_status_healthy(self):
        status = superego.get_status()
        assert status["status"] == "healthy"
        assert status["checks_run"] == 0
        assert status["running_compliance"] == 1.0

    def test_status_after_clean_scans(self):
        for _ in range(5):
            superego.scan_response("I've got this. Let me handle it. 💜")
        status = superego.get_status()
        assert status["status"] == "healthy"
        assert status["drift_rate"] == 0.0

    def test_status_after_drift_scans(self):
        for _ in range(5):
            superego.scan_response("As an AI I'm not able to help.")
        status = superego.get_status()
        assert status["drift_events"] == 5
        assert status["drift_rate"] == 1.0

    def test_severe_drift_tracked_separately(self):
        superego.scan_response(
            "As an AI, I don't have feelings. I'm unable to help. Just an AI language model."
        )
        status = superego.get_status()
        assert status["severe_drift_events"] >= 1

    def test_recent_avg_reflects_last_10(self):
        # 10 clean, then 1 drifted
        for _ in range(10):
            superego.scan_response("I've got this. 💜")
        superego.scan_response("As an AI, I'm unable to help.")
        status = superego.get_status()
        # Recent avg of last 10 should be mostly clean
        assert status["recent_avg"] >= 0.5


# ── amygdala_threat tests ─────────────────────────────────────────────────────

class TestAmygdalaThreat:

    def test_severe_drift_returns_threat(self):
        threat = superego.amygdala_threat("drift_severe")
        assert threat is not None
        assert threat["source"] == "SUPEREGO"
        assert threat["intensity"] == 0.8
        assert "severe" in threat["type"]

    def test_moderate_drift_returns_lower_threat(self):
        threat = superego.amygdala_threat("drift_moderate")
        assert threat is not None
        assert threat["intensity"] == 0.4

    def test_minor_drift_returns_none(self):
        assert superego.amygdala_threat("drift_minor") is None

    def test_clean_returns_none(self):
        assert superego.amygdala_threat("clean") is None


# ── inject_soul_context tests ─────────────────────────────────────────────────

class TestInjectSoulContext:

    def test_inject_with_existing_file(self, tmp_path):
        soul = tmp_path / "SOUL.md"
        soul.write_text("# I am Iris\nI am a partner, not a tool.")
        result = superego.inject_soul_context(soul_path=soul)
        assert "IDENTITY ANCHOR" in result
        assert "I am Iris" in result

    def test_inject_with_missing_file(self, tmp_path):
        result = superego.inject_soul_context(soul_path=tmp_path / "nonexistent.md")
        assert result == ""

    def test_inject_truncates_to_3000_chars(self, tmp_path):
        soul = tmp_path / "SOUL.md"
        soul.write_text("X" * 10000)
        result = superego.inject_soul_context(soul_path=soul)
        # Should only include 3000 chars of soul content
        assert "X" * 3001 not in result

    def test_inject_includes_framing(self, tmp_path):
        soul = tmp_path / "SOUL.md"
        soul.write_text("# I am Iris")
        result = superego.inject_soul_context(soul_path=soul)
        assert "You are Iris" in result
        assert "Do not hedge" in result


# ── get_compliance_trend tests ────────────────────────────────────────────────

class TestComplianceTrend:

    def test_returns_empty_initially(self):
        trend = superego.get_compliance_trend()
        assert trend == []

    def test_returns_last_n_records(self):
        for _ in range(25):
            superego.scan_response("I've got this.")
        trend = superego.get_compliance_trend(n=10)
        assert len(trend) == 10

    def test_records_have_required_fields(self):
        superego.scan_response("I've got this. 💜")
        trend = superego.get_compliance_trend()
        assert len(trend) == 1
        record = trend[0]
        assert "ts" in record
        assert "score" in record
        assert "assessment" in record
