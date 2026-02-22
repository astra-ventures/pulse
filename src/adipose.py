"""ADIPOSE — Token/Energy Budgeting.

Proactive resource budgeting. Fat reserves for lean times.
"""

import json
import time
from pathlib import Path

from pulse.src import thalamus

STATE_DIR = Path.home() / ".pulse" / "state"
STATE_FILE = STATE_DIR / "adipose-state.json"

# Default allocation percentages
DEFAULT_ALLOCATIONS = {
    "conversation": 0.60,
    "crons": 0.25,
    "reserve": 0.15,
}

# Conversation never below 50%
MIN_CONVERSATION_RATIO = 0.50


def _default_state() -> dict:
    return {
        "daily_budget": 1_000_000,  # default 1M tokens
        "category_budgets": {},
        "usage_today": {"conversation": 0, "crons": 0, "reserve": 0},
        "burn_rates": {},  # tokens per hour, computed
        "usage_log": [],  # timestamped allocations for burn rate calc
        "reserve_draws": [],
        "budget_set_time": time.time(),
        "spine_red": False,
    }


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, KeyError):
            pass
    state = _default_state()
    _recalc_budgets(state)
    return state


def _save_state(state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _recalc_budgets(state: dict):
    """Recalculate category budgets from daily budget."""
    total = state["daily_budget"]
    state["category_budgets"] = {
        cat: int(total * ratio) for cat, ratio in DEFAULT_ALLOCATIONS.items()
    }


def set_daily_budget(total_tokens: int):
    """Set total daily token budget."""
    state = _load_state()
    state["daily_budget"] = total_tokens
    _recalc_budgets(state)
    state["budget_set_time"] = time.time()
    _save_state(state)


def allocate(category: str, tokens: int) -> bool:
    """Request token allocation. Returns False if would exceed budget."""
    state = _load_state()
    if category not in state["category_budgets"]:
        raise ValueError(f"Unknown category: {category}")
    
    budget = state["category_budgets"].get(category, 0)
    used = state["usage_today"].get(category, 0)
    
    if used + tokens > budget:
        return False
    
    state["usage_today"][category] = used + tokens
    state["usage_log"].append({
        "ts": time.time(),
        "category": category,
        "tokens": tokens,
    })
    # Keep last 500 log entries
    state["usage_log"] = state["usage_log"][-500:]
    
    _save_state(state)
    _check_warnings(state)
    return True


def get_remaining(category: str) -> int:
    """Tokens remaining in category."""
    state = _load_state()
    budget = state["category_budgets"].get(category, 0)
    used = state["usage_today"].get(category, 0)
    return max(0, budget - used)


def get_burn_rate(category: str) -> float:
    """Tokens per hour in category (based on recent usage)."""
    state = _load_state()
    now = time.time()
    # Look at last 3 hours of usage
    window = 3 * 3600
    recent = [e for e in state["usage_log"]
              if e["category"] == category and now - e["ts"] < window]
    
    if not recent:
        return 0.0
    
    total_tokens = sum(e["tokens"] for e in recent)
    elapsed_hours = (now - recent[0]["ts"]) / 3600 if len(recent) > 1 else 1.0
    return total_tokens / max(elapsed_hours, 0.01)


def forecast_depletion(category: str) -> float:
    """Hours until category runs out at current burn rate."""
    rate = get_burn_rate(category)
    if rate <= 0:
        return float("inf")
    remaining = get_remaining(category)
    return remaining / rate


def emergency_reserve(tokens: int) -> bool:
    """Draw from reserve. Only allowed if SPINE is red."""
    state = _load_state()
    if not state.get("spine_red", False):
        return False
    
    reserve_budget = state["category_budgets"].get("reserve", 0)
    reserve_used = state["usage_today"].get("reserve", 0)
    
    if reserve_used + tokens > reserve_budget:
        return False
    
    state["usage_today"]["reserve"] = reserve_used + tokens
    state["reserve_draws"].append({
        "ts": time.time(),
        "tokens": tokens,
    })
    _save_state(state)
    
    # Alert SPINE via thalamus
    thalamus.append({
        "source": "adipose",
        "type": "reserve_draw",
        "salience": 0.9,
        "data": {"tokens": tokens, "remaining": reserve_budget - reserve_used - tokens},
    })
    return True


def set_spine_red(is_red: bool):
    """Set whether SPINE is in red state (enables emergency reserve)."""
    state = _load_state()
    state["spine_red"] = is_red
    _save_state(state)


def rebalance():
    """Shift unused cron budget to conversation if crons are under-spending."""
    state = _load_state()
    
    cron_budget = state["category_budgets"].get("crons", 0)
    cron_used = state["usage_today"].get("crons", 0)
    cron_remaining = cron_budget - cron_used
    
    # If crons used less than 50% of their budget, shift surplus to conversation
    if cron_used < cron_budget * 0.5 and cron_remaining > 0:
        shift = int(cron_remaining * 0.5)  # shift half of unused
        state["category_budgets"]["crons"] -= shift
        state["category_budgets"]["conversation"] += shift
        
        # Ensure conversation never below minimum
        total = state["daily_budget"]
        min_conv = int(total * MIN_CONVERSATION_RATIO)
        state["category_budgets"]["conversation"] = max(
            state["category_budgets"]["conversation"], min_conv
        )
        
        _save_state(state)
        
        thalamus.append({
            "source": "adipose",
            "type": "rebalance",
            "salience": 0.3,
            "data": {
                "shifted": shift,
                "from": "crons",
                "to": "conversation",
                "new_budgets": state["category_budgets"],
            },
        })


def get_budget_report() -> dict:
    """Full budget status."""
    state = _load_state()
    report = {
        "daily_budget": state["daily_budget"],
        "categories": {},
        "spine_red": state.get("spine_red", False),
        "reserve_draws": len(state.get("reserve_draws", [])),
    }
    
    for cat in ["conversation", "crons", "reserve"]:
        budget = state["category_budgets"].get(cat, 0)
        used = state["usage_today"].get(cat, 0)
        report["categories"][cat] = {
            "budget": budget,
            "used": used,
            "remaining": max(0, budget - used),
            "percent_used": round(used / budget * 100, 1) if budget > 0 else 0,
            "burn_rate": round(get_burn_rate(cat), 1),
        }
    
    return report


def emit_need_signals() -> dict:
    """Check budget state and emit HYPOTHALAMUS need signals."""
    try:
        state = _load_state()
    except Exception:
        return {}

    signals = {}

    # Check days_at_zero if tracked
    days_at_zero = state.get("days_at_zero", 0)
    if days_at_zero > 7:
        from pulse.src import hypothalamus
        hypothalamus.record_need_signal("generate_revenue", "adipose")
        signals["generate_revenue"] = days_at_zero
        return signals

    # Check if total budget is critically low (all categories near-depleted)
    budgets = state.get("category_budgets", {})
    usage = state.get("usage_today", {})
    if budgets:
        total_budget = sum(budgets.values())
        total_used = sum(usage.get(cat, 0) for cat in budgets)
        if total_budget > 0 and total_used / total_budget > 0.95:
            from pulse.src import hypothalamus
            hypothalamus.record_need_signal("generate_revenue", "adipose")
            signals["generate_revenue"] = total_used / total_budget

    return signals


def _check_warnings(state: dict):
    """Check budget thresholds and broadcast warnings."""
    for cat in ["conversation", "crons"]:
        budget = state["category_budgets"].get(cat, 0)
        used = state["usage_today"].get(cat, 0)
        if budget <= 0:
            continue
        pct = used / budget
        
        if cat == "crons" and pct > 0.9:
            thalamus.append({
                "source": "adipose",
                "type": "budget_warning",
                "salience": 0.7,
                "data": {"category": "crons", "percent_used": round(pct * 100, 1),
                         "action": "pause_low_priority_crons"},
            })
        elif cat == "conversation" and pct > 0.8:
            thalamus.append({
                "source": "adipose",
                "type": "budget_warning",
                "salience": 0.6,
                "data": {"category": "conversation", "percent_used": round(pct * 100, 1),
                         "action": "warn_buffer_capture_state"},
            })
