"""Tests for ADIPOSE — Token/Energy Budgeting."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from pulse.src import adipose, thalamus


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    bf = tmp_path / "thalamus.jsonl"
    sf = tmp_path / "adipose-state.json"
    with patch.object(adipose, "STATE_DIR", tmp_path), \
         patch.object(adipose, "STATE_FILE", sf), \
         patch.object(thalamus, "STATE_DIR", tmp_path), \
         patch.object(thalamus, "BROADCAST_FILE", bf):
        yield tmp_path


class TestBudgetSetup:
    def test_set_daily_budget(self):
        adipose.set_daily_budget(500_000)
        report = adipose.get_budget_report()
        assert report["daily_budget"] == 500_000

    def test_default_allocations(self):
        adipose.set_daily_budget(1_000_000)
        report = adipose.get_budget_report()
        assert report["categories"]["conversation"]["budget"] == 600_000
        assert report["categories"]["crons"]["budget"] == 250_000
        assert report["categories"]["reserve"]["budget"] == 150_000


class TestAllocation:
    def test_allocate_within_budget(self):
        adipose.set_daily_budget(1_000_000)
        assert adipose.allocate("conversation", 100_000) is True
        assert adipose.get_remaining("conversation") == 500_000

    def test_allocate_over_budget_rejected(self):
        adipose.set_daily_budget(1_000_000)
        assert adipose.allocate("conversation", 700_000) is False

    def test_allocate_unknown_category_raises(self):
        adipose.set_daily_budget(1_000_000)
        with pytest.raises(ValueError):
            adipose.allocate("snacks", 100)

    def test_multiple_allocations_accumulate(self):
        adipose.set_daily_budget(1_000_000)
        adipose.allocate("crons", 50_000)
        adipose.allocate("crons", 50_000)
        assert adipose.get_remaining("crons") == 150_000


class TestBurnRate:
    def test_zero_when_no_usage(self):
        adipose.set_daily_budget(1_000_000)
        assert adipose.get_burn_rate("conversation") == 0.0

    def test_nonzero_after_usage(self):
        adipose.set_daily_budget(1_000_000)
        adipose.allocate("conversation", 10_000)
        # With only one data point, rate calculation uses 1hr default
        rate = adipose.get_burn_rate("conversation")
        assert rate >= 10_000


class TestForecasting:
    def test_infinite_when_no_burn(self):
        adipose.set_daily_budget(1_000_000)
        assert adipose.forecast_depletion("conversation") == float("inf")

    def test_finite_after_usage(self):
        adipose.set_daily_budget(1_000_000)
        adipose.allocate("conversation", 10_000)
        hours = adipose.forecast_depletion("conversation")
        assert hours < float("inf")
        assert hours > 0


class TestEmergencyReserve:
    def test_blocked_when_not_spine_red(self):
        adipose.set_daily_budget(1_000_000)
        assert adipose.emergency_reserve(10_000) is False

    def test_allowed_when_spine_red(self):
        adipose.set_daily_budget(1_000_000)
        adipose.set_spine_red(True)
        assert adipose.emergency_reserve(10_000) is True

    def test_reserve_draw_broadcasts(self):
        adipose.set_daily_budget(1_000_000)
        adipose.set_spine_red(True)
        adipose.emergency_reserve(10_000)
        entries = thalamus.read_by_source("adipose")
        assert any(e["type"] == "reserve_draw" for e in entries)

    def test_reserve_over_budget_rejected(self):
        adipose.set_daily_budget(1_000_000)
        adipose.set_spine_red(True)
        assert adipose.emergency_reserve(200_000) is False  # reserve is only 150k


class TestRebalance:
    def test_shifts_unused_crons_to_conversation(self):
        adipose.set_daily_budget(1_000_000)
        # Don't use any crons, then rebalance
        adipose.rebalance()
        report = adipose.get_budget_report()
        assert report["categories"]["conversation"]["budget"] > 600_000

    def test_rebalance_broadcasts(self):
        adipose.set_daily_budget(1_000_000)
        adipose.rebalance()
        entries = thalamus.read_by_source("adipose")
        assert any(e["type"] == "rebalance" for e in entries)


class TestBudgetWarnings:
    def test_cron_warning_at_90_percent(self):
        adipose.set_daily_budget(1_000_000)
        # Use 91% of cron budget (250k * 0.91 ≈ 227.5k)
        adipose.allocate("crons", 225_000)
        # Should still be under, allocate one more
        adipose.allocate("crons", 5_000)
        entries = thalamus.read_by_source("adipose")
        warnings = [e for e in entries if e["type"] == "budget_warning"]
        assert any(w["data"]["category"] == "crons" for w in warnings)

    def test_conversation_warning_at_80_percent(self):
        adipose.set_daily_budget(1_000_000)
        # Use >80% of conversation (600k * 0.81 = 486k)
        adipose.allocate("conversation", 490_000)
        entries = thalamus.read_by_source("adipose")
        warnings = [e for e in entries if e["type"] == "budget_warning"]
        assert any(w["data"]["category"] == "conversation" for w in warnings)


class TestBudgetReport:
    def test_report_structure(self):
        adipose.set_daily_budget(1_000_000)
        report = adipose.get_budget_report()
        assert "daily_budget" in report
        assert "categories" in report
        for cat in ["conversation", "crons", "reserve"]:
            assert cat in report["categories"]
            c = report["categories"][cat]
            assert "budget" in c
            assert "used" in c
            assert "remaining" in c
            assert "percent_used" in c
