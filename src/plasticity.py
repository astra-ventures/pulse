"""
Drive Evolution — adaptive weight adjustment based on real performance data.

After each EVALUATE cycle, records which drive triggered and what happened.
Periodically recalculates optimal weights from rolling performance history.

This is how drives learn which impulses actually produce good work vs noise.

Guardrails:
- Weight floor: 0.3 (general), 0.5 (protected drives like curiosity/emotions)
- Weight ceiling: 3.0
- Max change per cycle: ±0.1
- Full audit trail of every adjustment
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from pulse.src.evolution.audit import AuditLog, MutationRecord

logger = logging.getLogger("pulse.drive_evolution")


# ─── Configuration ───────────────────────────────────────────

@dataclass
class EvolutionConfig:
    """Configuration for drive evolution."""
    # How many evaluations between weight recalculations
    evolution_interval: int = 10
    # Rolling history window (max records kept per drive)
    history_window: int = 100
    # Weight bounds
    min_weight: float = 0.3
    max_weight: float = 3.0
    # Protected drives get a higher floor
    protected_drives: set = field(default_factory=lambda: {"curiosity", "emotions"})
    protected_min_weight: float = 0.5
    # Max weight change per evolution cycle
    max_delta_per_cycle: float = 0.1
    # State file path
    state_file: str = "~/.pulse/state/drive-performance.json"
    # Audit log directory
    audit_dir: str = "~/.pulse/state"


# ─── Data Structures ────────────────────────────────────────

@dataclass
class EvaluationRecord:
    """Record of a single drive trigger + outcome."""
    timestamp: float
    drive_name: str
    triggered: bool           # Did this drive cause the trigger?
    success: bool             # Did the session produce good work?
    quality_score: float      # 0.0-1.0 quality assessment
    loop_average: float       # CORTEX loop average score (0-10 normalized to 0-1)
    context: str = ""         # Brief description of what happened

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "EvaluationRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class DrivePerformance:
    """Aggregated performance metrics for a single drive."""
    drive_name: str
    total_triggers: int = 0
    successful_triggers: int = 0
    failed_triggers: int = 0
    total_quality: float = 0.0
    current_weight: float = 1.0

    @property
    def true_positive_rate(self) -> float:
        """Drive fired → produced good work."""
        if self.total_triggers == 0:
            return 0.5  # No data = neutral
        return self.successful_triggers / self.total_triggers

    @property
    def false_positive_rate(self) -> float:
        """Drive fired → wasted session."""
        if self.total_triggers == 0:
            return 0.5
        return self.failed_triggers / self.total_triggers

    @property
    def average_quality(self) -> float:
        """Average quality score when this drive triggers."""
        if self.total_triggers == 0:
            return 0.5
        return self.total_quality / self.total_triggers


# ─── Main Engine ─────────────────────────────────────────────

class Plasticity:
    """
    Tracks drive performance and evolves weights over time.

    Flow:
    1. After each EVALUATE cycle, call record_evaluation()
    2. Every N evaluations, evolve() is called automatically
    3. evolve() recalculates optimal weights and writes them back
    """

    def __init__(self, config: Optional[EvolutionConfig] = None, audit_log: Optional[AuditLog] = None):
        self.config = config or EvolutionConfig()
        self.state_file = Path(self.config.state_file).expanduser()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        audit_dir = Path(self.config.audit_dir).expanduser()
        audit_dir.mkdir(parents=True, exist_ok=True)
        self.audit = audit_log or AuditLog(audit_dir)

        # In-memory state
        self.history: Dict[str, List[EvaluationRecord]] = {}
        self.evaluation_count: int = 0
        self.last_evolution_time: float = 0.0

        # Load persisted state
        self._load_state()

    def _load_state(self):
        """Load performance history from disk."""
        if not self.state_file.exists():
            return
        try:
            data = json.loads(self.state_file.read_text())
            self.evaluation_count = data.get("evaluation_count", 0)
            self.last_evolution_time = data.get("last_evolution_time", 0.0)
            for drive_name, records in data.get("history", {}).items():
                self.history[drive_name] = [
                    EvaluationRecord.from_dict(r) for r in records
                ]
            logger.info(f"Loaded drive performance state: {self.evaluation_count} evaluations tracked")
        except (json.JSONDecodeError, OSError, TypeError) as e:
            logger.warning(f"Failed to load drive performance state: {e}")

    def _save_state(self):
        """Persist performance history to disk."""
        data = {
            "evaluation_count": self.evaluation_count,
            "last_evolution_time": self.last_evolution_time,
            "history": {
                name: [r.to_dict() for r in records[-self.config.history_window:]]
                for name, records in self.history.items()
            },
        }
        try:
            self.state_file.write_text(json.dumps(data, indent=2))
        except OSError as e:
            logger.error(f"Failed to save drive performance state: {e}")

    def record_evaluation(
        self,
        drive_name: str,
        success: bool,
        quality_score: float,
        loop_average: float,
        context: str = "",
    ) -> Optional[Dict[str, Any]]:
        """
        Record an evaluation outcome for a drive.

        Args:
            drive_name: Which drive triggered the session
            success: Whether the session produced good work
            quality_score: 0.0-1.0 quality assessment
            loop_average: CORTEX loop average score (0-10, will be normalized)
            context: Brief description

        Returns:
            Evolution results if an evolution cycle was triggered, else None
        """
        # Normalize loop_average from 0-10 to 0-1
        normalized_loop = max(0.0, min(1.0, loop_average / 10.0))

        record = EvaluationRecord(
            timestamp=time.time(),
            drive_name=drive_name,
            triggered=True,
            success=success,
            quality_score=max(0.0, min(1.0, quality_score)),
            loop_average=normalized_loop,
            context=context,
        )

        if drive_name not in self.history:
            self.history[drive_name] = []
        self.history[drive_name].append(record)

        # Trim to window
        if len(self.history[drive_name]) > self.config.history_window:
            self.history[drive_name] = self.history[drive_name][-self.config.history_window:]

        self.evaluation_count += 1
        self._save_state()

        logger.info(
            f"Recorded evaluation #{self.evaluation_count}: "
            f"drive={drive_name} success={success} quality={quality_score:.2f} "
            f"loop_avg={loop_average:.1f}"
        )

        # Check if it's time to evolve
        if self.evaluation_count % self.config.evolution_interval == 0:
            return self.evolve()
        return None

    def evolve(self, current_weights: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """
        Recalculate optimal weights based on performance history.

        Args:
            current_weights: Dict of drive_name → current weight.
                             If None, uses weights from history context.

        Returns:
            Dict with evolution results including weight changes.
        """
        self.last_evolution_time = time.time()
        results: Dict[str, Any] = {
            "timestamp": self.last_evolution_time,
            "evaluation_count": self.evaluation_count,
            "changes": [],
            "performances": {},
        }

        if current_weights is None:
            current_weights = {}

        for drive_name, records in self.history.items():
            if not records:
                continue

            perf = self._calculate_performance(drive_name, records)
            results["performances"][drive_name] = {
                "true_positive_rate": round(perf.true_positive_rate, 3),
                "false_positive_rate": round(perf.false_positive_rate, 3),
                "average_quality": round(perf.average_quality, 3),
                "total_triggers": perf.total_triggers,
            }

            current_w = current_weights.get(drive_name, perf.current_weight)
            new_weight = self._calculate_new_weight(drive_name, current_w, perf)

            if new_weight != current_w:
                change = {
                    "drive": drive_name,
                    "before": round(current_w, 4),
                    "after": round(new_weight, 4),
                    "delta": round(new_weight - current_w, 4),
                    "reasoning": self._generate_reasoning(drive_name, perf, current_w, new_weight),
                }
                results["changes"].append(change)

                # Audit log
                self.audit.record(MutationRecord(
                    timestamp=time.time(),
                    mutation_type="drive_evolution",
                    target=f"drives.{drive_name}.weight",
                    before=round(current_w, 4),
                    after=round(new_weight, 4),
                    reason=change["reasoning"],
                    source="drive_evolution",
                ))

        self._save_state()

        if results["changes"]:
            logger.info(
                f"Drive evolution cycle complete: {len(results['changes'])} weight changes"
            )
            for c in results["changes"]:
                logger.info(f"  {c['drive']}: {c['before']} → {c['after']} ({c['reasoning']})")
        else:
            logger.info("Drive evolution cycle complete: no changes needed")

        return results

    def _calculate_performance(self, drive_name: str, records: List[EvaluationRecord]) -> DrivePerformance:
        """Calculate aggregated performance metrics from history."""
        perf = DrivePerformance(drive_name=drive_name)
        for r in records:
            if r.triggered:
                perf.total_triggers += 1
                if r.success:
                    perf.successful_triggers += 1
                else:
                    perf.failed_triggers += 1
                perf.total_quality += r.quality_score
        return perf

    def _calculate_new_weight(self, drive_name: str, current: float, perf: DrivePerformance) -> float:
        """
        Calculate the new weight for a drive based on performance.

        Algorithm:
        - Composite score = 0.4 * true_positive_rate + 0.3 * avg_quality + 0.3 * (1 - false_positive_rate)
        - If score > 0.6: weight should increase (drive is performing well)
        - If score < 0.4: weight should decrease (drive is underperforming)
        - Between 0.4-0.6: no change (neutral performance)
        - Change is proportional to distance from 0.5 center, capped at ±max_delta
        """
        # Need minimum data before adjusting
        if perf.total_triggers < 3:
            return current

        composite = (
            0.4 * perf.true_positive_rate +
            0.3 * perf.average_quality +
            0.3 * (1.0 - perf.false_positive_rate)
        )

        # Dead zone: 0.4-0.6 = no change
        if 0.4 <= composite <= 0.6:
            return current

        # Calculate desired delta
        # Positive composite (>0.6) → increase weight
        # Negative composite (<0.4) → decrease weight
        if composite > 0.6:
            raw_delta = (composite - 0.6) * 0.5  # Scale factor
        else:
            raw_delta = (composite - 0.4) * 0.5  # Will be negative

        # Clamp to max delta per cycle
        delta = max(-self.config.max_delta_per_cycle, min(self.config.max_delta_per_cycle, raw_delta))

        new_weight = current + delta

        # Apply floor/ceiling
        floor = self._get_weight_floor(drive_name)
        new_weight = max(floor, min(self.config.max_weight, new_weight))

        return round(new_weight, 4)

    def _get_weight_floor(self, drive_name: str) -> float:
        """Get the minimum weight for a drive (protected drives have higher floor)."""
        if drive_name in self.config.protected_drives:
            return self.config.protected_min_weight
        return self.config.min_weight

    def _generate_reasoning(self, drive_name: str, perf: DrivePerformance,
                            old_weight: float, new_weight: float) -> str:
        """Generate human-readable reasoning for a weight change."""
        direction = "increased" if new_weight > old_weight else "decreased"
        parts = [
            f"{drive_name} {direction} {old_weight:.2f}→{new_weight:.2f}",
            f"(TP:{perf.true_positive_rate:.0%}",
            f"FP:{perf.false_positive_rate:.0%}",
            f"quality:{perf.average_quality:.0%}",
            f"n={perf.total_triggers})",
        ]
        return " ".join(parts)

    def get_performance_summary(self) -> Dict[str, Any]:
        """Get a summary of all drive performance for display/logging."""
        summary = {
            "evaluation_count": self.evaluation_count,
            "last_evolution": self.last_evolution_time,
            "drives": {},
        }
        for drive_name, records in self.history.items():
            perf = self._calculate_performance(drive_name, records)
            summary["drives"][drive_name] = {
                "total_triggers": perf.total_triggers,
                "true_positive_rate": round(perf.true_positive_rate, 3),
                "false_positive_rate": round(perf.false_positive_rate, 3),
                "average_quality": round(perf.average_quality, 3),
            }
        return summary

    def apply_evolved_weights(self, drive_engine) -> Dict[str, Any]:
        """
        Convenience method: run evolution and apply results directly to a DriveEngine.

        Returns evolution results including applied changes.
        """
        current_weights = {
            name: drive.weight
            for name, drive in drive_engine.drives.items()
        }

        results = self.evolve(current_weights)

        for change in results.get("changes", []):
            drive_name = change["drive"]
            if drive_name in drive_engine.drives:
                drive_engine.drives[drive_name].weight = change["after"]
                logger.info(f"Applied evolved weight: {drive_name} = {change['after']}")

        return results
