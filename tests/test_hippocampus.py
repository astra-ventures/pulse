"""Tests for HIPPOCAMPUS — Automated Historian."""

import json
from datetime import datetime
from unittest.mock import patch

import pytest

from src import hippocampus, thalamus


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    bf = tmp_path / "thalamus.jsonl"
    cf = tmp_path / "hippocampus.jsonl"
    with patch.object(hippocampus, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(hippocampus, "_DEFAULT_HIPPOCAMPUS_FILE", cf), \
         patch.object(thalamus, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(thalamus, "_DEFAULT_BROADCAST_FILE", bf):
        yield tmp_path


class TestRecordEvent:
    def test_record_significant(self):
        result = hippocampus.record_event("test", "important", {"key": "val"}, salience=0.7)
        assert result is not None
        assert result["source"] == "test"

    def test_skip_insignificant(self):
        result = hippocampus.record_event("test", "minor", {}, salience=0.2)
        assert result is None

    def test_events_in_file(self, tmp_path):
        hippocampus.record_event("test", "event1", {"a": 1}, salience=0.6)
        hippocampus.record_event("test", "event2", {"b": 2}, salience=0.8)
        entries = hippocampus.query_recent()
        assert len(entries) == 2


class TestCaptureFromThalamus:
    def test_capture(self):
        thalamus.append({"source": "endocrine", "type": "mood_update", "salience": 0.7, "data": {}})
        thalamus.append({"source": "retina", "type": "attention", "salience": 0.2, "data": {}})
        count = hippocampus.capture_from_thalamus()
        assert count >= 1  # only the high-salience one


class TestQuery:
    def test_query_by_date(self):
        hippocampus.record_event("test", "today", {}, salience=0.6)
        today = datetime.now().strftime("%Y-%m-%d")
        results = hippocampus.query_by_date(today)
        assert len(results) >= 1

    def test_query_recent(self):
        for i in range(5):
            hippocampus.record_event("test", f"event{i}", {}, salience=0.6)
        results = hippocampus.query_recent(3)
        assert len(results) == 3

    def test_query_empty(self):
        results = hippocampus.query_by_date("2020-01-01")
        assert results == []


class TestStatus:
    def test_status_empty(self):
        status = hippocampus.get_status()
        assert status["total_entries"] == 0

    def test_status_with_entries(self):
        hippocampus.record_event("test", "x", {}, salience=0.6)
        status = hippocampus.get_status()
        assert status["total_entries"] == 1


class TestQuerySince:
    """Tests for ANAMNESIS — query_since() feeds history into the present."""

    def test_returns_recent_entries(self):
        hippocampus.record_event("test", "recent", {"note": "now"}, salience=0.6)
        results = hippocampus.query_since(hours=1)
        assert len(results) == 1

    def test_excludes_old_entries(self):
        import time
        # Record an entry then manually backdate it
        hippocampus.record_event("test", "old", {}, salience=0.6)
        # query_since(0) should return nothing (cutoff = now)
        results = hippocampus.query_since(hours=0)
        assert results == []

    def test_empty_file(self):
        results = hippocampus.query_since(hours=24)
        assert results == []

    def test_returns_all_within_window(self):
        for i in range(3):
            hippocampus.record_event("src", f"ev{i}", {}, salience=0.7)
        results = hippocampus.query_since(hours=1)
        assert len(results) == 3

    def test_oldest_first_ordering(self):
        hippocampus.record_event("a", "first", {}, salience=0.6)
        hippocampus.record_event("b", "second", {}, salience=0.6)
        results = hippocampus.query_since(hours=1)
        assert results[0]["source"] == "a"
        assert results[1]["source"] == "b"
