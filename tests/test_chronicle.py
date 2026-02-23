"""Tests for CHRONICLE — Automated Historian."""

import json
from datetime import datetime
from unittest.mock import patch

import pytest

from pulse.src import chronicle, thalamus


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    bf = tmp_path / "thalamus.jsonl"
    cf = tmp_path / "chronicle.jsonl"
    with patch.object(chronicle, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(chronicle, "_DEFAULT_CHRONICLE_FILE", cf), \
         patch.object(thalamus, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(thalamus, "_DEFAULT_BROADCAST_FILE", bf):
        yield tmp_path


class TestRecordEvent:
    def test_record_significant(self):
        result = chronicle.record_event("test", "important", {"key": "val"}, salience=0.7)
        assert result is not None
        assert result["source"] == "test"

    def test_skip_insignificant(self):
        result = chronicle.record_event("test", "minor", {}, salience=0.2)
        assert result is None

    def test_events_in_file(self, tmp_path):
        chronicle.record_event("test", "event1", {"a": 1}, salience=0.6)
        chronicle.record_event("test", "event2", {"b": 2}, salience=0.8)
        entries = chronicle.query_recent()
        assert len(entries) == 2


class TestCaptureFromThalamus:
    def test_capture(self):
        thalamus.append({"source": "endocrine", "type": "mood_update", "salience": 0.7, "data": {}})
        thalamus.append({"source": "retina", "type": "attention", "salience": 0.2, "data": {}})
        count = chronicle.capture_from_thalamus()
        assert count >= 1  # only the high-salience one


class TestQuery:
    def test_query_by_date(self):
        chronicle.record_event("test", "today", {}, salience=0.6)
        today = datetime.now().strftime("%Y-%m-%d")
        results = chronicle.query_by_date(today)
        assert len(results) >= 1

    def test_query_recent(self):
        for i in range(5):
            chronicle.record_event("test", f"event{i}", {}, salience=0.6)
        results = chronicle.query_recent(3)
        assert len(results) == 3

    def test_query_empty(self):
        results = chronicle.query_by_date("2020-01-01")
        assert results == []


class TestStatus:
    def test_status_empty(self):
        status = chronicle.get_status()
        assert status["total_entries"] == 0

    def test_status_with_entries(self):
        chronicle.record_event("test", "x", {}, salience=0.6)
        status = chronicle.get_status()
        assert status["total_entries"] == 1
