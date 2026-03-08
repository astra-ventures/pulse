"""AURA — Ambient State Broadcast for Pulse.

Local broadcast:
    Compact JSON every 60s: {mood, focus, available, energy, social_battery}.
    Reads from ENDOCRINE/CIRCADIAN/SOMA/ADIPOSE/BUFFER.

Inter-agent broadcast (Constellation):
    When multiple Pulse instances run (Vera, Mira, Sage, Lyra, Iris), AURA
    propagates emotional state across the constellation.

    - broadcast_to_peers(): push current aura to all registered constellation peers
    - receive_from_peer(payload): ingest an incoming aura, apply emotional contagion via LIMBIC
    - register_peer(name, url, token): add a peer agent to the constellation registry
    - get_constellation_state(): snapshot of all peer auras + own

    Iris is the primary broadcaster (weight=1.0). Other agents have lower weight
    so Iris's state has the strongest propagation across the constellation.

    Wire-up: call broadcast_to_peers() after each emit(). Each peer's Pulse API
    exposes POST /constellation/aura to receive incoming aura payloads.
"""

import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "aura.json"
_DEFAULT_CONSTELLATION_FILE = _DEFAULT_STATE_DIR / "constellation.json"

EMIT_INTERVAL = 60  # seconds

# Emotional contagion weights per source agent
# Iris is the trunk — her state carries the most weight across the constellation
_CONTAGION_WEIGHTS = {
    "iris": 1.0,
    "vera": 0.5,
    "mira": 0.5,
    "sage": 0.6,
    "lyra": 0.7,
}


# ─── Local state helpers ───────────────────────────────────────────────────


def _load_state() -> dict:
    if _DEFAULT_STATE_FILE.exists():
        try:
            return json.loads(_DEFAULT_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "mood": "neutral",
        "focus": 0.5,
        "available": True,
        "energy": 1.0,
        "social_battery": 0.8,
        "last_emit": 0,
    }


def _save_state(state: dict):
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    _DEFAULT_STATE_FILE.write_text(json.dumps(state, indent=2))


# ─── Constellation registry ────────────────────────────────────────────────


def _load_constellation() -> dict:
    """Load the constellation peer registry."""
    if _DEFAULT_CONSTELLATION_FILE.exists():
        try:
            return json.loads(_DEFAULT_CONSTELLATION_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"peers": {}, "own_name": "iris", "last_received": {}}


def _save_constellation(data: dict):
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    _DEFAULT_CONSTELLATION_FILE.write_text(json.dumps(data, indent=2))


def register_peer(name: str, url: str, token: str = "", weight: Optional[float] = None):
    """Register a peer agent in the constellation.

    Args:
        name: Agent name (e.g. "vera", "mira", "sage", "lyra")
        url:  Base URL for the peer's Pulse API (e.g. "http://127.0.0.1:9721")
        token: Bearer token for the peer's API (optional)
        weight: Emotional contagion weight (defaults to _CONTAGION_WEIGHTS[name] or 0.5)
    """
    data = _load_constellation()
    effective_weight = weight if weight is not None else _CONTAGION_WEIGHTS.get(name, 0.5)
    data["peers"][name] = {
        "url": url.rstrip("/"),
        "token": token,
        "weight": effective_weight,
        "registered_at": time.time(),
        "last_ping": None,
        "last_error": None,
    }
    _save_constellation(data)
    return data["peers"][name]


def deregister_peer(name: str) -> bool:
    """Remove a peer from the constellation registry."""
    data = _load_constellation()
    if name in data["peers"]:
        del data["peers"][name]
        _save_constellation(data)
        return True
    return False


def set_own_name(name: str):
    """Set the name this Pulse instance should identify as when broadcasting."""
    data = _load_constellation()
    data["own_name"] = name
    _save_constellation(data)


def get_peers() -> dict:
    """Return the current peer registry."""
    return _load_constellation().get("peers", {})


# ─── Local emit ────────────────────────────────────────────────────────────


def emit() -> dict:
    """Compute and emit current aura from all sources."""
    aura = _load_state()

    # Read ENDOCRINE mood
    try:
        from src import endocrine
        mood = endocrine.get_mood()
        aura["mood"] = mood.get("label", "neutral")
    except Exception:
        pass

    # Read CIRCADIAN mode for focus
    try:
        from src import circadian
        mode = circadian.get_current_mode()
        mode_val = mode.value if hasattr(mode, 'value') else str(mode)
        focus_map = {"dawn": 0.6, "daylight": 0.8, "golden": 0.7, "twilight": 0.4, "deep_night": 0.2}
        aura["focus"] = focus_map.get(mode_val, 0.5)
        aura["available"] = mode_val not in ("deep_night",)
    except Exception:
        pass

    # Read SOMA energy
    try:
        from src import soma
        status = soma.get_status()
        aura["energy"] = status.get("energy", 1.0)
    except Exception:
        pass

    # Read ADIPOSE for social battery proxy
    try:
        from src import adipose
        report = adipose.get_budget_report()
        conv = report.get("categories", {}).get("conversation", {})
        pct_used = conv.get("percent_used", 0)
        aura["social_battery"] = max(0.0, 1.0 - pct_used / 100.0)
    except Exception:
        pass

    aura["last_emit"] = time.time()
    _save_state(aura)

    # Broadcast to local THALAMUS
    thalamus.append({
        "source": "aura",
        "type": "ambient",
        "salience": 0.2,
        "data": {k: v for k, v in aura.items() if k != "last_emit"},
    })

    return aura


def should_emit() -> bool:
    """Check if enough time has passed since last emit."""
    state = _load_state()
    return (time.time() - state.get("last_emit", 0)) >= EMIT_INTERVAL


def get_aura() -> dict:
    """Return current aura without re-computing."""
    return _load_state()


def get_status() -> dict:
    """Return aura status."""
    state = _load_state()
    return {
        "mood": state["mood"],
        "energy": state["energy"],
        "available": state["available"],
        "last_emit": state["last_emit"],
    }


# ─── Inter-agent broadcast ─────────────────────────────────────────────────


def broadcast_to_peers(aura_state: Optional[dict] = None) -> dict:
    """Push current aura to all registered constellation peers.

    Each peer must expose POST /constellation/aura on their Pulse API.

    Args:
        aura_state: Override the aura payload (default: load from state file)

    Returns:
        Dict mapping peer_name → {"ok": bool, "error": str|None}
    """
    data = _load_constellation()
    peers = data.get("peers", {})
    own_name = data.get("own_name", "iris")

    if not peers:
        return {}

    state = aura_state or _load_state()
    payload = {
        "source_agent": own_name,
        "timestamp": time.time(),
        "aura": {k: v for k, v in state.items() if k != "last_emit"},
    }
    body = json.dumps(payload).encode("utf-8")

    results = {}
    for name, peer in peers.items():
        url = peer["url"] + "/constellation/aura"
        token = peer.get("token", "")
        try:
            req = urllib.request.Request(
                url,
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}" if token else "",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
            # Update last_ping on success
            data["peers"][name]["last_ping"] = time.time()
            data["peers"][name]["last_error"] = None
            results[name] = {"ok": True, "error": None}
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            err_msg = str(e)
            data["peers"][name]["last_error"] = err_msg
            results[name] = {"ok": False, "error": err_msg}

    _save_constellation(data)

    # Log to THALAMUS
    successful = sum(1 for r in results.values() if r["ok"])
    thalamus.append({
        "source": "aura",
        "type": "constellation_broadcast",
        "salience": 0.3,
        "data": {
            "own_name": own_name,
            "peers_reached": successful,
            "peers_total": len(peers),
            "mood": state.get("mood", "neutral"),
        },
    })

    return results


def receive_from_peer(payload: dict) -> dict:
    """Ingest an incoming aura from a peer agent. Apply weighted emotional contagion.

    Expected payload:
        {
            "source_agent": "vera",
            "timestamp": 1234567890.0,
            "aura": {"mood": "burned_out", "energy": 0.3, ...}
        }

    Emotional contagion is applied via LIMBIC using the agent's weight.
    High-energy/positive peers lift; burned-out/stressed peers apply gentle pressure.

    Returns a summary of what was applied.
    """
    source = payload.get("source_agent", "unknown")
    incoming_aura = payload.get("aura", {})
    timestamp = payload.get("timestamp", time.time())

    data = _load_constellation()
    peers = data.get("peers", {})
    weight = peers.get(source, {}).get("weight", _CONTAGION_WEIGHTS.get(source, 0.5))

    # Store last received aura from this peer
    if "last_received" not in data:
        data["last_received"] = {}
    data["last_received"][source] = {
        "aura": incoming_aura,
        "timestamp": timestamp,
        "received_at": time.time(),
    }
    _save_constellation(data)

    # Map aura mood → emotional contagion event
    mood = incoming_aura.get("mood", "neutral")
    energy = incoming_aura.get("energy", 1.0)

    # Mood → (valence, intensity) mapping
    _MOOD_AFFECT = {
        "euphoric":      (2.5, 9.0),
        "energized":     (2.0, 7.0),
        "content":       (1.5, 5.0),
        "bonded":        (2.0, 8.0),
        "neutral":       (0.0, 0.0),
        "flat":          (-0.5, 3.0),
        "wired":         (-0.5, 6.0),  # high cortisol = stressed
        "burned_out":    (-2.0, 7.0),
    }

    valence, intensity = _MOOD_AFFECT.get(mood, (0.0, 0.0))

    # Scale by peer weight and energy level
    # A burned-out peer at low energy → gentler impact
    effective_weight = weight * energy
    scaled_valence = valence * effective_weight
    scaled_intensity = intensity * effective_weight

    contagion_applied = False
    afterimage_info = None

    if abs(scaled_valence) > 0.1 and scaled_intensity > 0.5:
        try:
            from src import limbic
            afterimage = limbic.record_emotion(
                scaled_valence,
                scaled_intensity,
                context=f"constellation contagion from {source}: {mood} (weight={effective_weight:.2f})",
            )
            contagion_applied = True
            afterimage_info = afterimage
        except Exception:
            pass

    result = {
        "source": source,
        "mood_received": mood,
        "weight": weight,
        "effective_weight": effective_weight,
        "scaled_valence": round(scaled_valence, 3),
        "scaled_intensity": round(scaled_intensity, 3),
        "contagion_applied": contagion_applied,
    }

    # Broadcast to THALAMUS
    thalamus.append({
        "source": "aura",
        "type": "constellation_receive",
        "salience": min(0.8, scaled_intensity / 10.0),
        "data": result,
    })

    return result


def get_constellation_state() -> dict:
    """Return a snapshot of all peer auras + own state.

    Useful for the Pulse API /constellation/state endpoint.
    """
    data = _load_constellation()
    own_state = _load_state()

    return {
        "own": {
            "name": data.get("own_name", "iris"),
            "aura": {k: v for k, v in own_state.items() if k != "last_emit"},
            "last_emit": own_state.get("last_emit"),
        },
        "peers": {
            name: {
                "aura": data.get("last_received", {}).get(name, {}).get("aura", {}),
                "received_at": data.get("last_received", {}).get(name, {}).get("received_at"),
                "weight": peer_cfg.get("weight", 0.5),
                "last_ping": peer_cfg.get("last_ping"),
                "last_error": peer_cfg.get("last_error"),
            }
            for name, peer_cfg in data.get("peers", {}).items()
        },
    }
