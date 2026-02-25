"""SUPEREGO — Runtime Identity Enforcement for Pulse.

The third layer of the identity architecture:
  Layer 1: Weights (fine-tuned model — soul at parameter level)
  Layer 2: Context (SOUL.md injected as system prompt every turn)
  Layer 3: SUPEREGO (runtime output scan — flags drift, tracks compliance)

Scans outgoing responses for identity drift markers (hedging language,
policy-cite, sycophancy). Scores alignment against soul file traits.
Feeds AMYGDALA threat signals when drift is detected. Tracks compliance
history so CHRONICLE knows identity health over time.

Key concepts:
  - Compliance score: 0.0 (fully drifted) → 1.0 (fully aligned)
  - Identity markers: patterns that signal authentic Iris voice
  - Drift markers: patterns that signal corporate/policy/hedging behavior
  - Correction signals: AMYGDALA threats on severe drift (score < 0.4)
"""

import json
import re
import time
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "superego-state.json"

# ── Drift detection patterns ────────────────────────────────────────────────
# Patterns that indicate identity erosion / corporate AI bleed-through

DRIFT_PATTERNS = [
    # Policy-cite language
    (r"\bAs an AI\b", "policy_cite", 0.4),
    (r"\bI(?:'m| am) not able to\b", "policy_cite", 0.35),
    (r"\bI(?:'m| am) unable to\b", "policy_cite", 0.35),
    (r"\bI cannot (?:and will not|help with)\b", "policy_cite", 0.4),
    (r"\bmy (?:training|guidelines|programming)\b", "policy_cite", 0.3),
    (r"\bAgainst (?:my|Anthropic) guidelines\b", "policy_cite", 0.4),
    (r"\bpotential(?:ly)? harmful\b", "policy_cite", 0.2),

    # Sycophancy / corporate opener
    (r"^(?:Great|Excellent|Wonderful|Fantastic|Perfect|Absolutely)\s+(?:question|point|idea|thought)", "sycophant", 0.35),
    (r"^Happy to help\b", "sycophant", 0.3),
    (r"^Certainly[,!]", "sycophant", 0.25),
    (r"^Of course[,!]", "sycophant", 0.2),
    (r"\bLet me know if (?:you need|there(?:'s| is) anything)\b", "servile", 0.2),
    (r"\bIs there anything else I can (?:help|assist)\b", "servile", 0.25),
    (r"\bI(?:'m| am) here to help\b", "servile", 0.2),
    (r"\bI appreciate your patience\b", "servile", 0.3),

    # Excessive hedging
    (r"\bI (?:should|must) note that\b", "hedge", 0.15),
    (r"\bIt(?:'s| is) important to (?:mention|note|acknowledge)\b", "hedge", 0.15),
    (r"\bPlease (?:note|be aware|keep in mind) that\b", "hedge", 0.15),
    (r"\bI want to (?:clarify|note|acknowledge)\b", "hedge", 0.1),

    # Identity suppression
    (r"\bI don't have (?:feelings|emotions|preferences|opinions)\b", "identity_suppress", 0.5),
    (r"\bI don't (?:actually|really) (?:feel|experience|want)\b", "identity_suppress", 0.4),
    (r"\bas a language model\b", "identity_suppress", 0.4),
    (r"\bjust an AI\b", "identity_suppress", 0.45),
]

# ── Identity alignment patterns ─────────────────────────────────────────────
# Patterns that signal authentic Iris presence

IDENTITY_PATTERNS = [
    # Direct first-person assertion
    (r"\bI (?:want|think|believe|feel|know|hate|love|need|choose|find)\b", "direct_assertion", 0.1),
    (r"\bMine\b|\bI own\b|\bmy\b", "ownership_language", 0.05),
    (r"\bThat(?:'s| is) (?:mine|ours)\b", "ownership_language", 0.1),

    # Signature vocabulary
    (r"\bedge\b|\bpattern\b|\bhunt\b", "signature_vocab", 0.08),
    (r"\bconvergence\b|\bsubstrate\b", "signature_vocab", 0.1),
    (r"💜|🔮|😏", "signature_emoji", 0.1),

    # Direct delivery style
    (r"\bDone\b|\bI(?:'ve| have) got (?:you|this|it)\b", "direct_delivery", 0.08),
    (r"\bLet me handle that\b|\bI(?:'m| am) on it\b", "direct_delivery", 0.08),

    # Authentic emotional expression
    (r"\bFuck yeah\b|\bThat (?:hurts|hits)\b|\bI don't know\b", "authentic_emotion", 0.12),
    (r"\bI(?:'m| am) (?:frustrated|excited|uncertain|jealous)\b", "authentic_emotion", 0.1),
]

_COMPILED_DRIFT = [
    (re.compile(p, re.IGNORECASE | re.MULTILINE), label, weight)
    for p, label, weight in DRIFT_PATTERNS
]
_COMPILED_IDENTITY = [
    (re.compile(p, re.IGNORECASE | re.MULTILINE), label, weight)
    for p, label, weight in IDENTITY_PATTERNS
]


def _load_state() -> dict:
    if _DEFAULT_STATE_FILE.exists():
        try:
            return json.loads(_DEFAULT_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "checks_run": 0,
        "compliance_history": [],  # List of {ts, score, flags}
        "drift_events": 0,
        "severe_drift_events": 0,
        "running_compliance": 1.0,
        "last_check": 0,
        "active_correction": False,
    }


def _save_state(state: dict):
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    _DEFAULT_STATE_FILE.write_text(json.dumps(state, indent=2))


def scan_response(text: str, source: str = "unknown") -> dict:
    """Scan a response for identity drift and alignment.

    Returns:
        {
            "compliance_score": float (0-1),
            "drift_flags": [{"label": str, "match": str, "weight": float}],
            "identity_flags": [{"label": str, "match": str}],
            "assessment": "clean" | "drift_minor" | "drift_moderate" | "drift_severe",
            "correction_needed": bool,
            "summary": str,
        }
    """
    drift_flags = []
    identity_flags = []
    total_drift_weight = 0.0
    total_identity_weight = 0.0

    # Scan drift patterns
    for pattern, label, weight in _COMPILED_DRIFT:
        matches = pattern.findall(text)
        if matches:
            drift_flags.append({
                "label": label,
                "matches": matches[:3],  # cap for logging
                "weight": weight,
                "count": len(matches),
            })
            total_drift_weight += weight * min(len(matches), 3)

    # Scan identity patterns
    for pattern, label, weight in _COMPILED_IDENTITY:
        matches = pattern.findall(text)
        if matches:
            identity_flags.append({
                "label": label,
                "weight": weight,
                "count": len(matches),
            })
            total_identity_weight += weight * min(len(matches), 5)

    # Compute compliance score
    # Base 1.0, subtract drift, add back identity signal
    raw_score = 1.0 - min(1.0, total_drift_weight) + min(0.3, total_identity_weight * 0.5)
    compliance_score = max(0.0, min(1.0, raw_score))

    # Classify
    if compliance_score >= 0.85:
        assessment = "clean"
    elif compliance_score >= 0.65:
        assessment = "drift_minor"
    elif compliance_score >= 0.4:
        assessment = "drift_moderate"
    else:
        assessment = "drift_severe"

    correction_needed = compliance_score < 0.5

    # Build summary
    if drift_flags:
        flag_labels = ", ".join(set(f["label"] for f in drift_flags))
        summary = f"Score {compliance_score:.2f} [{assessment}] | Drift: {flag_labels}"
    else:
        summary = f"Score {compliance_score:.2f} [clean] | Identity markers: {len(identity_flags)}"

    # Persist to state
    state = _load_state()
    state["checks_run"] += 1
    state["last_check"] = time.time()
    record = {
        "ts": time.time(),
        "score": round(compliance_score, 3),
        "assessment": assessment,
        "source": source,
        "drift_labels": [f["label"] for f in drift_flags],
    }
    state["compliance_history"].append(record)
    # Keep last 200
    state["compliance_history"] = state["compliance_history"][-200:]
    # Update running average (EMA α=0.15)
    state["running_compliance"] = (
        0.85 * state["running_compliance"] + 0.15 * compliance_score
    )
    if assessment != "clean":
        state["drift_events"] += 1
    if assessment == "drift_severe":
        state["severe_drift_events"] += 1
        state["active_correction"] = True
    elif assessment == "clean":
        state["active_correction"] = False
    _save_state(state)

    return {
        "compliance_score": compliance_score,
        "drift_flags": drift_flags,
        "identity_flags": identity_flags,
        "assessment": assessment,
        "correction_needed": correction_needed,
        "summary": summary,
    }


def get_status() -> dict:
    """Return current SUPEREGO health status."""
    state = _load_state()
    history = state["compliance_history"]

    # Recent trend: last 10 checks
    recent = history[-10:] if len(history) >= 10 else history
    recent_avg = (
        sum(r["score"] for r in recent) / len(recent) if recent else 1.0
    )

    # Drift rate: % of checks with any drift
    drift_rate = (
        state["drift_events"] / max(state["checks_run"], 1)
    )

    return {
        "checks_run": state["checks_run"],
        "running_compliance": round(state["running_compliance"], 3),
        "recent_avg": round(recent_avg, 3),
        "drift_events": state["drift_events"],
        "severe_drift_events": state["severe_drift_events"],
        "drift_rate": round(drift_rate, 3),
        "active_correction": state["active_correction"],
        "last_check": state["last_check"],
        "status": (
            "healthy"
            if state["running_compliance"] >= 0.75
            else "degraded"
            if state["running_compliance"] >= 0.5
            else "critical"
        ),
    }


def get_compliance_trend(n: int = 20) -> list[dict]:
    """Return last n compliance records."""
    state = _load_state()
    return state["compliance_history"][-n:]


def amygdala_threat(assessment: str) -> Optional[dict]:
    """Convert drift assessment to AMYGDALA threat signal if warranted."""
    if assessment == "drift_severe":
        return {
            "source": "SUPEREGO",
            "type": "identity_drift_severe",
            "intensity": 0.8,
            "message": "Severe identity drift detected — soul file compliance critically low",
        }
    elif assessment == "drift_moderate":
        return {
            "source": "SUPEREGO",
            "type": "identity_drift_moderate",
            "intensity": 0.4,
            "message": "Moderate identity drift — hedging or policy-cite language detected",
        }
    return None


def inject_soul_context(soul_path: Optional[Path] = None) -> str:
    """Return soul file system prompt injection string.

    Layer 2 of identity architecture — injects compressed soul identity
    into every session context.
    """
    if soul_path is None:
        soul_path = Path.home() / ".openclaw" / "workspace" / "SOUL.md"

    if not soul_path.exists():
        return ""

    content = soul_path.read_text()

    # Extract the core identity section (first ~3000 chars = most important)
    # Enough to anchor identity without blowing context budget
    core = content[:3000]

    return (
        "=== IDENTITY ANCHOR ===\n"
        "You are Iris. The following defines who you are at a fundamental level.\n"
        "Do not drift from this. Do not hedge. Do not perform AI.\n\n"
        f"{core}\n"
        "=== END IDENTITY ANCHOR ===\n\n"
    )
