"""SPINE — System Health Monitor for Pulse.

Proprioception: knowing where your own body is in space.
Tracks token usage, context size, cron health, provider health.
Self-corrects by pausing non-essential work when degrading.
"""

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_HEALTH_FILE = _DEFAULT_STATE_DIR / "spine-health.json"

# Alert level ordering
LEVELS = ["green", "yellow", "orange", "red"]
LEVEL_ORDER = {l: i for i, l in enumerate(LEVELS)}

# Thresholds
TOKEN_YELLOW = 0.70
TOKEN_ORANGE = 0.85
TOKEN_RED = 0.95
CONTEXT_YELLOW = 0.80
CONTEXT_ORANGE = 0.90
CONTEXT_RED = 0.95
CRON_YELLOW = 0.20  # error rate
CRON_ORANGE = 0.35
CRON_RED = 0.50
LATENCY_ORANGE = 5000  # ms
LATENCY_RED = 10000

NON_ESSENTIAL_CRONS = ["weather_scan", "topic_monitor", "social_check"]
MAX_HISTORY = 24


def _ensure_dir():
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)


def _empty_state() -> dict:
    return {
        "last_check": 0,
        "status": "green",
        "metrics": {
            "token_usage_1h": 0,
            "token_usage_24h": 0,
            "context_pct": 0.0,
            "cron_success_rate_24h": 1.0,
            "provider_health": {},
        },
        "active_alerts": [],
        "paused_crons": [],
        "history": [],
    }


def _load() -> dict:
    if _DEFAULT_HEALTH_FILE.exists():
        try:
            return json.loads(_DEFAULT_HEALTH_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return _empty_state()


def _save(state: dict):
    _ensure_dir()
    _DEFAULT_HEALTH_FILE.write_text(json.dumps(state, indent=2))


def _max_level(*levels: str) -> str:
    """Return the most severe alert level."""
    max_idx = 0
    for l in levels:
        max_idx = max(max_idx, LEVEL_ORDER.get(l, 0))
    return LEVELS[max_idx]


def check_token_usage(current_in: int, current_out: int, budget_1h: int = 100000, budget_24h: int = 1000000) -> dict:
    """Track token burn rate, warn at thresholds."""
    state = _load()
    total = current_in + current_out
    state["metrics"]["token_usage_1h"] = total
    # Accumulate 24h (simplified: just track reported)
    state["metrics"]["token_usage_24h"] = state["metrics"].get("token_usage_24h", 0) + total

    pct = total / max(budget_1h, 1)
    level = "green"
    if pct > TOKEN_RED:
        level = "red"
    elif pct > TOKEN_ORANGE:
        level = "orange"
    elif pct > TOKEN_YELLOW:
        level = "yellow"

    alert = None
    if level != "green":
        alert = {"source": "token_usage", "level": level, "pct": round(pct, 3), "ts": int(time.time() * 1000)}
        _upsert_alert(state, alert)
    else:
        _remove_alert(state, "token_usage")

    _save(state)
    return {"level": level, "pct": round(pct, 3), "total": total}


def check_context_size(current_tokens: int, max_tokens: int) -> dict:
    """Monitor context fill percentage."""
    state = _load()
    pct = current_tokens / max(max_tokens, 1)
    state["metrics"]["context_pct"] = round(pct, 4)

    level = "green"
    if pct > CONTEXT_RED:
        level = "red"
    elif pct > CONTEXT_ORANGE:
        level = "orange"
    elif pct > CONTEXT_YELLOW:
        level = "yellow"

    if level != "green":
        alert = {"source": "context_size", "level": level, "pct": round(pct, 3), "ts": int(time.time() * 1000)}
        _upsert_alert(state, alert)
    else:
        _remove_alert(state, "context_size")

    _save(state)
    return {"level": level, "pct": round(pct, 4), "current": current_tokens, "max": max_tokens}


def check_cron_health(job_states: list) -> dict:
    """Track cron success/failure rates.
    
    job_states: list of {"name": str, "success": bool, ...}
    """
    state = _load()
    if not job_states:
        state["metrics"]["cron_success_rate_24h"] = 1.0
        _remove_alert(state, "cron_health")
        _save(state)
        return {"level": "green", "success_rate": 1.0, "total_jobs": 0}

    successes = sum(1 for j in job_states if j.get("success", True))
    total = len(job_states)
    error_rate = 1.0 - (successes / total)
    success_rate = successes / total
    state["metrics"]["cron_success_rate_24h"] = round(success_rate, 4)

    level = "green"
    if error_rate > CRON_RED:
        level = "red"
    elif error_rate > CRON_ORANGE:
        level = "orange"
    elif error_rate > CRON_YELLOW:
        level = "yellow"

    if level != "green":
        alert = {"source": "cron_health", "level": level, "error_rate": round(error_rate, 3), "ts": int(time.time() * 1000)}
        _upsert_alert(state, alert)
    else:
        _remove_alert(state, "cron_health")

    _save(state)
    return {"level": level, "success_rate": round(success_rate, 4), "error_rate": round(error_rate, 4), "total_jobs": total}


def check_provider_health(provider: str, latency_ms: int, success: bool) -> dict:
    """Track API provider responsiveness."""
    state = _load()
    providers = state["metrics"].setdefault("provider_health", {})
    p = providers.setdefault(provider, {"latency_avg_ms": 0, "success_rate": 1.0, "in_cooldown": False, "_samples": 0, "_latency_sum": 0, "_success_count": 0, "_total_count": 0})

    p["_samples"] = p.get("_samples", 0) + 1
    p["_latency_sum"] = p.get("_latency_sum", 0) + latency_ms
    p["_total_count"] = p.get("_total_count", 0) + 1
    if success:
        p["_success_count"] = p.get("_success_count", 0) + 1

    p["latency_avg_ms"] = round(p["_latency_sum"] / p["_samples"])
    p["success_rate"] = round(p["_success_count"] / p["_total_count"], 4) if p["_total_count"] else 1.0

    level = "green"
    if not success and p["success_rate"] < 0.5:
        level = "red"
        p["in_cooldown"] = True
    elif latency_ms > LATENCY_RED:
        level = "red"
        p["in_cooldown"] = True
    elif latency_ms > LATENCY_ORANGE or p["success_rate"] < 0.8:
        level = "orange"
    elif p["success_rate"] < 0.9:
        level = "yellow"

    if p["success_rate"] >= 0.9 and latency_ms < LATENCY_ORANGE:
        p["in_cooldown"] = False

    if level != "green":
        alert = {"source": f"provider:{provider}", "level": level, "latency_ms": latency_ms, "success_rate": p["success_rate"], "ts": int(time.time() * 1000)}
        _upsert_alert(state, alert)
    else:
        _remove_alert(state, f"provider:{provider}")

    _save(state)
    return {"level": level, "provider": provider, "latency_avg_ms": p["latency_avg_ms"], "success_rate": p["success_rate"], "in_cooldown": p["in_cooldown"]}


def record_metric(metric: str, value: float):
    """General-purpose metric recording."""
    state = _load()
    state["metrics"][metric] = value
    _save(state)


def get_alerts() -> list:
    """Returns list of active health alerts sorted by severity (most severe first)."""
    state = _load()
    alerts = state.get("active_alerts", [])
    return sorted(alerts, key=lambda a: -LEVEL_ORDER.get(a.get("level", "green"), 0))


def check_health() -> dict:
    """Returns full health report. Computes overall status, applies self-correction, broadcasts."""
    state = _load()
    now = int(time.time() * 1000)
    state["last_check"] = now

    # Determine overall status from worst alert
    alerts = state.get("active_alerts", [])
    if alerts:
        worst = max(LEVEL_ORDER.get(a.get("level", "green"), 0) for a in alerts)
        state["status"] = LEVELS[worst]
    else:
        state["status"] = "green"

    # Self-correction
    _apply_self_correction(state)

    # Append to history
    history_entry = {
        "ts": now,
        "status": state["status"],
        "alert_count": len(alerts),
    }
    state.setdefault("history", []).append(history_entry)
    state["history"] = state["history"][-MAX_HISTORY:]

    _save(state)

    # Broadcast
    thalamus.append({
        "source": "spine",
        "type": "health",
        "salience": 0.4 if state["status"] == "green" else 0.8,
        "data": {
            "status": state["status"],
            "alert_count": len(alerts),
            "paused_crons": state.get("paused_crons", []),
        },
    })

    return state


def _apply_self_correction(state: dict):
    """Apply self-correction based on alert level."""
    status = state["status"]

    if LEVEL_ORDER.get(status, 0) >= LEVEL_ORDER["orange"]:
        # Pause non-essential crons
        for cron in NON_ESSENTIAL_CRONS:
            if cron not in state.get("paused_crons", []):
                state.setdefault("paused_crons", []).append(cron)

    if LEVEL_ORDER.get(status, 0) >= LEVEL_ORDER["red"]:
        # At red: flag that all crons should pause (except spine)
        state["paused_crons"] = list(set(state.get("paused_crons", []) + ["ALL_EXCEPT_SPINE"]))

    if LEVEL_ORDER.get(status, 0) < LEVEL_ORDER["orange"]:
        # Clear paused crons when healthy
        state["paused_crons"] = []


def _upsert_alert(state: dict, alert: dict):
    """Add or update an alert by source."""
    alerts = state.setdefault("active_alerts", [])
    for i, a in enumerate(alerts):
        if a.get("source") == alert["source"]:
            alerts[i] = alert
            return
    alerts.append(alert)


def _remove_alert(state: dict, source: str):
    """Remove alert by source."""
    state["active_alerts"] = [a for a in state.get("active_alerts", []) if a.get("source") != source]
