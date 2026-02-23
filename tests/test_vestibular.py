"""Tests for VESTIBULAR — Balance Monitor."""

import json
from unittest.mock import patch

import pytest

from pulse.src import vestibular, thalamus


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    bf = tmp_path / "thalamus.jsonl"
    sf = tmp_path / "vestibular-state.json"
    with patch.object(vestibular, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(vestibular, "_DEFAULT_STATE_FILE", sf), \
         patch.object(thalamus, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(thalamus, "_DEFAULT_BROADCAST_FILE", bf):
        yield tmp_path


class TestRecordActivity:
    def test_record(self):
        vestibular.record_activity("building", 5)
        status = vestibular.get_status()
        assert status["counters"]["building"] == 5

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError):
            vestibular.record_activity("napping")


class TestCheckBalance:
    def test_balanced(self):
        vestibular.record_activity("building", 5)
        vestibular.record_activity("shipping", 5)
        vestibular.record_activity("working", 6)
        vestibular.record_activity("reflecting", 4)
        vestibular.record_activity("autonomy", 5)
        vestibular.record_activity("collaboration", 5)
        result = vestibular.check_balance()
        assert result["healthy"] is True

    def test_imbalanced(self):
        vestibular.record_activity("building", 100)
        vestibular.record_activity("shipping", 1)
        result = vestibular.check_balance()
        assert len(result["imbalances"]) > 0
        assert not result["healthy"]

    def test_imbalance_broadcasts_need_signal(self):
        vestibular.record_activity("building", 100)
        vestibular.record_activity("shipping", 1)
        vestibular.check_balance()
        entries = thalamus.read_by_source("vestibular")
        assert any(e["type"] == "need_signal" for e in entries)

    def test_zero_counts_default_balanced(self):
        result = vestibular.check_balance()
        assert result["healthy"] is True
