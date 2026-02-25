"""Tests for BUFFER — Working Memory."""
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from pulse.src import buffer, thalamus


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    """Redirect state files to tmp."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    archive_dir = state_dir / "buffer-archive"
    archive_dir.mkdir()
    monkeypatch.setattr(buffer, "_DEFAULT_STATE_DIR", state_dir)
    monkeypatch.setattr(buffer, "_DEFAULT_BUFFER_FILE", state_dir / "buffer.json")
    monkeypatch.setattr(buffer, "_DEFAULT_ARCHIVE_DIR", archive_dir)
    monkeypatch.setattr(thalamus, "_DEFAULT_STATE_DIR", state_dir)
    monkeypatch.setattr(thalamus, "_DEFAULT_BROADCAST_FILE", state_dir / "broadcast.jsonl")


class TestCaptureGet:
    def test_capture_roundtrip(self):
        result = buffer.capture(
            conversation_summary="Talking about Pulse architecture",
            decisions=["Use JSONL for bus"],
            action_items=["Build buffer module"],
            emotional_state={"valence": 0.5, "intensity": 0.3, "context": "focused"},
            open_threads=["How to handle compaction"],
        )
        assert result["decisions"] == ["Use JSONL for bus"]
        assert result["captured_at"] > 0

        loaded = buffer.get_buffer()
        assert loaded["decisions"] == ["Use JSONL for bus"]
        assert loaded["key_context"] == "Talking about Pulse architecture"
        assert loaded["action_items"] == ["Build buffer module"]

    def test_capture_overwrites_previous(self):
        buffer.capture("first", ["d1"], [], {}, [])
        buffer.capture("second", ["d2"], [], {}, [])
        assert buffer.get_buffer()["decisions"] == ["d2"]
        assert buffer.get_buffer()["key_context"] == "second"

    def test_capture_with_participants_and_topic(self):
        result = buffer.capture("summary", [], [], {}, [], participants=["Josh", "Iris"], topic="Architecture")
        assert result["participants"] == ["Josh", "Iris"]
        assert result["topic"] == "Architecture"

    def test_capture_broadcasts_to_thalamus(self):
        buffer.capture("test", ["d"], [], {"valence": 0.5}, [])
        entries = thalamus.read_by_source("buffer")
        assert len(entries) >= 1
        assert entries[-1]["type"] == "state"


class TestUpdateField:
    def test_update_existing_field(self):
        buffer.capture("ctx", [], [], {}, [])
        buffer.update_field("topic", "New topic")
        assert buffer.get_buffer()["topic"] == "New topic"

    def test_update_decisions(self):
        buffer.capture("ctx", ["old"], [], {}, [])
        buffer.update_field("decisions", ["new1", "new2"])
        assert buffer.get_buffer()["decisions"] == ["new1", "new2"]

    def test_update_unknown_field_raises(self):
        buffer.capture("ctx", [], [], {}, [])
        with pytest.raises(KeyError):
            buffer.update_field("nonexistent_field", "value")

    def test_update_refreshes_timestamp(self):
        buffer.capture("ctx", [], [], {}, [])
        t1 = buffer.get_buffer()["captured_at"]
        time.sleep(0.01)
        buffer.update_field("topic", "x")
        t2 = buffer.get_buffer()["captured_at"]
        assert t2 >= t1


class TestCompactSummary:
    def test_empty_buffer_returns_empty(self):
        assert buffer.get_compact_summary() == ""

    def test_includes_key_fields(self):
        buffer.capture(
            "Building the nervous system",
            ["Use thalamus bus"],
            ["Write tests"],
            {"valence": 0.7, "intensity": 0.4, "context": "excited"},
            ["Integration patterns"],
            topic="Pulse Architecture",
            participants=["Josh", "Iris"],
        )
        summary = buffer.get_compact_summary()
        assert "Pulse Architecture" in summary
        assert "Use thalamus bus" in summary
        assert "Write tests" in summary
        assert "excited" in summary

    def test_respects_max_tokens(self):
        buffer.capture(
            "x" * 5000,
            ["d" * 500],
            ["a" * 500],
            {"valence": 0.0, "intensity": 0.0, "context": "c" * 500},
            ["t" * 500],
        )
        summary = buffer.get_compact_summary(max_tokens=50)
        assert len(summary) <= 200 + 3  # 50*4 chars + "..."

    def test_summary_under_default_limit(self):
        buffer.capture("Short context", ["d1"], ["a1"], {"valence": 0.0, "intensity": 0.0, "context": ""}, [])
        summary = buffer.get_compact_summary(max_tokens=500)
        assert len(summary) <= 2000


class TestRotate:
    def test_rotate_archives_and_clears(self):
        buffer.capture("important context", ["key decision"], [], {}, [])
        archive_path = buffer.rotate()
        assert archive_path is not None
        assert Path(archive_path).exists()

        # Buffer should be empty now
        buf = buffer.get_buffer()
        assert buf["decisions"] == []
        assert buf["captured_at"] == 0

        # Archive should contain old data
        archived = json.loads(Path(archive_path).read_text())
        assert archived["decisions"] == ["key decision"]

    def test_rotate_empty_buffer_returns_none(self):
        assert buffer.rotate() is None

    def test_rotate_broadcasts(self):
        buffer.capture("ctx", [], [], {}, [])
        buffer.rotate()
        entries = thalamus.read_by_source("buffer")
        types = [e["type"] for e in entries]
        assert "rotate" in types


class TestAutoCapture:
    def test_extracts_decisions(self):
        messages = [
            {"role": "user", "content": "Let's go with Python for the backend"},
            {"role": "assistant", "content": "Agreed, Python is the right choice"},
        ]
        result = buffer.auto_capture(messages)
        assert len(result["decisions"]) > 0

    def test_extracts_action_items(self):
        messages = [
            {"role": "user", "content": "I need to fix the deployment script"},
            {"role": "assistant", "content": "I'll update the config file"},
        ]
        result = buffer.auto_capture(messages)
        assert len(result["action_items"]) > 0

    def test_extracts_open_threads(self):
        messages = [
            {"role": "user", "content": "What about the database migration?"},
        ]
        result = buffer.auto_capture(messages)
        assert len(result["open_threads"]) > 0

    def test_detects_positive_sentiment(self):
        messages = [
            {"role": "user", "content": "This is great work, I'm excited about it!"},
            {"role": "assistant", "content": "Awesome, happy to help!"},
        ]
        result = buffer.auto_capture(messages)
        assert result["emotional_state"]["valence"] > 0

    def test_detects_negative_sentiment(self):
        messages = [
            {"role": "user", "content": "I'm frustrated and disappointed with the results"},
        ]
        result = buffer.auto_capture(messages)
        assert result["emotional_state"]["valence"] < 0

    def test_extracts_participants(self):
        messages = [
            {"role": "user", "sender": "Josh", "content": "hello"},
            {"role": "assistant", "sender": "Iris", "content": "hi"},
        ]
        result = buffer.auto_capture(messages)
        assert "Josh" in result["participants"]
        assert "Iris" in result["participants"]

    def test_empty_messages(self):
        result = buffer.auto_capture([])
        assert result["decisions"] == []
        assert result["action_items"] == []
