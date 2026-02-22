"""Tests for ENGRAM — Spatial + Episodic Memory Indexing."""

import json
import time
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from pulse.src.engram import (
    Engram, encode, recall, recall_raw, recall_by_place, recall_by_emotion,
    recall_by_time, consolidate, get_places, prune, _load_store, _save_store,
)


@pytest.fixture(autouse=True)
def clean_store(tmp_path, monkeypatch):
    state_file = tmp_path / "engram-store.json"
    monkeypatch.setattr("pulse.src.engram._DEFAULT_STATE_FILE", state_file)
    monkeypatch.setattr("pulse.src.engram._DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr("pulse.src.engram.thalamus", MagicMock())
    yield state_file


class TestEncode:
    def test_basic_encode(self):
        eg = encode("Had a great conversation", {"valence": 0.8, "intensity": 0.9, "label": "joy"}, "main_session")
        assert eg.event == "Had a great conversation"
        assert eg.emotion["label"] == "joy"
        assert eg.location == "main_session"
        assert eg.id

    def test_encode_persists(self):
        encode("Event 1", {"valence": 0.5, "intensity": 0.5, "label": "calm"}, "discord")
        store = _load_store()
        assert len(store) == 1

    def test_encode_auto_associates(self):
        encode("First", {"valence": 0, "intensity": 0.3, "label": "neutral"}, "dream")
        eg2 = encode("Second", {"valence": 0, "intensity": 0.3, "label": "neutral"}, "dream")
        assert len(eg2.associations) == 1

    def test_encode_with_sensory(self):
        eg = encode("Voice call", {"valence": 0.9, "intensity": 0.8, "label": "warmth"}, "main_session",
                     sensory={"voice": True, "image": False, "text_tone": "warm"})
        assert eg.sensory["voice"] is True

    def test_encode_default_timestamp(self):
        eg = encode("Now", {"valence": 0, "intensity": 0.5, "label": "neutral"}, "cron_session")
        assert eg.timestamp > 0

    def test_encode_custom_timestamp(self):
        eg = encode("Past", {"valence": 0, "intensity": 0.5, "label": "neutral"}, "cron_session", timestamp=1000.0)
        assert eg.timestamp == 1000.0


class TestRecall:
    def test_recall_by_keyword(self):
        encode("Wrote a poem about stars", {"valence": 0.7, "intensity": 0.6, "label": "creative"}, "main_session")
        encode("Fixed a bug in spine", {"valence": 0.3, "intensity": 0.4, "label": "satisfaction"}, "cron_session")
        result = recall("poem stars")
        assert "poem" in result.lower()

    def test_recall_updates_count(self):
        encode("Unique memory", {"valence": 0, "intensity": 0.5, "label": "neutral"}, "main_session")
        raw = recall_raw("Unique memory")
        assert raw[0]["recall_count"] == 1

    def test_recall_empty(self):
        result = recall("nonexistent thing")
        assert result == ""

    def test_recall_returns_string(self):
        encode("Testing recall format", {"valence": 0.5, "intensity": 0.5, "label": "focus"}, "main_session")
        result = recall("testing recall")
        assert isinstance(result, str)
        assert "ENGRAM recall" in result

    def test_recall_limit(self):
        for i in range(10):
            encode(f"Event {i} about coding", {"valence": 0.5, "intensity": 0.5, "label": "focus"}, "main_session")
        raw = recall_raw("coding", n=3)
        assert len(raw) == 3


class TestRecallByPlace:
    def test_place_recall(self):
        encode("Discord chat", {"valence": 0.5, "intensity": 0.5, "label": "social"}, "discord")
        encode("Main session work", {"valence": 0.5, "intensity": 0.5, "label": "focus"}, "main_session")
        results = recall_by_place("discord")
        assert len(results) == 1
        assert results[0].location == "discord"

    def test_place_recall_empty(self):
        results = recall_by_place("nonexistent")
        assert results == []


class TestRecallByEmotion:
    def test_emotion_filter(self):
        encode("Happy moment", {"valence": 0.9, "intensity": 0.8, "label": "joy"}, "main_session")
        encode("Sad moment", {"valence": -0.8, "intensity": 0.7, "label": "sadness"}, "main_session")
        results = recall_by_emotion((0.5, 1.0), 0.5)
        assert len(results) == 1
        assert results[0].emotion["label"] == "joy"

    def test_emotion_filter_intensity(self):
        encode("Low intensity", {"valence": 0.5, "intensity": 0.2, "label": "calm"}, "main_session")
        encode("High intensity", {"valence": 0.5, "intensity": 0.9, "label": "excitement"}, "main_session")
        results = recall_by_emotion((0.0, 1.0), 0.5)
        assert len(results) == 1


class TestRecallByTime:
    def test_time_window(self):
        encode("Old", {"valence": 0, "intensity": 0.5, "label": "n"}, "main_session", timestamp=1000.0)
        encode("Recent", {"valence": 0, "intensity": 0.5, "label": "n"}, "main_session", timestamp=5000.0)
        results = recall_by_time(4000.0, 6000.0)
        assert len(results) == 1
        assert results[0].event == "Recent"


class TestConsolidate:
    def test_consolidation(self):
        eg1 = encode("Wrote code", {"valence": 0.5, "intensity": 0.6, "label": "focus"}, "main_session")
        eg2 = encode("Dreamed of ocean", {"valence": 0.7, "intensity": 0.5, "label": "peace"}, "dream")
        result = consolidate([eg1, eg2])
        assert "focus" in result
        assert "peace" in result
        assert "→" in result

    def test_consolidate_empty(self):
        assert consolidate([]) == ""


class TestGetPlaces:
    def test_places_map(self):
        encode("A", {"valence": 0, "intensity": 0.5, "label": "calm"}, "discord")
        encode("B", {"valence": 0, "intensity": 0.5, "label": "calm"}, "discord")
        encode("C", {"valence": 0, "intensity": 0.5, "label": "joy"}, "main_session")
        places = get_places()
        assert places["discord"]["count"] == 2
        assert places["discord"]["dominant_emotion"] == "calm"
        assert places["main_session"]["count"] == 1


class TestPrune:
    def test_prune_removes_low_intensity(self):
        for i in range(15):
            encode(f"E{i}", {"valence": 0, "intensity": i * 0.06, "label": "n"}, "main_session")
        prune(max_entries=10)
        store = _load_store()
        assert len(store) == 10

    def test_prune_noop_under_max(self):
        encode("Only one", {"valence": 0, "intensity": 0.5, "label": "n"}, "main_session")
        prune(max_entries=10)
        store = _load_store()
        assert len(store) == 1


class TestRecallWeighted:
    """Tests for the weighted recall (ENGRAM native recall replacing hippocampus)."""

    def test_recall_empty_store(self):
        """No memories → empty string returned gracefully."""
        result = recall("anything at all")
        assert result == ""

    def test_recall_keyword_match(self):
        """Memory with matching keyword scores higher."""
        encode("Built a new API endpoint", {"valence": 0.5, "intensity": 0.5, "label": "focus"}, "main_session")
        encode("Went for a dream walk", {"valence": 0.7, "intensity": 0.3, "label": "calm"}, "dream")
        raw = recall_raw("API endpoint")
        assert len(raw) >= 1
        assert "API" in raw[0].get("event", "")

    def test_recall_importance_weighted(self):
        """Higher importance memories ranked higher when keywords match equally."""
        now = time.time() * 1000
        # Both have the same keyword, but different importance (via intensity)
        encode("Deploy server alpha", {"valence": 0.5, "intensity": 0.2, "label": "focus"}, "cron_session", timestamp=now)
        encode("Deploy server beta", {"valence": 0.5, "intensity": 0.9, "label": "focus"}, "cron_session", timestamp=now)
        raw = recall_raw("Deploy server")
        assert len(raw) == 2
        # Higher intensity should score higher
        assert raw[0].get("event") == "Deploy server beta"

    def test_recall_recency_weighted(self):
        """Recent memories ranked higher than old ones (equal keywords and importance)."""
        old_ts = (time.time() - 7 * 86400) * 1000  # 7 days ago
        new_ts = time.time() * 1000                  # now
        encode("Write documentation old", {"valence": 0.5, "intensity": 0.5, "label": "focus"}, "main_session", timestamp=old_ts)
        encode("Write documentation new", {"valence": 0.5, "intensity": 0.5, "label": "focus"}, "main_session", timestamp=new_ts)
        raw = recall_raw("Write documentation")
        assert len(raw) == 2
        assert raw[0].get("event") == "Write documentation new"

    def test_recall_returns_n_results(self):
        """Respects n limit."""
        for i in range(8):
            encode(f"Task {i} about coding", {"valence": 0.5, "intensity": 0.5, "label": "focus"}, "main_session")
        raw = recall_raw("coding", n=3)
        assert len(raw) == 3
        text = recall("coding", n=3)
        assert "3 memories" in text

    def test_recall_raw_returns_dicts(self):
        """recall_raw returns list of dicts with _score field."""
        encode("Research quantum computing", {"valence": 0.6, "intensity": 0.7, "label": "curiosity"}, "main_session")
        raw = recall_raw("quantum computing")
        assert isinstance(raw, list)
        assert len(raw) >= 1
        assert isinstance(raw[0], dict)
        assert "_score" in raw[0]
        assert isinstance(raw[0]["_score"], float)

    def test_recall_handles_hippocampus_format(self):
        """Recall works with memories stored in hippocampus format (content/tags/source/importance/ts)."""
        # Write a store in hippocampus format directly
        store = [
            {
                "content": "Deployed new feature to production",
                "importance": 8,
                "ts": time.time(),
                "tags": ["deploy", "production", "feature"],
                "source": "github",
            },
            {
                "content": "Reviewed pull request on auth module",
                "importance": 5,
                "ts": time.time(),
                "tags": ["review", "auth"],
                "source": "github",
            },
        ]
        _save_store(store)
        raw = recall_raw("deploy production feature")
        assert len(raw) >= 1
        assert "Deployed" in raw[0].get("content", "")

    def test_recall_graceful_on_corrupt_store(self, tmp_path, monkeypatch):
        """Corrupt store file doesn't crash recall."""
        state_file = tmp_path / "engram-store.json"
        state_file.write_text("not valid json {{{")
        monkeypatch.setattr("pulse.src.engram._DEFAULT_STATE_FILE", state_file)
        result = recall("anything")
        assert result == ""

    def test_recall_no_query(self):
        """Empty query returns empty."""
        encode("Something", {"valence": 0.5, "intensity": 0.5, "label": "focus"}, "main_session")
        result = recall("")
        assert result == ""


class TestEngramDataclass:
    def test_roundtrip(self):
        eg = Engram(id="test", event="hello", emotion={"valence": 0, "intensity": 0.5, "label": "n"},
                    location="main_session", timestamp=1000.0)
        d = eg.to_dict()
        eg2 = Engram.from_dict(d)
        assert eg2.id == "test"
        assert eg2.event == "hello"
