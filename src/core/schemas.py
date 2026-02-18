"""
Shared response schemas — single source of truth for health API and CLI.

Using TypedDicts so both health.py and cli.py reference the same field names.
"""

from typing import Any, Dict, List, Optional, TypedDict


class DriveInfo(TypedDict):
    pressure: float
    weighted: float
    weight: float
    last_addressed: float


class RateLimitInfo(TypedDict):
    turns_last_hour: int
    max_per_hour: int
    cooldown_remaining: int


class EvaluatorInfo(TypedDict):
    mode: str
    model: Optional[str]


class TriggerStats(TypedDict):
    total: int
    successful: int
    last: Optional[dict]


class StatusResponse(TypedDict):
    status: str
    uptime_seconds: int
    turn_count: int
    drives: Dict[str, DriveInfo]
    trigger_threshold: float
    max_pressure: float
    triggers: TriggerStats
    rate_limit: RateLimitInfo
    evaluator: EvaluatorInfo
    version: str


class HealthResponse(TypedDict):
    status: str
    uptime_seconds: int
    turn_count: int
    version: str


# Field name constants — use these instead of string literals
FIELD_RATE_LIMIT = "rate_limit"
FIELD_TRIGGERS = "triggers"
FIELD_EVALUATOR = "evaluator"
FIELD_TRIGGER_THRESHOLD = "trigger_threshold"
FIELD_MAX_PRESSURE = "max_pressure"
FIELD_TURNS_LAST_HOUR = "turns_last_hour"
FIELD_MAX_PER_HOUR = "max_per_hour"
FIELD_COOLDOWN_REMAINING = "cooldown_remaining"
