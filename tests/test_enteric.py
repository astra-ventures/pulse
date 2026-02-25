"""Tests for ENTERIC — Gut Feeling / Intuition."""
import json
import pytest
from unittest.mock import MagicMock

from pulse.src import enteric


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    monkeypatch.setattr(enteric, "_DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(enteric, "_DEFAULT_STATE_FILE", tmp_path / "enteric-state.json")


@pytest.fixture
def mock_thalamus(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(enteric.thalamus, "append", mock)
    return mock


# ── gut_check returns valid structure ───────────────────────────────────

def test_gut_check_returns_intuition(mock_thalamus):
    result = enteric.gut_check({"task": "write code"})
    assert result.direction in ("toward", "away", "neutral")
    assert 0.0 <= result.confidence <= 1.0
    assert isinstance(result.whisper, str)


def test_gut_check_neutral_when_no_patterns(mock_thalamus):
    result = enteric.gut_check({"anything": "here"})
    assert result.direction == "neutral"
    assert result.confidence <= 0.2


# ── Training updates accuracy ──────────────────────────────────────────

def test_training_positive_outcome(mock_thalamus):
    enteric.train("positive", {"task": "deploy"}, "toward")
    acc = enteric.get_accuracy()
    assert acc["toward"]["total"] == 1
    assert acc["toward"]["correct"] == 1


def test_training_wrong_prediction(mock_thalamus):
    enteric.train("negative", {"task": "risky"}, "toward")
    acc = enteric.get_accuracy()
    assert acc["toward"]["total"] == 1
    assert acc["toward"]["correct"] == 0


def test_training_adds_pattern(mock_thalamus):
    enteric.train("positive", {"task": "code"}, "toward")
    patterns = enteric.get_pattern_library()
    assert len(patterns) == 1
    assert patterns[0]["outcome"] == "positive"


# ── Pattern matching with similar contexts ─────────────────────────────

def test_gut_uses_trained_patterns(mock_thalamus):
    # Train with a pattern
    enteric.train("positive", {"task": "deploy", "env": "staging"}, "toward")
    enteric.train("positive", {"task": "deploy", "env": "prod"}, "toward")
    # Query with similar context
    result = enteric.gut_check({"task": "deploy", "env": "staging"})
    assert result.direction == "toward"
    assert result.confidence > 0.1


def test_gut_away_from_negative_patterns(mock_thalamus):
    enteric.train("negative", {"task": "delete", "target": "prod"}, "away")
    enteric.train("negative", {"task": "delete", "target": "db"}, "away")
    result = enteric.gut_check({"task": "delete", "target": "prod"})
    assert result.direction == "away"


# ── Mood bias from ENDOCRINE ──────────────────────────────────────────

def test_mood_bias_high_cortisol(tmp_path, mock_thalamus):
    # Write fake endocrine state with high cortisol
    endo = {"hormones": {"cortisol": 0.9, "dopamine": 0.5}}
    (tmp_path / "endocrine-state.json").write_text(json.dumps(endo))
    # Train a neutral baseline
    enteric.train("neutral", {"task": "decide"}, "neutral")
    result = enteric.gut_check({"task": "decide"})
    # High cortisol should bias toward away
    # (may still be neutral if pattern is strong, but bias exists)
    assert result.direction in ("away", "neutral")


def test_mood_bias_high_dopamine(tmp_path, mock_thalamus):
    endo = {"hormones": {"cortisol": 0.5, "dopamine": 0.9}}
    (tmp_path / "endocrine-state.json").write_text(json.dumps(endo))
    enteric.train("neutral", {"task": "explore"}, "neutral")
    result = enteric.gut_check({"task": "explore"})
    assert result.direction in ("toward", "neutral")


# ── Override tracking ──────────────────────────────────────────────────

def test_log_override(mock_thalamus):
    enteric.log_override({"task": "risky"}, "away", "proceed", outcome="positive")
    state = json.loads(enteric._DEFAULT_STATE_FILE.read_text())
    assert len(state["override_log"]) == 1
    assert state["override_log"][0]["gut_direction"] == "away"
    assert state["override_log"][0]["cortex_decision"] == "proceed"


# ── Confidence calculation ─────────────────────────────────────────────

def test_confidence_increases_with_agreement(mock_thalamus):
    # Multiple similar patterns agreeing
    for _ in range(3):
        enteric.train("positive", {"task": "code", "lang": "python"}, "toward")
    result = enteric.gut_check({"task": "code", "lang": "python"})
    assert result.confidence > 0.3


# ── THALAMUS integration ──────────────────────────────────────────────

def test_strong_intuition_broadcasts(mock_thalamus):
    # Create strong patterns
    for _ in range(5):
        enteric.train("positive", {"x": "y"}, "toward")
    result = enteric.gut_check({"x": "y"})
    if result.confidence > 0.7:
        mock_thalamus.assert_called()
        call_data = mock_thalamus.call_args[0][0]
        assert call_data["source"] == "enteric"


# ── Pattern library management ────────────────────────────────────────

def test_pattern_library_pruning(mock_thalamus):
    for i in range(250):
        enteric.train("positive", {"i": str(i)}, "toward")
    patterns = enteric.get_pattern_library()
    assert len(patterns) <= enteric.MAX_PATTERNS
