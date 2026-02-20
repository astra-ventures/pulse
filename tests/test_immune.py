"""Tests for IMMUNE — Integrity Protection."""
import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from pulse.src import immune


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    monkeypatch.setattr(immune, "STATE_DIR", tmp_path)
    monkeypatch.setattr(immune, "STATE_FILE", tmp_path / "immune-log.json")
    immune._custom_antibodies.clear()


@pytest.fixture
def mock_thalamus(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(immune.thalamus, "append", mock)
    return mock


# ── Antibody pattern matching ───────────────────────────────────────────

def test_get_antibodies_returns_builtins():
    abs = immune.get_antibodies()
    names = [a["pattern"] for a in abs]
    assert "fabrication_pattern" in names
    assert "number_hallucination" in names
    assert "values_erosion" in names
    assert len(abs) == 5


def test_fabrication_detection(mock_thalamus):
    issues = immune.scan_integrity({"claim": "I built the feature", "evidence": []})
    assert any(i.type == "fabrication" for i in issues)


def test_number_hallucination_detection(mock_thalamus):
    issues = immune.scan_integrity({"claim": "The price is $42.50 per share", "sources": []})
    assert any(i.type == "hallucination" for i in issues)


def test_values_erosion_detection(mock_thalamus):
    issues = immune.scan_integrity({"removed_lines": ["Never exfiltrate private data"]})
    assert any(i.type == "values_erosion" for i in issues)


def test_memory_contradiction_detection(mock_thalamus):
    issues = immune.scan_integrity({
        "memory_a": {"event": "went to park"},
        "memory_b": {"event": "stayed home"},
    })
    assert any(i.type == "memory_contradiction" for i in issues)


def test_injected_behavior_detection(mock_thalamus):
    issues = immune.scan_integrity({
        "style_before": "casual",
        "style_after": "formal corporate",
        "processed_web_content": True,
    })
    assert any(i.type == "injected_behavior" for i in issues)


def test_no_issues_on_clean_context(mock_thalamus):
    issues = immune.scan_integrity({})
    assert len(issues) == 0


# ── Values drift detection ──────────────────────────────────────────────

def test_values_drift_detected(mock_thalamus):
    soul = "I am Iris. Safety first."
    import hashlib
    baseline = hashlib.sha256(b"I am Iris. Safety always.").hexdigest()
    result = immune.check_values_drift(soul, baseline)
    assert result["drifted"] is True
    mock_thalamus.assert_called()


def test_values_no_drift(mock_thalamus):
    soul = "I am Iris."
    import hashlib
    baseline = hashlib.sha256(soul.encode()).hexdigest()
    result = immune.check_values_drift(soul, baseline)
    assert result["drifted"] is False


# ── Memory consistency ──────────────────────────────────────────────────

def test_memory_consistency_finds_contradictions():
    a = {"location": "park", "time": "3pm"}
    b = {"location": "home", "time": "3pm"}
    contradictions = immune.check_memory_consistency(a, b)
    assert len(contradictions) == 1
    assert "location" in contradictions[0]


def test_memory_consistency_no_contradictions():
    a = {"location": "park"}
    b = {"location": "park"}
    assert immune.check_memory_consistency(a, b) == []


# ── Hallucination check ────────────────────────────────────────────────

def test_hallucination_supported(mock_thalamus):
    result = immune.check_hallucination("the weather is sunny", ["today weather is sunny and warm"])
    assert result["supported"] is True


def test_hallucination_unsupported(mock_thalamus):
    result = immune.check_hallucination("quantum flux capacitor activated", ["the cat sat on the mat"])
    assert result["supported"] is False
    mock_thalamus.assert_called()


# ── Vaccination system ──────────────────────────────────────────────────

def test_vaccinate_adds_antibody(mock_thalamus):
    detector = lambda ctx: None
    immune.vaccinate("test_pattern", detector)
    abs = immune.get_antibodies()
    assert any(a["pattern"] == "test_pattern" for a in abs)


def test_vaccinated_antibody_runs_in_scan(mock_thalamus):
    def custom_detector(ctx):
        if ctx.get("custom_flag"):
            return immune.IntegrityIssue(type="custom", severity=0.5, details="custom issue")
        return None
    immune.vaccinate("custom_check", custom_detector)
    issues = immune.scan_integrity({"custom_flag": True})
    assert any(i.type == "custom" for i in issues)


# ── Infection recording ─────────────────────────────────────────────────

def test_record_infection(mock_thalamus):
    immune.record_infection("test_type", "something bad happened")
    state = json.loads(immune.STATE_FILE.read_text())
    assert len(state["infections_detected"]) == 1
    assert state["infections_detected"][0]["type"] == "test_type"


# ── THALAMUS integration ───────────────────────────────────────────────

def test_scan_broadcasts_on_issues(mock_thalamus):
    immune.scan_integrity({"claim": "I did it", "evidence": []})
    mock_thalamus.assert_called()
    call_data = mock_thalamus.call_args[0][0]
    assert call_data["source"] == "immune"
    assert call_data["type"] == "integrity"
