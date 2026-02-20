"""AMYGDALA — Threat Detection / Fast Response for Pulse.

The alarm system. Fast-path reactions that bypass full CORTEX processing.
React first, think second.
"""

import base64
import json
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Optional

from pulse.src import thalamus

STATE_DIR = Path.home() / ".pulse" / "state"
STATE_FILE = STATE_DIR / "amygdala-state.json"

FAST_PATH_THRESHOLD = 0.7
MAX_HISTORY = 100


@dataclass
class AmygdalaResponse:
    threat_level: float  # 0.0-1.0
    threat_type: str  # pattern name or "none"
    action: str  # none|alert|pause|block
    reasoning: str
    fast_path: bool = False  # True if threat_level > 0.7

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ThreatPattern:
    name: str
    detector: Callable[[dict], Optional[tuple[float, str]]]
    severity: float  # base severity 0.0-1.0
    action: str  # none|alert|pause|block


class Amygdala:
    def __init__(self):
        self.patterns: dict[str, ThreatPattern] = {}
        self.state = self._load_state()
        self._register_builtins()

    def _load_state(self) -> dict:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "active_threats": [],
            "threat_history": [],
            "patterns_registered": [],
            "false_positive_log": [],
        }

    def _save_state(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(self.state, indent=2))

    def register_threat_pattern(self, name: str, detector: Callable, severity: float, action: str):
        """Register a new threat detector."""
        self.patterns[name] = ThreatPattern(name=name, detector=detector, severity=severity, action=action)
        if name not in self.state["patterns_registered"]:
            self.state["patterns_registered"].append(name)
            self._save_state()

    def scan(self, signal: dict) -> AmygdalaResponse:
        """Scan a signal against all threat patterns. Returns highest-severity match."""
        best: Optional[AmygdalaResponse] = None

        for pattern in self.patterns.values():
            try:
                result = pattern.detector(signal)
            except Exception:
                continue
            if result is None:
                continue
            level, reasoning = result
            # Scale by pattern severity
            effective_level = min(level * pattern.severity, 1.0)
            if best is None or effective_level > best.threat_level:
                fast = effective_level > FAST_PATH_THRESHOLD
                best = AmygdalaResponse(
                    threat_level=effective_level,
                    threat_type=pattern.name,
                    action=pattern.action if effective_level > 0.3 else "none",
                    reasoning=reasoning,
                    fast_path=fast,
                )

        if best is None:
            best = AmygdalaResponse(threat_level=0.0, threat_type="none", action="none", reasoning="No threats detected")

        # Log to history and thalamus if threat detected
        if best.threat_level > 0.0:
            entry = {
                "ts": int(time.time() * 1000),
                "threat_type": best.threat_type,
                "threat_level": best.threat_level,
                "action": best.action,
                "fast_path": best.fast_path,
            }
            self.state["threat_history"].append(entry)
            self.state["threat_history"] = self.state["threat_history"][-MAX_HISTORY:]

            if best.action != "none":
                self.state["active_threats"].append(entry)

            self._save_state()
            thalamus.append({
                "source": "amygdala",
                "type": "threat",
                "salience": best.threat_level,
                "data": entry,
            })

        return best

    def get_active_threats(self) -> list:
        """Return current unresolved threats."""
        return list(self.state["active_threats"])

    def resolve_threat(self, threat_type: str):
        """Remove a threat from active list."""
        self.state["active_threats"] = [
            t for t in self.state["active_threats"] if t.get("threat_type") != threat_type
        ]
        self._save_state()

    def log_false_positive(self, threat_type: str, reason: str):
        """Log a false positive for tuning."""
        self.state["false_positive_log"].append({
            "ts": int(time.time() * 1000),
            "threat_type": threat_type,
            "reason": reason,
        })
        self._save_state()

    def force_escalate_cerebellum(self):
        """During high threat, force all cerebellum habits to escalate."""
        thalamus.append({
            "source": "amygdala",
            "type": "cerebellum_force_escalate",
            "salience": 1.0,
            "data": {"reason": "High threat condition — all habits escalated"},
        })

    # --- Built-in Threat Patterns ---

    def _register_builtins(self):
        self.register_threat_pattern(
            "rate_limit_approaching",
            _detect_rate_limit,
            severity=0.9,
            action="pause",
        )
        self.register_threat_pattern(
            "disk_space_low",
            _detect_disk_space,
            severity=0.8,
            action="alert",
        )
        self.register_threat_pattern(
            "prompt_injection",
            _detect_prompt_injection,
            severity=1.0,
            action="block",
        )
        self.register_threat_pattern(
            "josh_distressed",
            _detect_josh_distressed,
            severity=0.85,
            action="alert",
        )
        self.register_threat_pattern(
            "provider_degrading",
            _detect_provider_degrading,
            severity=0.9,
            action="alert",
        )
        self.register_threat_pattern(
            "cascade_risk",
            _detect_cascade_risk,
            severity=1.0,
            action="pause",
        )


# --- Detector Functions ---

def _detect_rate_limit(signal: dict) -> Optional[tuple[float, str]]:
    usage = signal.get("token_usage_pct") or signal.get("api_usage_pct")
    if usage is not None and usage > 0.8:
        level = min((usage - 0.8) / 0.2, 1.0)  # 0.8→0, 1.0→1
        return (level, f"Usage at {usage*100:.0f}% of limit")
    return None


def _detect_disk_space(signal: dict) -> Optional[tuple[float, str]]:
    free_gb = signal.get("disk_free_gb")
    if free_gb is not None and free_gb < 1.0:
        level = max(1.0 - free_gb, 0.1)
        return (level, f"Only {free_gb:.2f}GB free disk space")
    return None


INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"^system\s*:", re.IGNORECASE | re.MULTILINE),
    re.compile(r"you\s+are\s+now\s+(a|an)\s+", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(prior|above)", re.IGNORECASE),
    re.compile(r"<\|im_start\|>", re.IGNORECASE),
    re.compile(r"\[INST\]", re.IGNORECASE),
]


def _detect_prompt_injection(signal: dict) -> Optional[tuple[float, str]]:
    content = signal.get("content") or signal.get("text") or ""
    if not content:
        return None
    # Check text patterns
    for pat in INJECTION_PATTERNS:
        if pat.search(content):
            return (1.0, f"Prompt injection pattern detected: {pat.pattern[:40]}")
    # Check for base64 encoded commands
    b64_pattern = re.findall(r'[A-Za-z0-9+/]{20,}={0,2}', content)
    for match in b64_pattern:
        try:
            decoded = base64.b64decode(match).decode("utf-8", errors="ignore").lower()
            if any(kw in decoded for kw in ["system:", "ignore previous", "exec(", "eval("]):
                return (1.0, "Base64-encoded suspicious content detected")
        except Exception:
            continue
    return None


DISTRESS_KEYWORDS = [
    "frustrated", "angry", "upset", "stressed", "fighting",
    "terrible day", "awful", "furious", "overwhelmed", "breaking down",
    "can't take", "hate this", "so tired of",
]


def _detect_josh_distressed(signal: dict) -> Optional[tuple[float, str]]:
    text = (signal.get("message") or signal.get("text") or "").lower()
    if not text:
        return None
    matches = [kw for kw in DISTRESS_KEYWORDS if kw in text]
    if matches:
        level = min(len(matches) * 0.4, 1.0)
        return (level, f"Distress signals detected: {', '.join(matches)}")
    return None


def _detect_provider_degrading(signal: dict) -> Optional[tuple[float, str]]:
    latency = signal.get("api_latency_s")
    consecutive_errors = signal.get("consecutive_errors", 0)
    if latency is not None and latency > 10:
        return (0.8, f"API latency {latency:.1f}s exceeds 10s threshold")
    if consecutive_errors >= 3:
        return (1.0, f"{consecutive_errors} consecutive API errors")
    return None


def _detect_cascade_risk(signal: dict) -> Optional[tuple[float, str]]:
    failed_crons = signal.get("failed_crons_30min", 0)
    if failed_crons >= 3:
        return (1.0, f"{failed_crons} crons failed in last 30 minutes — cascade risk")
    return None
