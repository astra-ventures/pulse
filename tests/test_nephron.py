"""Tests for NEPHRON — Excretory System / Memory Pruning."""

import json
import time
import pytest
from pathlib import Path
from unittest.mock import patch

from pulse.src import nephron


class TestNephronBasics:
    def test_default_state(self):
        state = nephron._default_state()
        assert state["total_cycles"] == 0
        assert state["total_pruned"] == 0
        assert state["last_run"] == 0
        assert state["history"] == []

    def test_should_run(self):
        assert not nephron.should_run(0)
        assert not nephron.should_run(1)
        assert not nephron.should_run(50)
        assert not nephron.should_run(99)
        assert nephron.should_run(100)
        assert nephron.should_run(200)
        assert nephron.should_run(300)

    def test_get_status(self):
        status = nephron.get_status()
        assert "total_cycles" in status
        assert "total_pruned" in status
        assert "last_run" in status

    def test_filter_all_runs(self):
        results = nephron.filter_all()
        assert "pruned" in results
        assert "errors" in results
        assert "timestamp" in results

    def test_state_persists_after_filter(self):
        nephron.filter_all()
        status = nephron.get_status()
        assert status["total_cycles"] >= 1

    def test_thalamus_pruning(self):
        """Test that THALAMUS bus gets trimmed when too large."""
        thalamus_file = nephron._DEFAULT_STATE_DIR / "thalamus.jsonl"
        
        # Create oversized file
        original = thalamus_file.read_text() if thalamus_file.exists() else ""
        try:
            lines = [json.dumps({"ts": i, "source": "test", "type": "test"}) for i in range(600)]
            thalamus_file.write_text("\n".join(lines) + "\n")
            
            pruned = nephron._prune_thalamus()
            assert pruned == 100  # 600 - 500
            
            remaining = thalamus_file.read_text().strip().split("\n")
            assert len(remaining) == 500
        finally:
            # Restore original
            thalamus_file.write_text(original)

    def test_thalamus_no_pruning_needed(self):
        """No pruning when under threshold."""
        thalamus_file = nephron._DEFAULT_STATE_DIR / "thalamus.jsonl"
        original = thalamus_file.read_text() if thalamus_file.exists() else ""
        try:
            lines = [json.dumps({"ts": i}) for i in range(100)]
            thalamus_file.write_text("\n".join(lines) + "\n")
            assert nephron._prune_thalamus() == 0
        finally:
            thalamus_file.write_text(original)

    def test_endocrine_history_pruning(self):
        """Trim mood_history when over 48."""
        endo_file = nephron._DEFAULT_STATE_DIR / "endocrine-state.json"
        if not endo_file.exists():
            return
        
        original = endo_file.read_text()
        try:
            data = json.loads(original)
            # Temporarily inflate
            data["mood_history"] = [{"ts": i, "label": "test"} for i in range(60)]
            endo_file.write_text(json.dumps(data))
            
            pruned = nephron._prune_endocrine_history()
            assert pruned == 12  # 60 - 48
            
            after = json.loads(endo_file.read_text())
            assert len(after["mood_history"]) == 48
        finally:
            endo_file.write_text(original)

    def test_chronicle_no_recent_pruning(self):
        """Recent chronicle entries should not be pruned."""
        chronicle_file = nephron._DEFAULT_STATE_DIR / "chronicle.jsonl"
        if not chronicle_file.exists():
            return
        
        original = chronicle_file.read_text()
        try:
            lines = [json.dumps({"ts": time.time() - 100, "event": "test"}) for _ in range(5)]
            chronicle_file.write_text("\n".join(lines) + "\n")
            assert nephron._prune_chronicle() == 0
        finally:
            chronicle_file.write_text(original)
