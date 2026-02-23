"""PROPRIOCEPTION — Self-Model / Capability Awareness for Pulse.

Knowing what I am, what I can do, and what my limits are — right now.
"""

import json
import time
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "proprioception-state.json"

# ── Default capability registry ─────────────────────────────────────────

_capabilities: dict = {
    "model": "unknown",
    "context_window": 200000,
    "context_used": 0,
    "tools_available": [],
    "skills_available": [],
    "channels_active": [],
    "limitations": [],
    "session_type": "unknown",
    "uptime_start": None,
    "failed_attempts": [],  # log of things we tried but couldn't do
}


def _load_state() -> dict:
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    if _DEFAULT_STATE_FILE.exists():
        try:
            return json.loads(_DEFAULT_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return dict(_capabilities)


def _save_state(state: dict):
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    _DEFAULT_STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Core functions ──────────────────────────────────────────────────────

def get_self_model() -> dict:
    """Full current capability snapshot."""
    state = _load_state()
    state["context_remaining"] = state.get("context_window", 200000) - state.get("context_used", 0)
    if state.get("uptime_start"):
        state["uptime_hours"] = round((time.time() - state["uptime_start"]) / 3600, 2)
    return state


def can_i(action: str) -> tuple[bool, str]:
    """Check if a specific action is possible right now."""
    state = _load_state()
    tools = state.get("tools_available", [])
    
    # Map common actions to required tools
    action_tool_map = {
        "send a message": "message",
        "send message": "message",
        "message": "message",
        "search the web": "web_search",
        "web search": "web_search",
        "search": "web_search",
        "browse": "browser",
        "read files": "read",
        "read": "read",
        "write files": "write",
        "write": "write",
        "edit files": "edit",
        "edit": "edit",
        "run commands": "exec",
        "exec": "exec",
        "execute": "exec",
        "see images": "image",
        "image": "image",
        "speak": "tts",
        "tts": "tts",
        "text to speech": "tts",
    }

    action_lower = action.lower().strip()
    
    # Direct tool name check
    if action_lower in tools:
        return (True, f"{action_lower} tool available")

    # Action description check
    required_tool = action_tool_map.get(action_lower)
    if required_tool:
        if required_tool in tools:
            return (True, f"{required_tool} tool available")
        else:
            _log_failed_attempt(action_lower, f"{required_tool} tool not in current session")
            return (False, f"{required_tool} tool not in current session")

    # Check limitations
    for lim in state.get("limitations", []):
        if action_lower in lim.lower():
            return (False, lim)

    # Unknown action — can't confirm
    return (False, f"Unknown action '{action}' — cannot confirm capability")


def get_limits() -> dict:
    """Current resource limits."""
    state = _load_state()
    ctx_max = state.get("context_window", 200000)
    ctx_used = state.get("context_used", 0)
    return {
        "context_window": ctx_max,
        "context_used": ctx_used,
        "context_remaining": ctx_max - ctx_used,
        "context_percent_used": round(ctx_used / max(ctx_max, 1) * 100, 1),
        "tools_available": state.get("tools_available", []),
        "model": state.get("model", "unknown"),
    }


def estimate_cost(task_description: str) -> dict:
    """Rough estimate of tokens/time for a task."""
    words = len(task_description.split())
    # Heuristic: simple tasks ~500 tokens, complex ~5000+
    complexity = min(1.0, words / 50)  # longer descriptions = more complex
    estimated_tokens = int(500 + complexity * 4500)
    estimated_seconds = int(5 + complexity * 55)
    return {
        "estimated_tokens": estimated_tokens,
        "estimated_seconds": estimated_seconds,
        "complexity": round(complexity, 2),
        "description": task_description[:200],
    }


def would_exceed(task_description: str) -> bool:
    """Would this task exceed current available resources?"""
    state = _load_state()
    remaining = state.get("context_window", 200000) - state.get("context_used", 0)
    cost = estimate_cost(task_description)
    return cost["estimated_tokens"] > remaining


def update_capabilities(model: str, tools: list, context_max: int,
                        context_used: int = 0,
                        skills: Optional[list] = None,
                        channels: Optional[list] = None,
                        limitations: Optional[list] = None,
                        session_type: str = "main"):
    """Called on session start or model switch."""
    state = _load_state()
    old_model = state.get("model")
    state.update({
        "model": model,
        "tools_available": tools,
        "context_window": context_max,
        "context_used": context_used,
        "skills_available": skills or [],
        "channels_active": channels or [],
        "limitations": limitations or [],
        "session_type": session_type,
        "uptime_start": state.get("uptime_start") or time.time(),
    })
    _save_state(state)

    # Broadcast if model changed
    if old_model and old_model != model:
        thalamus.append({
            "source": "proprioception",
            "type": "capability_change",
            "salience": 0.6,
            "data": {"event": "model_switch", "from": old_model, "to": model},
        })


def get_identity_snapshot() -> dict:
    """Who am I right now?"""
    state = _load_state()
    return {
        "model": state.get("model", "unknown"),
        "session_type": state.get("session_type", "unknown"),
        "channels_active": state.get("channels_active", []),
        "tools_count": len(state.get("tools_available", [])),
        "skills_count": len(state.get("skills_available", [])),
        "limitations_count": len(state.get("limitations", [])),
    }


def _log_failed_attempt(action: str, reason: str):
    """Log when we attempt something we can't do — feeds to IMMUNE."""
    state = _load_state()
    attempts = state.get("failed_attempts", [])
    attempts.append({
        "action": action,
        "reason": reason,
        "ts": int(time.time() * 1000),
    })
    # Keep last 50
    state["failed_attempts"] = attempts[-50:]
    _save_state(state)
