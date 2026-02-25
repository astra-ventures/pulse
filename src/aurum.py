"""AURUM — Financial Nervous System for Pulse.

Pulse has drive pressure based on financial state, not just token budgets.
Financial pressure is a real physiological signal: low revenue = high cortisol.

Target: $20k/month. Progress toward that target shapes baseline drive pressure.
"""

import json
import time
from pathlib import Path
from typing import Optional

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "aurum-state.json"

_GOALS_FILE = Path.home() / ".openclaw" / "workspace" / "memory" / "self" / "goals.json"

# Valid balance source fields
_BALANCE_FIELDS = {
    "polymarket_balance",
    "trading_pnl_7d",
    "monthly_revenue",
    "target_monthly",
    "runway_days",
}


def _default_state() -> dict:
    return {
        "polymarket_balance": 0.0,
        "trading_pnl_7d": 0.0,
        "monthly_revenue": 0.0,
        "target_monthly": 20000.0,
        "runway_days": 0,
        "last_update": 0,
        "history": [],
    }


def _load_state() -> dict:
    if _DEFAULT_STATE_FILE.exists():
        try:
            return json.loads(_DEFAULT_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return _default_state()


def _save_state(state: dict):
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    _DEFAULT_STATE_FILE.write_text(json.dumps(state, indent=2))


def update_balance(source: str, amount: float) -> dict:
    """Update a balance field and log to history.

    Args:
        source: one of the balance field names (e.g. "monthly_revenue")
        amount: new value (absolute, not delta)

    Returns:
        Updated state dict.
    """
    state = _load_state()
    now = time.time()

    if source not in _BALANCE_FIELDS:
        raise ValueError(f"Unknown balance field: {source}. Valid: {sorted(_BALANCE_FIELDS)}")

    old = state.get(source, 0.0)
    state[source] = float(amount)
    state["last_update"] = now

    state["history"].append({
        "ts": now,
        "field": source,
        "old": old,
        "new": amount,
        "delta": amount - old,
    })
    # Keep last 200 history entries
    state["history"] = state["history"][-200:]

    _save_state(state)
    return state.copy()


def get_financial_pressure() -> float:
    """Return 0.0–1.0 financial pressure score.

    0.0 = fully funded (no pressure)
    1.0 = zero revenue (maximum pressure)
    Linear between: 1.0 - (monthly_revenue / target_monthly)
    """
    state = _load_state()
    monthly = state.get("monthly_revenue", 0.0)
    target = state.get("target_monthly", 20000.0)

    if target <= 0:
        return 0.0
    if monthly <= 0:
        return 1.0
    if monthly >= target:
        return 0.0

    return round(1.0 - (monthly / target), 3)


def get_status() -> dict:
    """Return current balances + pressure score + days to target at current rate."""
    state = _load_state()
    pressure = get_financial_pressure()

    monthly = state.get("monthly_revenue", 0.0)
    target = state.get("target_monthly", 20000.0)
    gap = max(0.0, target - monthly)

    # Simple goal_001 progress notes from goals.json
    goal_notes = []
    try:
        if _GOALS_FILE.exists():
            goals_data = json.loads(_GOALS_FILE.read_text())
            for goal in goals_data.get("goals", []):
                if goal.get("id") == "goal_001":
                    progress = goal.get("progress", [])
                    if progress:
                        # Get last 2 progress notes
                        last_notes = progress[-2:]
                        for note in last_notes:
                            if isinstance(note, str):
                                goal_notes.append(note)
                            elif isinstance(note, dict):
                                goal_notes.append(note.get("note", ""))
    except Exception:
        pass

    return {
        "polymarket_balance": state.get("polymarket_balance", 0.0),
        "trading_pnl_7d": state.get("trading_pnl_7d", 0.0),
        "monthly_revenue": monthly,
        "target_monthly": target,
        "revenue_gap": gap,
        "runway_days": state.get("runway_days", 0),
        "financial_pressure": pressure,
        "last_update": state.get("last_update", 0),
        "goal_001_notes": goal_notes,
    }


def emit_need_signals(hypothalamus_mod=None, endocrine_mod=None) -> dict:
    """Emit need signals to HYPOTHALAMUS based on financial pressure.

    - pressure > 0.7: emit "generate_revenue" need
    - pressure > 0.9: also raise cortisol

    Returns:
        {"pressure": float, "signals_emitted": list}
    """
    pressure = get_financial_pressure()
    signals = []

    if pressure > 0.7 and hypothalamus_mod is not None:
        try:
            hypothalamus_mod.record_need_signal("generate_revenue", "treasury")
            signals.append("generate_revenue")
        except Exception:
            pass

    if pressure > 0.9 and endocrine_mod is not None:
        try:
            endocrine_mod.update_hormone("cortisol", 0.15, "financial_pressure")
            signals.append("cortisol_bump")
        except Exception:
            pass

    return {"pressure": pressure, "signals_emitted": signals}
