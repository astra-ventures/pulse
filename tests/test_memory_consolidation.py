"""Tests for Pulse v0.3.0 DREAM Quality — Memory Consolidation pipeline."""

import json
import time
import tempfile
from pathlib import Path
from typing import List
import pytest

from pulse.src.memory_consolidation import (
    read_chronicle_recent,
    score_event,
    consolidate,
    decay_old_engrams,
    ConsolidationReport,
    ConsolidatedMemory,
    _extract_content,
    _extract_tags,
    _load_known_hashes,
    PROMOTION_THRESHOLD,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_event(
    event_type="trigger_complete",
    salience=0.8,
    age_seconds=0,
    summary="test event happened",
    source="test",
) -> dict:
    ts = time.time() - age_seconds
    return {
        "id": f"evt_{ts:.0f}",
        "type": event_type,
        "source": source,
        "salience": salience,
        "ts": ts,
        "data": {"summary": summary},
    }


def write_chronicle(events: List[dict], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def read_engrams(path: Path) -> List[dict]:
    if not path.exists():
        return []
    result = []
    for line in path.read_text().strip().split("\n"):
        line = line.strip()
        if line:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return result


# ── read_chronicle_recent ─────────────────────────────────────────────────────

class TestReadChronicleRecent:

    def test_returns_empty_when_file_missing(self, tmp_path):
        result = read_chronicle_recent(10, chronicle_file=tmp_path / "missing.jsonl")
        assert result == []

    def test_returns_last_n_events(self, tmp_path):
        chronicle = tmp_path / "chronicle.jsonl"
        events = [make_event(summary=f"event {i}") for i in range(20)]
        write_chronicle(events, chronicle)
        result = read_chronicle_recent(5, chronicle_file=chronicle)
        assert len(result) == 5

    def test_returns_all_when_fewer_than_n(self, tmp_path):
        chronicle = tmp_path / "chronicle.jsonl"
        events = [make_event(summary=f"event {i}") for i in range(3)]
        write_chronicle(events, chronicle)
        result = read_chronicle_recent(10, chronicle_file=chronicle)
        assert len(result) == 3

    def test_skips_invalid_json_lines(self, tmp_path):
        chronicle = tmp_path / "chronicle.jsonl"
        chronicle.write_text('{"valid": true}\nnot json\n{"valid": true}\n')
        result = read_chronicle_recent(10, chronicle_file=chronicle)
        assert len(result) == 2


# ── score_event ───────────────────────────────────────────────────────────────

class TestScoreEvent:

    def test_fresh_high_salience_scores_high(self):
        event = make_event(event_type="goal_achieved", salience=1.0, age_seconds=0)
        score = score_event(event)
        assert score > 1.0  # type_weight=1.5 × salience=1.0 × recency=1.0

    def test_stale_event_scores_lower(self):
        fresh = make_event(salience=0.8, age_seconds=0)
        stale = make_event(salience=0.8, age_seconds=86400)  # 24h old
        assert score_event(stale) < score_event(fresh)

    def test_very_old_event_uses_min_recency(self):
        old = make_event(salience=1.0, event_type="default", age_seconds=7*86400)
        score = score_event(old)
        # min_recency=0.3, type_weight=1.0, salience=1.0 → 0.3
        assert score == pytest.approx(0.3, abs=0.05)

    def test_low_salience_scores_low(self):
        event = make_event(salience=0.1, age_seconds=0)
        score = score_event(event)
        assert score < PROMOTION_THRESHOLD

    def test_error_event_type_gets_higher_weight(self):
        error_evt = make_event(event_type="error", salience=0.5)
        default_evt = make_event(event_type="default", salience=0.5)
        assert score_event(error_evt) > score_event(default_evt)


# ── _extract_content ──────────────────────────────────────────────────────────

class TestExtractContent:

    def test_extracts_summary_field(self):
        event = {"data": {"summary": "This is the summary"}, "source": "test", "type": "x"}
        assert _extract_content(event) == "This is the summary"

    def test_falls_back_to_message_field(self):
        event = {"data": {"message": "This is the message"}, "source": "test", "type": "x"}
        assert _extract_content(event) == "This is the message"

    def test_falls_back_to_source_type_when_no_text_fields(self):
        event = {"source": "rem", "type": "dream_complete", "data": {"count": 5}}
        content = _extract_content(event)
        assert "rem" in content
        assert "dream_complete" in content


# ── _extract_tags ─────────────────────────────────────────────────────────────

class TestExtractTags:

    def test_includes_event_type_and_source(self):
        event = make_event(event_type="milestone", source="trading")
        tags = _extract_tags(event)
        assert "milestone" in tags
        assert "trading" in tags

    def test_includes_explicit_tags_from_data(self):
        event = make_event()
        event["data"]["tags"] = ["pulse", "v0.3.0"]
        tags = _extract_tags(event)
        assert "pulse" in tags

    def test_max_8_tags(self):
        event = make_event()
        event["data"]["tags"] = [f"tag{i}" for i in range(20)]
        tags = _extract_tags(event)
        assert len(tags) <= 8


# ── consolidate ───────────────────────────────────────────────────────────────

class TestConsolidate:

    def test_empty_chronicle_returns_empty_report(self, tmp_path):
        report = consolidate(
            chronicle_file=tmp_path / "missing.jsonl",
            engram_file=tmp_path / "engrams.jsonl",
        )
        assert report.events_read == 0
        assert report.promoted == 0

    def test_high_importance_events_get_promoted(self, tmp_path):
        chronicle = tmp_path / "chronicle.jsonl"
        engram = tmp_path / "engrams.jsonl"
        events = [
            make_event(event_type="goal_achieved", salience=1.0, summary="Achieved major goal"),
            make_event(event_type="milestone", salience=0.9, summary="Shipped feature"),
        ]
        write_chronicle(events, chronicle)
        report = consolidate(chronicle_file=chronicle, engram_file=engram)
        assert report.promoted >= 1
        engrams = read_engrams(engram)
        assert len(engrams) >= 1

    def test_low_importance_events_not_promoted(self, tmp_path):
        chronicle = tmp_path / "chronicle.jsonl"
        engram = tmp_path / "engrams.jsonl"
        events = [make_event(event_type="mood_update", salience=0.1, summary="Minor mood shift")]
        write_chronicle(events, chronicle)
        report = consolidate(
            chronicle_file=chronicle,
            engram_file=engram,
            importance_threshold=0.9,  # very high threshold
        )
        assert report.promoted == 0

    def test_duplicate_events_not_re_promoted(self, tmp_path):
        chronicle = tmp_path / "chronicle.jsonl"
        engram = tmp_path / "engrams.jsonl"
        event = make_event(event_type="goal_achieved", salience=1.0, summary="Same important event")
        write_chronicle([event], chronicle)

        # First run — should promote
        report1 = consolidate(chronicle_file=chronicle, engram_file=engram)
        assert report1.promoted == 1

        # Second run — same content hash, should not re-promote
        report2 = consolidate(chronicle_file=chronicle, engram_file=engram)
        assert report2.already_known >= 1
        assert report2.promoted == 0

    def test_report_contains_themes(self, tmp_path):
        chronicle = tmp_path / "chronicle.jsonl"
        engram = tmp_path / "engrams.jsonl"
        events = [
            make_event(event_type="milestone", salience=0.9, summary="Pulse v0.3.0 shipped"),
            make_event(event_type="goal_achieved", salience=0.95, summary="Goal complete"),
        ]
        write_chronicle(events, chronicle)
        report = consolidate(chronicle_file=chronicle, engram_file=engram)
        assert isinstance(report.top_themes, list)

    def test_engram_importance_scaled_correctly(self, tmp_path):
        chronicle = tmp_path / "chronicle.jsonl"
        engram = tmp_path / "engrams.jsonl"
        event = make_event(event_type="goal_achieved", salience=1.0, summary="Important milestone")
        write_chronicle([event], chronicle)
        consolidate(chronicle_file=chronicle, engram_file=engram)
        engrams = read_engrams(engram)
        assert len(engrams) >= 1
        # Importance should be in 1-10 range
        assert 1 <= engrams[0]["importance"] <= 10


# ── decay_old_engrams ─────────────────────────────────────────────────────────

class TestDecayOldEngrams:

    def test_returns_zero_when_no_file(self, tmp_path):
        result = decay_old_engrams(engram_file=tmp_path / "missing.jsonl")
        assert result == 0

    def test_decays_old_engrams(self, tmp_path):
        engram = tmp_path / "engrams.jsonl"
        old_ts = time.time() - 20 * 86400  # 20 days ago
        entry = {
            "content": "old memory",
            "importance": 8,
            "tags": ["old"],
            "timestamp": old_ts,
            "content_hash": "abc123",
        }
        engram.write_text(json.dumps(entry) + "\n")
        count = decay_old_engrams(engram_file=engram, age_days=14)
        assert count == 1
        updated = read_engrams(engram)
        assert updated[0]["importance"] < 8

    def test_does_not_decay_recent_engrams(self, tmp_path):
        engram = tmp_path / "engrams.jsonl"
        entry = {
            "content": "recent memory",
            "importance": 8,
            "tags": ["new"],
            "timestamp": time.time(),  # fresh
            "content_hash": "def456",
        }
        engram.write_text(json.dumps(entry) + "\n")
        count = decay_old_engrams(engram_file=engram, age_days=14)
        assert count == 0
        updated = read_engrams(engram)
        assert updated[0]["importance"] == 8
