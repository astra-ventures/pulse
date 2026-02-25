"""Tests for RETINA — Attention Filter."""
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# Patch state dirs before import
_tmpdir = tempfile.mkdtemp()
_state_dir = Path(_tmpdir) / "state"
_state_dir.mkdir()

with patch("pulse.src.thalamus._DEFAULT_STATE_DIR", _state_dir), \
     patch("pulse.src.thalamus._DEFAULT_BROADCAST_FILE", _state_dir / "broadcast.jsonl"):
    import pulse.src.thalamus as thalamus
    # Now patch retina's state
    with patch.dict(os.environ, {}):
        import pulse.src.retina as retina_mod
        from pulse.src.retina import Retina, ScoredSignal


@pytest.fixture(autouse=True)
def clean_state(tmp_path):
    """Reset state for each test."""
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    broadcast = state_dir / "broadcast.jsonl"

    with patch.object(retina_mod, "_DEFAULT_STATE_DIR", state_dir), \
         patch.object(retina_mod, "_DEFAULT_STATE_FILE", state_dir / "retina-state.json"), \
         patch.object(thalamus, "_DEFAULT_STATE_DIR", state_dir), \
         patch.object(thalamus, "_DEFAULT_BROADCAST_FILE", broadcast):
        retina_mod._instance = None
        yield


class TestPriorityRules:
    def test_owner_direct(self):
        r = Retina()
        scored = r.score({"sender": "+15555550100", "text": "hey"})
        assert scored.priority == 1.0
        assert scored.category == "owner_direct"
        assert scored.should_process is True

    def test_owner_mention(self):
        r = Retina()
        scored = r.score({"sender": "+15551234567", "text": "owner said something"})
        assert scored.priority == 0.9
        assert scored.category == "owner_mention"

    def test_high_value_alert_edge(self):
        r = Retina()
        scored = r.score({"edge_pct": 15})
        assert scored.priority == 0.85
        assert scored.category == "high_value_alert"

    def test_high_value_alert_likes(self):
        r = Retina()
        scored = r.score({"likes": 100})
        assert scored.priority == 0.85

    def test_cron_anomaly(self):
        r = Retina()
        scored = r.score({"source_type": "cron", "anomaly": True})
        assert scored.priority == 0.7
        assert scored.category == "cron_anomaly"

    def test_cron_routine(self):
        r = Retina()
        scored = r.score({"source_type": "cron"})
        assert scored.priority == 0.1
        assert scored.category == "cron_routine_success"
        assert scored.should_process is False  # below 0.3 threshold

    def test_heartbeat_quiet(self):
        r = Retina()
        scored = r.score({"source_type": "heartbeat"})
        assert scored.priority == 0.05
        assert scored.should_process is False

    def test_system_health(self):
        r = Retina()
        scored = r.score({"health_level": "yellow"})
        assert scored.priority == 0.8
        assert scored.category == "system_health"

    def test_notable_mention(self):
        r = Retina()
        scored = r.score({"source_type": "mention", "follower_count": 50000})
        assert scored.priority == 0.75

    def test_routine_mention(self):
        r = Retina()
        scored = r.score({"source_type": "mention", "follower_count": 500})
        assert scored.priority == 0.3

    def test_web_content(self):
        r = Retina()
        scored = r.score({"source_type": "web_content"})
        assert scored.priority == 0.2
        assert scored.should_process is False

    def test_unknown_signal(self):
        r = Retina()
        scored = r.score({"random": "data"})
        assert scored.priority == 0.0
        assert scored.category == "unknown"


class TestThresholdFiltering:
    def test_default_threshold(self):
        r = Retina()
        assert r.threshold == 0.3

    def test_below_threshold_not_processed(self):
        r = Retina()
        scored = r.score({"source_type": "web_content"})  # 0.2
        assert scored.should_process is False

    def test_above_threshold_processed(self):
        r = Retina()
        scored = r.score({"sender": "+15555550100", "text": "hi"})  # 1.0
        assert scored.should_process is True


class TestDynamicThreshold:
    def test_spine_orange_raises_threshold(self):
        r = Retina()
        r.set_spine_level("orange")
        # Routine mention at 0.3 now below 0.6 threshold
        scored = r.score({"source_type": "mention", "follower_count": 500})
        assert scored.should_process is False

    def test_spine_red_raises_threshold(self):
        r = Retina()
        r.set_spine_level("red")
        scored = r.score({"source_type": "cron", "anomaly": True})  # 0.7
        assert scored.should_process is True  # 0.7 > 0.6

    def test_focus_mode_blocks_non_josh(self):
        r = Retina()
        r.set_focus_mode(True)
        scored = r.score({"health_level": "yellow"})  # 0.8 but threshold is 0.8
        assert scored.should_process is True  # 0.8 >= 0.8

        scored2 = r.score({"source_type": "cron", "anomaly": True})  # 0.7
        assert scored2.should_process is False  # 0.7 < 0.8

    def test_focus_mode_owner_still_passes(self):
        r = Retina()
        r.set_focus_mode(True)
        scored = r.score({"sender": "+15555550100", "text": "hey"})
        assert scored.should_process is True  # Owner always passes


class TestBatchFiltering:
    def test_filter_batch(self):
        r = Retina()
        signals = [
            {"sender": "+15555550100", "text": "important"},
            {"source_type": "heartbeat"},
            {"health_level": "red"},
            {"source_type": "web_content"},
        ]
        results = r.filter_batch(signals)
        assert len(results) == 2  # josh_direct + system_health
        assert results[0].priority == 1.0
        assert results[1].priority == 0.8


class TestAttentionQueue:
    def test_queue_sorted_by_priority(self):
        r = Retina()
        r.score({"health_level": "yellow"})  # 0.8
        r.score({"sender": "+15555550100", "text": "hi"})  # 1.0
        r.score({"source_type": "mention", "follower_count": 50000})  # 0.75
        q = r.get_attention_queue()
        assert len(q) == 3
        assert q[0].priority == 1.0
        assert q[1].priority == 0.8

    def test_queue_limit(self):
        r = Retina()
        for i in range(5):
            r.score({"sender": "+15555550100", "text": f"msg {i}"})
        assert len(r.get_attention_queue(limit=3)) == 3


class TestTopicBoost:
    def test_buffer_topic_boosts_matching_signals(self):
        r = Retina()
        r.set_buffer_topic("weather")
        scored = r.score({"source_type": "mention", "follower_count": 500,
                          "text": "weather forecast looks wild"})
        assert scored.priority == 0.5  # 0.3 + 0.2 boost


class TestCustomRules:
    def test_register_custom_rule(self):
        r = Retina()
        r.register_priority_rule("vip_alert", lambda s: s.get("vip"), 0.95)
        scored = r.score({"vip": True})
        assert scored.priority == 0.95
        assert scored.category == "vip_alert"


class TestThalamusIntegration:
    def test_score_writes_to_thalamus(self):
        r = Retina()
        r.score({"sender": "+15555550100", "text": "hi"})
        entries = thalamus.read_by_source("retina")
        assert len(entries) >= 1
        assert entries[-1]["type"] == "attention"
        assert entries[-1]["data"]["category"] == "owner_direct"


class TestScoredSignal:
    def test_to_dict(self):
        s = ScoredSignal({"a": 1}, 0.5, "test", True, "reason")
        d = s.to_dict()
        assert d["priority"] == 0.5
        assert d["category"] == "test"
