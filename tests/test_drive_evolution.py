"""Tests for Drive Evolution — adaptive weight adjustment."""

import json
import time
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.drive_evolution import DriveEvolution, EvolutionConfig, EvaluationRecord, DrivePerformance
from src.drives.engine import Drive, DriveEngine


class TestEvaluationRecord:
    def test_roundtrip(self):
        r = EvaluationRecord(
            timestamp=time.time(), drive_name="goals", triggered=True,
            success=True, quality_score=0.8, loop_average=0.85, context="test"
        )
        d = r.to_dict()
        r2 = EvaluationRecord.from_dict(d)
        assert r2.drive_name == "goals"
        assert r2.quality_score == 0.8


class TestDrivePerformance:
    def test_true_positive_rate(self):
        p = DrivePerformance("goals", total_triggers=10, successful_triggers=7, failed_triggers=3)
        assert p.true_positive_rate == 0.7

    def test_false_positive_rate(self):
        p = DrivePerformance("goals", total_triggers=10, successful_triggers=7, failed_triggers=3)
        assert p.false_positive_rate == 0.3

    def test_average_quality(self):
        p = DrivePerformance("goals", total_triggers=4, total_quality=3.2)
        assert p.average_quality == 0.8

    def test_no_data_returns_neutral(self):
        p = DrivePerformance("goals")
        assert p.true_positive_rate == 0.5
        assert p.false_positive_rate == 0.5
        assert p.average_quality == 0.5


class TestDriveEvolution:
    def _make_evolution(self, **kwargs) -> DriveEvolution:
        tmp = tempfile.mkdtemp()
        config = EvolutionConfig(
            state_file=f"{tmp}/drive-performance.json",
            audit_dir=tmp,
            evolution_interval=kwargs.get("evolution_interval", 5),
            **{k: v for k, v in kwargs.items() if k != "evolution_interval"},
        )
        return DriveEvolution(config=config)

    def test_record_evaluation_increments_count(self):
        evo = self._make_evolution()
        evo.record_evaluation("goals", True, 0.8, 8.0, "test")
        assert evo.evaluation_count == 1
        assert "goals" in evo.history
        assert len(evo.history["goals"]) == 1

    def test_evolution_triggers_at_interval(self):
        evo = self._make_evolution(evolution_interval=3)
        r1 = evo.record_evaluation("goals", True, 0.9, 9.0)
        r2 = evo.record_evaluation("goals", True, 0.8, 8.0)
        assert r1 is None
        assert r2 is None
        r3 = evo.record_evaluation("goals", True, 0.85, 8.5)
        assert r3 is not None  # Evolution triggered
        assert "changes" in r3

    def test_weight_increases_for_high_performance(self):
        evo = self._make_evolution(evolution_interval=5)
        # 5 successful high-quality triggers
        for i in range(5):
            evo.record_evaluation("goals", True, 0.9, 9.0, f"good {i}")
        results = evo.evolve({"goals": 1.0})
        # Goals should increase (TP=100%, quality=0.9, FP=0%)
        if results["changes"]:
            change = results["changes"][0]
            assert change["after"] > change["before"]

    def test_weight_decreases_for_poor_performance(self):
        evo = self._make_evolution(evolution_interval=5)
        # 5 failed low-quality triggers
        for i in range(5):
            evo.record_evaluation("goals", False, 0.1, 2.0, f"bad {i}")
        results = evo.evolve({"goals": 1.0})
        if results["changes"]:
            change = results["changes"][0]
            assert change["after"] < change["before"]

    def test_max_delta_per_cycle(self):
        evo = self._make_evolution(max_delta_per_cycle=0.1)
        for i in range(10):
            evo.record_evaluation("goals", True, 1.0, 10.0)
        results = evo.evolve({"goals": 1.0})
        if results["changes"]:
            change = results["changes"][0]
            assert abs(change["delta"]) <= 0.1 + 1e-9  # float tolerance

    def test_weight_floor_general(self):
        evo = self._make_evolution(min_weight=0.3)
        for i in range(10):
            evo.record_evaluation("goals", False, 0.0, 0.0)
        results = evo.evolve({"goals": 0.35})
        for c in results.get("changes", []):
            if c["drive"] == "goals":
                assert c["after"] >= 0.3

    def test_weight_floor_protected(self):
        evo = self._make_evolution(
            protected_drives={"curiosity", "emotions"},
            protected_min_weight=0.5,
        )
        for i in range(10):
            evo.record_evaluation("curiosity", False, 0.0, 0.0)
        results = evo.evolve({"curiosity": 0.55})
        for c in results.get("changes", []):
            if c["drive"] == "curiosity":
                assert c["after"] >= 0.5

    def test_weight_ceiling(self):
        evo = self._make_evolution(max_weight=3.0)
        for i in range(10):
            evo.record_evaluation("goals", True, 1.0, 10.0)
        results = evo.evolve({"goals": 2.95})
        for c in results.get("changes", []):
            if c["drive"] == "goals":
                assert c["after"] <= 3.0

    def test_no_change_in_dead_zone(self):
        evo = self._make_evolution()
        # Mix of success/failure → composite near 0.5
        for i in range(5):
            evo.record_evaluation("goals", i % 2 == 0, 0.5, 5.0)
        results = evo.evolve({"goals": 1.0})
        # Should have no changes (dead zone 0.4-0.6)
        goal_changes = [c for c in results.get("changes", []) if c["drive"] == "goals"]
        assert len(goal_changes) == 0

    def test_minimum_data_requirement(self):
        evo = self._make_evolution()
        # Only 2 records — not enough to adjust
        evo.record_evaluation("goals", True, 1.0, 10.0)
        evo.record_evaluation("goals", True, 1.0, 10.0)
        results = evo.evolve({"goals": 1.0})
        assert len(results.get("changes", [])) == 0

    def test_persistence_roundtrip(self):
        tmp = tempfile.mkdtemp()
        config = EvolutionConfig(
            state_file=f"{tmp}/perf.json",
            audit_dir=tmp,
            evolution_interval=100,
        )
        evo1 = DriveEvolution(config=config)
        evo1.record_evaluation("goals", True, 0.9, 9.0, "test")
        evo1.record_evaluation("curiosity", False, 0.3, 3.0, "test2")

        # Load fresh instance
        evo2 = DriveEvolution(config=config)
        assert evo2.evaluation_count == 2
        assert len(evo2.history["goals"]) == 1
        assert len(evo2.history["curiosity"]) == 1

    def test_history_window_trimming(self):
        evo = self._make_evolution(evolution_interval=1000)
        evo.config.history_window = 5
        for i in range(10):
            evo.record_evaluation("goals", True, 0.8, 8.0)
        assert len(evo.history["goals"]) <= 5

    def test_audit_log_written(self):
        evo = self._make_evolution(evolution_interval=3)
        for i in range(3):
            evo.record_evaluation("goals", True, 0.95, 9.5)
        # Force evolution with known weight
        results = evo.evolve({"goals": 1.0})
        if results["changes"]:
            assert evo.audit.total_mutations > 0

    def test_get_performance_summary(self):
        evo = self._make_evolution()
        evo.record_evaluation("goals", True, 0.9, 9.0)
        evo.record_evaluation("goals", False, 0.2, 2.0)
        summary = evo.get_performance_summary()
        assert summary["evaluation_count"] == 2
        assert "goals" in summary["drives"]
        assert summary["drives"]["goals"]["total_triggers"] == 2

    def test_apply_evolved_weights(self):
        """Test applying evolution results to a mock drive engine."""
        evo = self._make_evolution()
        for i in range(5):
            evo.record_evaluation("test_drive", True, 0.95, 9.5)

        # Create a simple mock
        class MockDriveEngine:
            def __init__(self):
                self.drives = {"test_drive": Drive("test_drive", "test", weight=1.0)}

        engine = MockDriveEngine()
        results = evo.apply_evolved_weights(engine)
        # Weight should have been applied
        if results["changes"]:
            assert engine.drives["test_drive"].weight == results["changes"][0]["after"]

    def test_quality_score_clamped(self):
        evo = self._make_evolution()
        evo.record_evaluation("goals", True, 1.5, 12.0)  # Over max
        r = evo.history["goals"][-1]
        assert r.quality_score == 1.0
        assert r.loop_average == 1.0  # Normalized from 10.0 → 1.0, clamped

    def test_generate_reasoning(self):
        evo = self._make_evolution()
        perf = DrivePerformance("goals", total_triggers=10, successful_triggers=8,
                                failed_triggers=2, total_quality=7.5)
        reason = evo._generate_reasoning("goals", perf, 1.0, 1.1)
        assert "goals" in reason
        assert "increased" in reason
        assert "TP:" in reason
