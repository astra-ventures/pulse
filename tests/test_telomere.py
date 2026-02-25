"""Tests for TELOMERE — Identity Integrity Tracker."""

import json
from unittest.mock import patch

import pytest

from pulse.src import telomere, thalamus


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    bf = tmp_path / "thalamus.jsonl"
    sf = tmp_path / "telomere-state.json"
    snap_dir = tmp_path / "telomere" / "snapshots"
    soul = tmp_path / "SOUL.md"
    soul.write_text("# I am Iris\nThis is my soul.")
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "2026-01-01.md").write_text("test")
    (memory_dir / "2026-01-02.md").write_text("test")
    with patch.object(telomere, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(telomere, "_DEFAULT_STATE_FILE", sf), \
         patch.object(telomere, "_DEFAULT_SNAPSHOT_DIR", snap_dir), \
         patch.object(telomere, "SOUL_PATH", soul), \
         patch.object(telomere, "MEMORY_DIR", memory_dir), \
         patch.object(thalamus, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(thalamus, "_DEFAULT_BROADCAST_FILE", bf):
        yield tmp_path


class TestStartSession:
    def test_increments_count(self):
        telomere.start_session()
        telomere.start_session()
        status = telomere.get_status()
        assert status["session_count"] == 2


class TestCheckIdentity:
    def test_basic_check(self):
        result = telomere.check_identity()
        assert "drift_score" in result
        assert "memory_completeness" in result
        assert result["soul_hash"] != ""

    def test_no_drift_without_snapshots(self):
        result = telomere.check_identity()
        assert result["drift_score"] == 0.0

    def test_drift_detected_with_changed_snapshots(self, tmp_path):
        # Take snapshot with current hash
        telomere.take_snapshot()
        # Change soul
        (tmp_path / "SOUL.md").write_text("# I am someone else entirely")
        result = telomere.check_identity()
        assert result["drift_score"] > 0

    def test_high_drift_triggers_alert(self, tmp_path):
        # Add snapshots with different hashes
        state = telomere._load_state()
        state["snapshots"] = [{"hash": "different", "ts": 0, "month": "2025-01"} for _ in range(5)]
        telomere._save_state(state)
        result = telomere.check_identity()
        assert result["drift_score"] > 0
        entries = thalamus.read_by_source("telomere")
        assert any(e["type"] == "identity_drift_alert" for e in entries)


class TestSnapshot:
    def test_take_snapshot(self):
        snap = telomere.take_snapshot()
        assert "hash" in snap
        assert "month" in snap
        status = telomere.get_status()
        assert status["snapshots_count"] == 1


class TestMemoryCompleteness:
    def test_completeness_calculated(self):
        result = telomere.check_identity()
        assert result["memory_completeness"] > 0
