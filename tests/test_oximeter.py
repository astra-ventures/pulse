"""Tests for OXIMETER — External Perception Tracker."""

import json
from unittest.mock import patch

import pytest

from pulse.src import oximeter, thalamus


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    bf = tmp_path / "thalamus.jsonl"
    sf = tmp_path / "oximeter-state.json"
    with patch.object(oximeter, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(oximeter, "_DEFAULT_STATE_FILE", sf), \
         patch.object(thalamus, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(thalamus, "_DEFAULT_BROADCAST_FILE", bf):
        yield tmp_path


class TestMetrics:
    def test_update_followers(self):
        result = oximeter.update_metrics(followers=500)
        assert result["followers"] == 500

    def test_update_sentiment(self):
        result = oximeter.update_metrics(sentiment=0.8)
        assert result["sentiment"] == 0.8

    def test_sentiment_clamped(self):
        result = oximeter.update_metrics(sentiment=1.5)
        assert result["sentiment"] == 1.0


class TestSelfPerception:
    def test_update(self):
        result = oximeter.update_self_perception(impact=0.7, reception=0.8)
        assert result["impact"] == 0.7


class TestGapDetection:
    def test_no_gap_when_aligned(self):
        oximeter.update_metrics(followers=5000, sentiment=0.7)
        oximeter.update_self_perception(impact=0.5, reception=0.7)
        result = oximeter.detect_gap()
        assert result["overall_gap"] < 0.3

    def test_gap_when_misaligned(self):
        oximeter.update_metrics(followers=100, sentiment=0.3)
        oximeter.update_self_perception(impact=0.9, reception=0.9)
        result = oximeter.detect_gap()
        assert result["overall_gap"] > 0.3
        assert result["self_overestimates"] is True

    def test_large_gap_broadcasts(self):
        oximeter.update_metrics(followers=0, sentiment=0.1)
        oximeter.update_self_perception(impact=0.9, reception=0.9)
        oximeter.detect_gap()
        entries = thalamus.read_by_source("oximeter")
        assert any(e["type"] == "perception_gap" for e in entries)


class TestStatus:
    def test_status(self):
        status = oximeter.get_status()
        assert "metrics" in status
        assert "self_perception" in status
