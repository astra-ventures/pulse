"""Tests for the Broadcast Layer."""

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from pulse.src import thalamus


@pytest.fixture(autouse=True)
def tmp_broadcast(tmp_path):
    """Redirect broadcast to temp dir."""
    bf = tmp_path / "thalamus.jsonl"
    with patch.object(thalamus, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(thalamus, "_DEFAULT_BROADCAST_FILE", bf):
        yield bf


class TestAppend:
    def test_basic_append(self):
        entry = {"source": "test", "type": "state", "salience": 0.5, "data": {"msg": "hello"}}
        result = thalamus.append(entry)
        assert "ts" in result
        assert thalamus.read_recent(1) == [result]

    def test_preserves_existing_ts(self):
        entry = {"ts": 12345, "source": "test", "type": "state", "salience": 0.5, "data": {}}
        result = thalamus.append(entry)
        assert result["ts"] == 12345

    def test_multiple_appends(self):
        for i in range(5):
            thalamus.append({"source": "test", "type": "state", "salience": 0.1, "data": {"i": i}})
        assert len(thalamus.read_recent(10)) == 5


class TestRead:
    def test_read_recent(self):
        for i in range(20):
            thalamus.append({"ts": i, "source": "test", "type": "state", "salience": 0.1, "data": {"i": i}})
        recent = thalamus.read_recent(5)
        assert len(recent) == 5
        assert recent[0]["data"]["i"] == 15

    def test_read_since(self):
        for i in range(10):
            thalamus.append({"ts": i * 1000, "source": "test", "type": "state", "salience": 0.1, "data": {}})
        result = thalamus.read_since(5000)
        assert len(result) == 5

    def test_read_by_source(self):
        thalamus.append({"source": "a", "type": "state", "salience": 0.1, "data": {}})
        thalamus.append({"source": "b", "type": "state", "salience": 0.1, "data": {}})
        thalamus.append({"source": "a", "type": "state", "salience": 0.1, "data": {}})
        assert len(thalamus.read_by_source("a")) == 2
        assert len(thalamus.read_by_source("b")) == 1

    def test_read_by_type(self):
        thalamus.append({"source": "x", "type": "emotion", "salience": 0.5, "data": {}})
        thalamus.append({"source": "x", "type": "silence", "salience": 0.3, "data": {}})
        thalamus.append({"source": "x", "type": "emotion", "salience": 0.7, "data": {}})
        assert len(thalamus.read_by_type("emotion")) == 2

    def test_read_empty(self):
        assert thalamus.read_recent() == []
        assert thalamus.read_since(0) == []


class TestRotation:
    def test_rotation_triggers(self, tmp_broadcast):
        with patch.object(thalamus, "MAX_ENTRIES", 20), \
             patch.object(thalamus, "KEEP_ENTRIES", 10):
            for i in range(25):
                thalamus.append({"ts": i, "source": "test", "type": "state", "salience": 0.1, "data": {"i": i}})
            remaining = thalamus.read_recent(100)
            assert len(remaining) <= 20  # After rotation, kept entries + new ones
            # Archived entries should exist
            archives = list(thalamus._DEFAULT_STATE_DIR.glob("broadcast-archive-*.jsonl"))
            assert len(archives) >= 1


class TestConcurrency:
    def test_concurrent_writes(self):
        results = []

        def writer(n):
            for i in range(10):
                thalamus.append({"source": f"thread-{n}", "type": "state", "salience": 0.1, "data": {"i": i}})
            results.append(n)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        all_entries = thalamus.read_recent(100)
        assert len(all_entries) == 40
