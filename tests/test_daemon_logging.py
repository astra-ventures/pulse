"""Tests for daily notes file locking — Gap #3."""

import fcntl
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pulse.src.core.daily_sync import DailyNoteSync


@pytest.fixture
def daily_sync(tmp_path):
    """DailyNoteSync with isolated temp directory."""
    config = MagicMock()
    config.workspace.root = str(tmp_path)
    config.workspace.daily_notes = "memory/"
    return DailyNoteSync(config)


class TestFlockPresent:
    """Verify that daily note writes use fcntl.flock."""

    def test_log_trigger_uses_flock(self, daily_sync, tmp_path):
        """log_trigger must acquire an exclusive lock."""
        locked = []
        original_flock = fcntl.flock

        def tracking_flock(fd, op):
            if op == fcntl.LOCK_EX:
                locked.append("lock")
            elif op == fcntl.LOCK_UN:
                locked.append("unlock")
            return original_flock(fd, op)

        with patch("pulse.src.core.daily_sync.fcntl") as mock_fcntl:
            mock_fcntl.LOCK_EX = fcntl.LOCK_EX
            mock_fcntl.LOCK_UN = fcntl.LOCK_UN
            mock_fcntl.flock = tracking_flock

            daily_sync.log_trigger(
                turn=1, reason="test", top_drive="goals",
                pressure=5.0, success=True,
            )

        assert "lock" in locked
        assert "unlock" in locked

    def test_log_mutation_uses_flock(self, daily_sync, tmp_path):
        """log_mutation must acquire an exclusive lock."""
        locked = []
        original_flock = fcntl.flock

        def tracking_flock(fd, op):
            if op == fcntl.LOCK_EX:
                locked.append("lock")
            elif op == fcntl.LOCK_UN:
                locked.append("unlock")
            return original_flock(fd, op)

        with patch("pulse.src.core.daily_sync.fcntl") as mock_fcntl:
            mock_fcntl.LOCK_EX = fcntl.LOCK_EX
            mock_fcntl.LOCK_UN = fcntl.LOCK_UN
            mock_fcntl.flock = tracking_flock

            daily_sync.log_mutation({"type": "adjust_weight", "drive": "goals",
                                     "before": 0.5, "after": 0.7})

        assert "lock" in locked
        assert "unlock" in locked


class TestConcurrentWrites:
    """Simulate concurrent writes — verify no data loss."""

    def test_concurrent_trigger_writes(self, daily_sync, tmp_path):
        """Multiple threads writing triggers must not lose entries."""
        n_threads = 10
        n_writes = 5
        errors = []

        def writer(thread_id):
            try:
                for i in range(n_writes):
                    daily_sync.log_trigger(
                        turn=thread_id * 100 + i,
                        reason=f"thread-{thread_id}-write-{i}",
                        top_drive="goals",
                        pressure=2.0,
                        success=True,
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during concurrent writes: {errors}"

        # Verify all entries present
        notes_file = daily_sync._get_file()
        content = notes_file.read_text()
        trigger_lines = [l for l in content.splitlines() if "Trigger #" in l]
        assert len(trigger_lines) == n_threads * n_writes

    def test_no_duplicate_entries(self, daily_sync, tmp_path):
        """Each write must produce exactly one entry, no duplicates."""
        for i in range(20):
            daily_sync.log_trigger(
                turn=i, reason=f"unique-{i}-end", top_drive="curiosity",
                pressure=1.5, success=True,
            )

        notes_file = daily_sync._get_file()
        content = notes_file.read_text()
        trigger_lines = [l for l in content.splitlines() if "Trigger #" in l]
        assert len(trigger_lines) == 20
        for i in range(20):
            marker = f"unique-{i}-end"
            assert content.count(marker) == 1, f"Duplicate entry for {marker}"

    def test_entries_not_truncated(self, daily_sync, tmp_path):
        """Long reason strings must not be truncated or corrupted."""
        long_reason = "A" * 200
        daily_sync.log_trigger(
            turn=1, reason=long_reason, top_drive="goals",
            pressure=3.0, success=True,
        )

        notes_file = daily_sync._get_file()
        content = notes_file.read_text()
        assert long_reason in content
