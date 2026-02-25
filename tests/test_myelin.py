"""Tests for MYELIN — Context Compression."""
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

_tmpdir = tempfile.mkdtemp()
_state_dir = Path(_tmpdir) / "state"
_state_dir.mkdir()

with patch("pulse.src.thalamus._DEFAULT_STATE_DIR", _state_dir), \
     patch("pulse.src.thalamus._DEFAULT_BROADCAST_FILE", _state_dir / "broadcast.jsonl"):
    import pulse.src.thalamus as thalamus
    import pulse.src.myelin as myelin_mod
    from pulse.src.myelin import Myelin, REFERENCE_THRESHOLD, _PRE_SEEDED


@pytest.fixture(autouse=True)
def clean_state(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    broadcast = state_dir / "broadcast.jsonl"

    with patch.object(myelin_mod, "_DEFAULT_STATE_DIR", state_dir), \
         patch.object(myelin_mod, "_DEFAULT_LEXICON_FILE", state_dir / "myelin-lexicon.json"), \
         patch.object(thalamus, "_DEFAULT_STATE_DIR", state_dir), \
         patch.object(thalamus, "_DEFAULT_BROADCAST_FILE", broadcast):
        myelin_mod._instance = None
        yield


class TestConceptTracking:
    def test_track_increments_count(self):
        m = Myelin()
        for i in range(3):
            m.track_concept("test thing", "a test thing description")
        assert m._tracking["TEST-THING"]["references"] == 3

    def test_track_preseeded_increments(self):
        m = Myelin()
        m.track_concept("WEATHER-BOT", "weather stuff")
        assert m._concepts["WEATHER-BOT"]["references"] == REFERENCE_THRESHOLD + 1


class TestCompressionExpansion:
    def test_compress_replaces_full_text(self):
        m = Myelin()
        full = m._concepts["WEATHER-BOT"]["full"]
        text = f"I was working on {full} today"
        compressed = m.compress(text)
        assert "[WEATHER-BOT]" in compressed
        assert full not in compressed

    def test_expand_reverses_compression(self):
        m = Myelin()
        full = m._concepts["WEATHER-BOT"]["full"]
        text = f"I was working on {full} today"
        compressed = m.compress(text)
        expanded = m.expand(compressed)
        assert expanded == text

    def test_roundtrip(self):
        m = Myelin()
        full = m._concepts["GLOBAL-TEMP"]["full"]
        original = f"The {full} is running well"
        assert m.expand(m.compress(original)) == original


class TestLexiconUpdate:
    def test_promotion_at_threshold(self):
        m = Myelin()
        for i in range(REFERENCE_THRESHOLD):
            m.track_concept("new idea", "a brand new idea for testing")
        assert "NEW-IDEA" in m._tracking
        m.update_lexicon()
        assert "NEW-IDEA" in m._concepts
        assert "NEW-IDEA" not in m._tracking

    def test_below_threshold_stays_tracking(self):
        m = Myelin()
        for i in range(REFERENCE_THRESHOLD - 1):
            m.track_concept("partial", "not enough refs")
        m.update_lexicon()
        assert "PARTIAL" not in m._concepts
        assert "PARTIAL" in m._tracking

    def test_demotion_stale_concepts(self):
        m = Myelin()
        # Add a concept manually with old timestamp
        old_ts = int((time.time() - 8 * 86400) * 1000)  # 8 days ago
        m._concepts["OLD-THING"] = {
            "full": "something old",
            "references": 10,
            "last_used": old_ts,
            "created": old_ts,
        }
        m.update_lexicon()
        assert "OLD-THING" not in m._concepts

    def test_preseeded_never_demoted(self):
        m = Myelin()
        old_ts = int((time.time() - 30 * 86400) * 1000)
        m._concepts["WEATHER-BOT"]["last_used"] = old_ts
        m.update_lexicon()
        assert "WEATHER-BOT" in m._concepts  # pre-seeded, not demoted


class TestNeverCompress:
    def test_names_not_tracked(self):
        m = Myelin()
        m.track_concept("Josh", "Josh the human")
        assert "JOSH" not in m._tracking
        assert "JOSH" not in m._concepts

    def test_iris_not_tracked(self):
        m = Myelin()
        m.track_concept("Iris", "Iris the AI")
        assert "IRIS" not in m._tracking

    def test_emotions_not_tracked(self):
        m = Myelin()
        m.track_concept("love", "the feeling of love")
        assert "LOVE" not in m._tracking


class TestPreSeeded:
    def test_all_preseeded_loaded(self):
        m = Myelin()
        for key in _PRE_SEEDED:
            assert key in m._concepts, f"{key} not in concepts"

    def test_preseeded_have_correct_full(self):
        m = Myelin()
        assert "prediction markets" in m._concepts["WEATHER-BOT"]["full"]


class TestTokenSavings:
    def test_estimate_savings(self):
        m = Myelin()
        full = m._concepts["WEATHER-BOT"]["full"]
        text = f"Working on {full} and also {full} again"
        savings = m.estimate_savings(text)
        assert savings["tokens_saved"] > 0
        assert savings["compression_ratio"] < 1.0


class TestThalamusIntegration:
    def test_promotion_broadcasts(self):
        m = Myelin()
        for i in range(REFERENCE_THRESHOLD):
            m.track_concept("broadcast test", "something to broadcast")
        m.update_lexicon()
        entries = thalamus.read_by_source("myelin")
        assert any(e["data"].get("action") == "promoted" for e in entries)


class TestGetLexicon:
    def test_lexicon_format(self):
        m = Myelin()
        lex = m.get_lexicon()
        assert "WEATHER-BOT" in lex
        assert lex["WEATHER-BOT"]["shorthand"] == "[WEATHER-BOT]"
        assert "full" in lex["WEATHER-BOT"]
