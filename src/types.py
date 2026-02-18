"""
Pulse Type Definitions — structured types for data flowing through the system.

Use these instead of raw dicts for sensor readings, mutation commands,
and other inter-module data.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ─── Sensor Data ─────────────────────────────────────────────

@dataclass
class FileChange:
    path: str
    type: str  # "created", "modified", "deleted"


@dataclass
class FilesystemReading:
    changes: List[FileChange] = field(default_factory=list)


@dataclass
class SystemAlert:
    type: str  # "memory_pressure", "process_down"
    severity: str  # "high", "medium", "low"
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SystemReading:
    alerts: List[SystemAlert] = field(default_factory=list)


@dataclass
class ConversationReading:
    active: bool = False
    in_cooldown: bool = False
    last_human_activity: float = 0.0
    seconds_since: Optional[int] = None


@dataclass
class SensorSnapshot:
    """Combined reading from all sensors."""
    filesystem: FilesystemReading = field(default_factory=FilesystemReading)
    system: SystemReading = field(default_factory=SystemReading)
    conversation: ConversationReading = field(default_factory=ConversationReading)


# ─── Mutation Commands ───────────────────────────────────────

@dataclass
class MutationCommand:
    """A self-modification request from the agent."""
    type: str
    reason: str = "no reason given"
    drive: Optional[str] = None
    name: Optional[str] = None
    value: Optional[float] = None
    amount: Optional[float] = None
    weight: Optional[float] = None


@dataclass
class MutationResult:
    """Result of processing a mutation."""
    status: str  # "applied", "blocked", "error"
    type: str
    error: Optional[str] = None
    drive: Optional[str] = None
    name: Optional[str] = None
    before: Any = None
    after: Any = None
    clamped: bool = False
    weight: Optional[float] = None
