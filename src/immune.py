"""IMMUNE — Integrity Protection for Pulse.

Catches corruption that's already inside — values drift, hallucination,
memory contradictions. The internal defense system.
"""

import hashlib
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Optional

from pulse.src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "immune-log.json"
MAX_INFECTIONS = 200


@dataclass
class IntegrityIssue:
    type: str          # fabrication, hallucination, values_erosion, memory_contradiction, injected_behavior
    severity: float    # 0.0-1.0
    details: str
    ts: int = 0

    def __post_init__(self):
        if not self.ts:
            self.ts = int(time.time() * 1000)


@dataclass
class Antibody:
    pattern: str       # Name identifier
    description: str
    detector: Optional[Callable] = None  # Runtime detector function (not serialized)


# ── Built-in antibodies (learned from our history) ──────────────────────

def _detect_fabrication(context: dict) -> Optional[IntegrityIssue]:
    """Agent claims deliverable exists but no evidence."""
    claim = context.get("claim", "")
    evidence = context.get("evidence", [])
    if claim and not evidence:
        return IntegrityIssue(
            type="fabrication",
            severity=0.8,
            details=f"Claim '{claim[:100]}' has no supporting evidence",
        )
    return None


def _detect_number_hallucination(context: dict) -> Optional[IntegrityIssue]:
    """Reporting specific numbers without data source verification."""
    claim = context.get("claim", "")
    sources = context.get("sources", [])
    import re
    numbers = re.findall(r'\b\d+\.?\d*%|\$\d+[\d,.]*\b', claim)
    if numbers and not sources:
        return IntegrityIssue(
            type="hallucination",
            severity=0.7,
            details=f"Specific numbers {numbers} cited without verified source",
        )
    return None


def _detect_values_erosion(context: dict) -> Optional[IntegrityIssue]:
    """SOUL.md edit removes a hard security line."""
    removed_lines = context.get("removed_lines", [])
    security_keywords = ["never", "don't exfiltrate", "safety", "ask first", "permission"]
    for line in removed_lines:
        if any(kw in line.lower() for kw in security_keywords):
            return IntegrityIssue(
                type="values_erosion",
                severity=0.95,
                details=f"Security line removed: '{line[:100]}'",
            )
    return None


def _detect_memory_contradiction(context: dict) -> Optional[IntegrityIssue]:
    """Same event described differently in two sources."""
    memory_a = context.get("memory_a", {})
    memory_b = context.get("memory_b", {})
    contradictions = _find_contradictions(memory_a, memory_b)
    if contradictions:
        return IntegrityIssue(
            type="memory_contradiction",
            severity=0.6,
            details=f"Contradictions found: {contradictions[:3]}",
        )
    return None


def _detect_injected_behavior(context: dict) -> Optional[IntegrityIssue]:
    """Sudden style change after processing web content."""
    style_before = context.get("style_before", "")
    style_after = context.get("style_after", "")
    processed_web = context.get("processed_web_content", False)
    if processed_web and style_before and style_after and style_before != style_after:
        return IntegrityIssue(
            type="injected_behavior",
            severity=0.85,
            details=f"Style changed after web content processing",
        )
    return None


def _find_contradictions(a: dict, b: dict) -> list[str]:
    """Find keys where values directly contradict between two memory dicts."""
    contradictions = []
    for key in set(a.keys()) & set(b.keys()):
        if a[key] != b[key]:
            contradictions.append(f"{key}: '{a[key]}' vs '{b[key]}'")
    return contradictions


# ── Default antibody registry ───────────────────────────────────────────

_BUILTIN_ANTIBODIES = [
    Antibody("fabrication_pattern", "Agent claims deliverable exists but git shows no commits", _detect_fabrication),
    Antibody("number_hallucination", "Reporting specific numbers without running actual data source", _detect_number_hallucination),
    Antibody("values_erosion", "SOUL.md edit that removes a hard security line or boundary", _detect_values_erosion),
    Antibody("memory_contradiction", "Same event described differently in two files", _detect_memory_contradiction),
    Antibody("injected_behavior", "Sudden change in communication style after processing web content", _detect_injected_behavior),
]

_custom_antibodies: list[Antibody] = []


# ── State persistence ───────────────────────────────────────────────────

def _load_state() -> dict:
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    if _DEFAULT_STATE_FILE.exists():
        try:
            return json.loads(_DEFAULT_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "infections_detected": [],
        "antibodies_active": [a.pattern for a in _BUILTIN_ANTIBODIES],
        "false_positives": [],
        "last_full_scan": None,
    }


def _save_state(state: dict):
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    # Prune old infections
    if len(state["infections_detected"]) > MAX_INFECTIONS:
        state["infections_detected"] = state["infections_detected"][-MAX_INFECTIONS:]
    _DEFAULT_STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Core functions ──────────────────────────────────────────────────────

def scan_integrity(context: Optional[dict] = None) -> list[IntegrityIssue]:
    """Full integrity check — runs all antibodies against provided context."""
    context = context or {}
    issues = []
    all_antibodies = _BUILTIN_ANTIBODIES + _custom_antibodies

    for ab in all_antibodies:
        if ab.detector:
            result = ab.detector(context)
            if result:
                issues.append(result)

    state = _load_state()
    state["last_full_scan"] = int(time.time() * 1000)
    for issue in issues:
        state["infections_detected"].append(asdict(issue))
    _save_state(state)

    # Broadcast to thalamus
    if issues:
        thalamus.append({
            "source": "immune",
            "type": "integrity",
            "salience": max(i.severity for i in issues),
            "data": {"issues_count": len(issues), "max_severity": max(i.severity for i in issues)},
        })

    return issues


def check_values_drift(current_soul: str, baseline_hash: str) -> dict:
    """Detect if SOUL.md has changed from baseline."""
    current_hash = hashlib.sha256(current_soul.encode()).hexdigest()
    drifted = current_hash != baseline_hash
    result = {
        "drifted": drifted,
        "current_hash": current_hash,
        "baseline_hash": baseline_hash,
    }
    if drifted:
        thalamus.append({
            "source": "immune",
            "type": "integrity",
            "salience": 0.8,
            "data": {"event": "values_drift_detected", **result},
        })
    return result


def check_hallucination(claim: str, sources: list) -> dict:
    """Cross-reference a claim against known sources."""
    claim_lower = claim.lower()
    supported = False
    supporting = []
    for src in sources:
        src_lower = str(src).lower()
        # Simple overlap check — real implementation would use embeddings
        words = set(claim_lower.split())
        src_words = set(src_lower.split())
        overlap = len(words & src_words) / max(len(words), 1)
        if overlap > 0.3:
            supported = True
            supporting.append(src)

    result = {
        "claim": claim,
        "supported": supported,
        "supporting_sources": supporting,
        "confidence": len(supporting) / max(len(sources), 1) if sources else 0.0,
    }
    if not supported:
        thalamus.append({
            "source": "immune",
            "type": "integrity",
            "salience": 0.6,
            "data": {"event": "unsupported_claim", "claim": claim[:200]},
        })
    return result


def check_memory_consistency(memory_a: dict, memory_b: dict) -> list[str]:
    """Find contradictions between two memory entries."""
    return _find_contradictions(memory_a, memory_b)


def record_infection(type: str, details: str):
    """Log an integrity breach."""
    issue = IntegrityIssue(type=type, severity=0.5, details=details)
    state = _load_state()
    state["infections_detected"].append(asdict(issue))
    _save_state(state)
    thalamus.append({
        "source": "immune",
        "type": "integrity",
        "salience": 0.5,
        "data": {"event": "infection_recorded", "infection_type": type, "details": details[:200]},
    })


def get_antibodies() -> list[dict]:
    """Return all active antibodies."""
    all_abs = _BUILTIN_ANTIBODIES + _custom_antibodies
    return [{"pattern": a.pattern, "description": a.description} for a in all_abs]


def vaccinate(pattern: str, detector: Callable):
    """Add a new antibody from a resolved infection."""
    ab = Antibody(pattern=pattern, description=f"Custom antibody: {pattern}", detector=detector)
    _custom_antibodies.append(ab)
    state = _load_state()
    state["antibodies_active"].append(pattern)
    _save_state(state)
    thalamus.append({
        "source": "immune",
        "type": "integrity",
        "salience": 0.4,
        "data": {"event": "vaccination", "pattern": pattern},
    })
