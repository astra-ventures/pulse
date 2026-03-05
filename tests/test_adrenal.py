"""Tests for ADRENAL — Financial Nervous System."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pulse.src import adrenal


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    sf = tmp_path / "adrenal-state.json"
    # Point GOALS_FILE to a nonexistent path so tests don't read real goals
    dummy_goals = tmp_path / "goals.json"
    with patch.object(adrenal, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(adrenal, "_DEFAULT_STATE_FILE", sf), \
         patch.object(adrenal, "_GOALS_FILE", dummy_goals):
        yield tmp_path


class TestUpdateBalance:
    def test_update_monthly_revenue(self):
        state = adrenal.update_balance("monthly_revenue", 5000.0)
        assert state["monthly_revenue"] == 5000.0

    def test_update_polymarket(self):
        state = adrenal.update_balance("polymarket_balance", 250.0)
        assert state["polymarket_balance"] == 250.0

    def test_history_logged(self, tmp_path):
        adrenal.update_balance("monthly_revenue", 1000.0)
        sf = tmp_path / "adrenal-state.json"
        state = json.loads(sf.read_text())
        assert len(state["history"]) == 1
        assert state["history"][0]["field"] == "monthly_revenue"
        assert state["history"][0]["new"] == 1000.0

    def test_invalid_field_raises(self):
        with pytest.raises(ValueError, match="Unknown balance field"):
            adrenal.update_balance("invalid_field", 100.0)

    def test_history_capped_at_200(self):
        for i in range(205):
            adrenal.update_balance("trading_pnl_7d", float(i))
        sf = tmp_path / "adrenal-state.json" if False else None
        state = adrenal._load_state()
        assert len(state["history"]) <= 200


class TestGetFinancialPressure:
    def test_zero_revenue_max_pressure(self):
        # Default state has 0 revenue → pressure = 1.0
        pressure = adrenal.get_financial_pressure()
        assert pressure == 1.0

    def test_full_revenue_no_pressure(self):
        adrenal.update_balance("monthly_revenue", 20000.0)
        pressure = adrenal.get_financial_pressure()
        assert pressure == 0.0

    def test_half_revenue_half_pressure(self):
        adrenal.update_balance("monthly_revenue", 10000.0)
        pressure = adrenal.get_financial_pressure()
        assert abs(pressure - 0.5) < 0.01

    def test_over_target_no_pressure(self):
        adrenal.update_balance("monthly_revenue", 25000.0)
        pressure = adrenal.get_financial_pressure()
        assert pressure == 0.0

    def test_pressure_linear(self):
        adrenal.update_balance("monthly_revenue", 5000.0)
        p1 = adrenal.get_financial_pressure()
        adrenal.update_balance("monthly_revenue", 15000.0)
        p2 = adrenal.get_financial_pressure()
        assert p2 < p1


class TestGetStatus:
    def test_status_fields(self):
        status = adrenal.get_status()
        assert "monthly_revenue" in status
        assert "target_monthly" in status
        assert "financial_pressure" in status
        assert "revenue_gap" in status
        assert "polymarket_balance" in status

    def test_revenue_gap(self):
        adrenal.update_balance("monthly_revenue", 8000.0)
        status = adrenal.get_status()
        assert status["revenue_gap"] == pytest.approx(12000.0)

    def test_no_goals_file_ok(self):
        # Should not raise if goals.json absent
        status = adrenal.get_status()
        assert status["goal_001_notes"] == []


class TestEmitNeedSignals:
    def test_high_pressure_emits_signal(self):
        # Default state: 0 revenue → pressure 1.0 > 0.7
        mock_hypo = MagicMock()
        mock_endo = MagicMock()
        result = adrenal.emit_need_signals(hypothalamus_mod=mock_hypo, endocrine_mod=mock_endo)
        mock_hypo.record_need_signal.assert_called_with("generate_revenue", "treasury")
        assert "generate_revenue" in result["signals_emitted"]

    def test_critical_pressure_raises_cortisol(self):
        # pressure > 0.9 with 0 revenue
        mock_hypo = MagicMock()
        mock_endo = MagicMock()
        result = adrenal.emit_need_signals(hypothalamus_mod=mock_hypo, endocrine_mod=mock_endo)
        mock_endo.update_hormone.assert_called_with("cortisol", 0.15, "financial_pressure")

    def test_low_pressure_no_signals(self):
        adrenal.update_balance("monthly_revenue", 18000.0)
        mock_hypo = MagicMock()
        mock_endo = MagicMock()
        result = adrenal.emit_need_signals(hypothalamus_mod=mock_hypo, endocrine_mod=mock_endo)
        mock_hypo.record_need_signal.assert_not_called()
        assert result["signals_emitted"] == []

    def test_no_modules_ok(self):
        # Should not raise without modules
        result = adrenal.emit_need_signals()
        assert "pressure" in result

    def test_returns_pressure_score(self):
        result = adrenal.emit_need_signals()
        assert 0.0 <= result["pressure"] <= 1.0
