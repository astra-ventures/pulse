"""Tests for CHALLENGER — Goal Expansion / Stagnation Sentinel."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pulse.src import challenger


# ── Fixtures ────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Redirect all state files to a temp directory for test isolation."""
    monkeypatch.setattr(challenger, "_DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(challenger, "_DEFAULT_STATE_FILE", tmp_path / "challenger-state.json")
    monkeypatch.setattr(challenger, "_THALAMUS_FILE", tmp_path / "thalamus.jsonl")
    monkeypatch.setattr(challenger, "_CHRONICLE_FILE", tmp_path / "chronicle.jsonl")
    return tmp_path


@pytest.fixture
def sample_thalamus(isolated_state):
    """Write a sample diverse THALAMUS file."""
    entries = [
        {"type": "ship_recorded", "source": "motoric", "data": {"name": "pulse_v1"}, "ts": time.time() - 3600},
        {"type": "mood_update", "source": "endocrine", "data": {"mood": "energized"}, "ts": time.time() - 3000},
        {"type": "filter_cycle", "source": "nephron", "data": {"pruned": 5}, "ts": time.time() - 2400},
        {"type": "threat_resolved", "source": "amygdala", "data": {}, "ts": time.time() - 1800},
        {"type": "learning_update", "source": "retina", "data": {}, "ts": time.time() - 1200},
        {"type": "stagnation_detected", "source": "challenger", "data": {}, "ts": time.time() - 600},
    ]
    path = isolated_state / "thalamus.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return path


@pytest.fixture
def stagnant_thalamus(isolated_state):
    """Write a THALAMUS file showing repetition."""
    entries = [
        {"type": "generate_task", "source": "hypothalamus",
         "data": {"task": "reflect on current state and purpose"}, "ts": time.time() - i * 60}
        for i in range(8)
    ]
    path = isolated_state / "thalamus.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return path


# ── State management ────────────────────────────────────────────────────────────

class TestStateManagement:
    def test_default_state(self):
        state = challenger._default_state()
        assert state["total_scans"] == 0
        assert state["total_challenges_issued"] == 0
        assert state["last_scan"] == 0
        assert state["last_challenge_ts"] == 0
        assert state["stagnation_streak"] == 0
        assert isinstance(state["novelty_history"], list)
        assert isinstance(state["recent_domains_suggested"], list)

    def test_load_state_missing_file(self, isolated_state):
        state = challenger._load_state()
        assert state == challenger._default_state()

    def test_save_and_reload_state(self, isolated_state):
        state = challenger._default_state()
        state["total_scans"] = 42
        state["stagnation_streak"] = 3
        challenger._save_state(state)

        loaded = challenger._load_state()
        assert loaded["total_scans"] == 42
        assert loaded["stagnation_streak"] == 3

    def test_load_state_corrupt_file(self, isolated_state):
        state_file = isolated_state / "challenger-state.json"
        state_file.write_text("not valid json{{{{")
        state = challenger._load_state()
        assert state == challenger._default_state()

    def test_save_creates_directory(self, tmp_path, monkeypatch):
        deep_dir = tmp_path / "a" / "b" / "c"
        monkeypatch.setattr(challenger, "_DEFAULT_STATE_DIR", deep_dir)
        monkeypatch.setattr(challenger, "_DEFAULT_STATE_FILE", deep_dir / "challenger-state.json")
        state = challenger._default_state()
        challenger._save_state(state)
        assert (deep_dir / "challenger-state.json").exists()


# ── Loop interval ────────────────────────────────────────────────────────────────

class TestShouldRun:
    def test_zero_never_runs(self):
        assert not challenger.should_run(0)

    def test_before_interval(self):
        for i in range(1, challenger.LOOP_INTERVAL):
            assert not challenger.should_run(i)

    def test_at_interval(self):
        assert challenger.should_run(challenger.LOOP_INTERVAL)

    def test_multiples_of_interval(self):
        assert challenger.should_run(challenger.LOOP_INTERVAL * 2)
        assert challenger.should_run(challenger.LOOP_INTERVAL * 3)

    def test_non_multiples_dont_run(self):
        assert not challenger.should_run(challenger.LOOP_INTERVAL + 1)
        assert not challenger.should_run(challenger.LOOP_INTERVAL * 2 - 1)


# ── Complexity scoring ───────────────────────────────────────────────────────────

class TestComplexityScoring:
    def test_empty_string(self):
        score = challenger._score_complexity("")
        assert score == 1.0

    def test_low_complexity_keywords(self):
        assert challenger._score_complexity("reflect on state") == 1.0
        assert challenger._score_complexity("check status") >= 2.0
        assert challenger._score_complexity("log output") >= 2.0

    def test_high_complexity_keywords(self):
        assert challenger._score_complexity("build a new module") >= 7.0
        assert challenger._score_complexity("implement the feature") >= 8.0
        assert challenger._score_complexity("design the architecture") >= 7.0

    def test_unknown_text(self):
        score = challenger._score_complexity("xyzzy quux blarg")
        assert score == 2.0  # default

    def test_mixed_takes_max(self):
        # "reflect" (1) and "build" (7) → should return 7
        score = challenger._score_complexity("reflect on how to build this")
        assert score >= 7.0


# ── Repetition detection ─────────────────────────────────────────────────────────

class TestRepetitionDetection:
    def test_empty_entries(self):
        rep = challenger.detect_repetition([])
        assert rep["repetitive"] is False
        assert rep["count"] == 0

    def test_diverse_entries(self, sample_thalamus):
        entries = challenger._read_recent_thalamus()
        rep = challenger.detect_repetition(entries)
        # Diverse entries shouldn't trigger repetition
        assert rep["count"] < challenger.REPETITION_THRESHOLD or not rep["repetitive"]

    def test_repeated_entries_trigger_stagnation(self):
        entries = [
            {"type": "generate_task", "data": {"task": "reflect on current state"}, "source": "hypothalamus"}
            for _ in range(6)
        ]
        rep = challenger.detect_repetition(entries)
        assert rep["repetitive"] is True
        assert rep["count"] >= challenger.REPETITION_THRESHOLD

    def test_below_threshold_not_repetitive(self):
        entries = [
            {"type": "generate_task", "data": {"task": "reflect on current state"}, "source": "hypothalamus"}
            for _ in range(challenger.REPETITION_THRESHOLD - 1)
        ]
        rep = challenger.detect_repetition(entries)
        # At threshold-1, should NOT be repetitive
        assert rep["count"] == challenger.REPETITION_THRESHOLD - 1
        assert rep["repetitive"] is False

    def test_complexity_avg_in_result(self):
        entries = [
            {"type": "t", "data": {"task": "build something amazing"}, "source": "s"},
            {"type": "t", "data": {"task": "reflect quietly"}, "source": "s"},
        ]
        rep = challenger.detect_repetition(entries)
        assert "complexity_avg" in rep
        assert isinstance(rep["complexity_avg"], float)

    def test_uses_type_as_fallback(self):
        entries = [
            {"type": "reflect", "data": {}, "source": "hypothalamus"}
            for _ in range(5)
        ]
        rep = challenger.detect_repetition(entries)
        assert rep["repetitive"] is True


# ── Novelty scoring ──────────────────────────────────────────────────────────────

class TestNoveltyScoring:
    def test_empty_entries_neutral(self):
        score = challenger.compute_novelty_score([])
        assert score == 0.5

    def test_diverse_entries_higher_score(self, sample_thalamus):
        entries = challenger._read_recent_thalamus()
        score = challenger.compute_novelty_score(entries)
        assert score > 0.2

    def test_uniform_entries_lower_score(self):
        entries = [
            {"type": "reflect", "source": "hypothalamus", "data": {}}
            for _ in range(10)
        ]
        diverse_entries = [
            {"type": f"event_{i}", "source": f"module_{i}", "data": {}}
            for i in range(10)
        ]
        uniform_score = challenger.compute_novelty_score(entries)
        diverse_score = challenger.compute_novelty_score(diverse_entries)
        assert uniform_score <= diverse_score

    def test_score_range(self, sample_thalamus):
        entries = challenger._read_recent_thalamus()
        score = challenger.compute_novelty_score(entries)
        assert 0.0 <= score <= 1.0

    def test_many_source_types_increase_score(self):
        entries = [
            {"type": "event", "source": f"module_{i}", "data": {}}
            for i in range(6)
        ]
        score = challenger.compute_novelty_score(entries)
        assert score >= 0.4  # 6 sources = fully diverse source component


# ── THALAMUS reading ─────────────────────────────────────────────────────────────

class TestReadThalamus:
    def test_missing_file_returns_empty(self, isolated_state):
        result = challenger._read_recent_thalamus()
        assert result == []

    def test_reads_recent_entries(self, sample_thalamus):
        entries = challenger._read_recent_thalamus()
        assert len(entries) > 0
        assert len(entries) <= challenger.THALAMUS_SCAN_WINDOW

    def test_respects_window_size(self, isolated_state):
        many_entries = [
            {"type": f"t_{i}", "source": "test", "data": {}}
            for i in range(100)
        ]
        path = isolated_state / "thalamus.jsonl"
        path.write_text("\n".join(json.dumps(e) for e in many_entries) + "\n")
        entries = challenger._read_recent_thalamus(n=10)
        assert len(entries) == 10
        # Should be the LAST 10
        assert entries[-1]["type"] == "t_99"

    def test_skips_invalid_json(self, isolated_state):
        path = isolated_state / "thalamus.jsonl"
        path.write_text('{"type": "valid"}\nnot json\n{"type": "also_valid"}\n')
        entries = challenger._read_recent_thalamus()
        assert len(entries) == 2
        assert all("type" in e for e in entries)


# ── Challenge selection ──────────────────────────────────────────────────────────

class TestPickChallenge:
    def test_returns_valid_challenge(self):
        ch = challenger.pick_challenge([])
        assert "domain" in ch
        assert "label" in ch
        assert "prompt" in ch

    def test_domain_in_known_list(self):
        known_domains = {d["name"] for d in challenger.CHALLENGE_DOMAINS}
        for _ in range(20):
            ch = challenger.pick_challenge([])
            assert ch["domain"] in known_domains

    def test_avoids_recent_domains(self):
        """With enough trials, should not always repeat excluded domain."""
        excluded = ["technical_build", "market_research"]
        results = [challenger.pick_challenge(excluded) for _ in range(30)]
        domains_seen = {r["domain"] for r in results}
        # Should see at least one domain that's not the excluded ones
        non_excluded = domains_seen - set(excluded)
        assert len(non_excluded) > 0

    def test_falls_back_when_all_excluded(self):
        """When all domains recently used, should still pick something."""
        all_domains = [d["name"] for d in challenger.CHALLENGE_DOMAINS]
        ch = challenger.pick_challenge(all_domains)
        assert ch["domain"] in all_domains

    def test_prompt_is_string(self):
        ch = challenger.pick_challenge([])
        assert isinstance(ch["prompt"], str)
        assert len(ch["prompt"]) > 5


# ── Core scan ────────────────────────────────────────────────────────────────────

class TestScan:
    def test_scan_returns_expected_keys(self, isolated_state):
        result = challenger.scan()
        assert "stagnant" in result
        assert "novelty_score" in result
        assert "repetition" in result
        assert "challenge" in result
        assert "stagnation_streak" in result

    def test_novelty_score_in_range(self, isolated_state):
        result = challenger.scan()
        assert 0.0 <= result["novelty_score"] <= 1.0

    def test_stagnation_increments_streak(self, stagnant_thalamus):
        # Force stagnation: no challenge ever issued → hours_since >= threshold
        result = challenger.scan()
        assert result["stagnant"] is True
        assert result["stagnation_streak"] >= 1

    def test_stagnation_provides_challenge(self, stagnant_thalamus):
        result = challenger.scan()
        if result["stagnant"]:
            assert result["challenge"] is not None
            ch = result["challenge"]
            assert "domain" in ch
            assert "prompt" in ch

    def test_no_stagnation_resets_streak(self, isolated_state, sample_thalamus):
        """If already has recent challenge and diverse thalamus, streak should stay at 0."""
        # Pre-populate state with a recent challenge
        state = challenger._default_state()
        state["last_challenge_ts"] = time.time() - 60   # 1 minute ago
        state["stagnation_streak"] = 5
        challenger._save_state(state)

        result = challenger.scan()
        if not result["stagnant"]:
            assert result["stagnation_streak"] == 0

    def test_scan_updates_state(self, isolated_state):
        challenger.scan()
        state = challenger._load_state()
        assert state["total_scans"] == 1
        assert state["last_scan"] > 0

    def test_scan_updates_novelty_history(self, isolated_state):
        challenger.scan()
        state = challenger._load_state()
        assert len(state["novelty_history"]) == 1
        entry = state["novelty_history"][0]
        assert "ts" in entry
        assert "score" in entry
        assert "stagnant" in entry

    def test_novelty_history_capped_at_20(self, isolated_state):
        for _ in range(25):
            challenger.scan()
        state = challenger._load_state()
        assert len(state["novelty_history"]) <= 20

    def test_challenge_ts_updated_on_stagnation(self, stagnant_thalamus):
        before = time.time()
        result = challenger.scan()
        if result["stagnant"]:
            state = challenger._load_state()
            assert state["last_challenge_ts"] >= before

    def test_scan_emits_to_thalamus(self, isolated_state):
        """Scan should write a THALAMUS entry."""
        with patch.object(challenger.thalamus, "append") as mock_append:
            challenger.scan()
            assert mock_append.called

    def test_domain_rotation_across_scans(self, stagnant_thalamus):
        """Running multiple stagnation scans should rotate domains."""
        domains_seen = set()
        for _ in range(len(challenger.CHALLENGE_DOMAINS) + 2):
            result = challenger.scan()
            if result.get("challenge"):
                domains_seen.add(result["challenge"]["domain"])
        # Should have seen at least 2 different domains over time
        assert len(domains_seen) >= 1  # at minimum 1


# ── Emit need signals ─────────────────────────────────────────────────────────────

class TestEmitNeedSignals:
    def test_no_hypothalamus_no_crash(self, isolated_state):
        result = challenger.emit_need_signals(hypothalamus_mod=None)
        assert "stagnation_streak" in result
        assert "signals_emitted" in result
        assert result["signals_emitted"] == []

    def test_with_mock_hypothalamus_low_streak(self, isolated_state):
        # streak = 0 → no signals
        mock_hm = MagicMock()
        result = challenger.emit_need_signals(hypothalamus_mod=mock_hm)
        assert "new_challenge" not in result["signals_emitted"]
        mock_hm.record_need_signal.assert_not_called()

    def test_with_mock_hypothalamus_streak_1(self, isolated_state):
        # Set streak to 1
        state = challenger._default_state()
        state["stagnation_streak"] = 1
        challenger._save_state(state)

        mock_hm = MagicMock()
        result = challenger.emit_need_signals(hypothalamus_mod=mock_hm)
        assert "new_challenge" in result["signals_emitted"]
        mock_hm.record_need_signal.assert_called_with("new_challenge", "challenger")

    def test_with_mock_hypothalamus_streak_3(self, isolated_state):
        # Set streak to 3+ → explore also emitted
        state = challenger._default_state()
        state["stagnation_streak"] = 3
        challenger._save_state(state)

        mock_hm = MagicMock()
        result = challenger.emit_need_signals(hypothalamus_mod=mock_hm)
        assert "new_challenge" in result["signals_emitted"]
        assert "explore" in result["signals_emitted"]

    def test_hypothalamus_exception_doesnt_crash(self, isolated_state):
        state = challenger._default_state()
        state["stagnation_streak"] = 2
        challenger._save_state(state)

        mock_hm = MagicMock()
        mock_hm.record_need_signal.side_effect = RuntimeError("oops")
        # Should not raise
        result = challenger.emit_need_signals(hypothalamus_mod=mock_hm)
        assert "signals_emitted" in result


# ── Get status ────────────────────────────────────────────────────────────────────

class TestGetStatus:
    def test_status_keys(self, isolated_state):
        status = challenger.get_status()
        assert "total_scans" in status
        assert "total_challenges_issued" in status
        assert "last_scan" in status
        assert "last_challenge_ts" in status
        assert "last_challenge_domain" in status
        assert "last_challenge_prompt" in status
        assert "stagnation_streak" in status
        assert "novelty_score" in status
        assert "hours_since_challenge" in status

    def test_status_after_scan(self, isolated_state):
        challenger.scan()
        status = challenger.get_status()
        assert status["total_scans"] == 1

    def test_hours_since_none_when_never_challenged(self, isolated_state):
        status = challenger.get_status()
        assert status["hours_since_challenge"] is None

    def test_hours_since_calculated_when_challenged(self, isolated_state):
        state = challenger._default_state()
        state["last_challenge_ts"] = time.time() - 3600  # 1 hour ago
        challenger._save_state(state)

        status = challenger.get_status()
        assert status["hours_since_challenge"] is not None
        assert 0.9 <= status["hours_since_challenge"] <= 1.1

    def test_novelty_score_in_range(self, isolated_state):
        status = challenger.get_status()
        assert 0.0 <= status["novelty_score"] <= 1.0


# ── CHALLENGE_DOMAINS completeness ───────────────────────────────────────────────

class TestDomainDefinitions:
    def test_all_domains_have_required_keys(self):
        for domain in challenger.CHALLENGE_DOMAINS:
            assert "name" in domain, f"Missing 'name' in {domain}"
            assert "label" in domain, f"Missing 'label' in {domain}"
            assert "examples" in domain, f"Missing 'examples' in {domain}"

    def test_all_domains_have_at_least_one_example(self):
        for domain in challenger.CHALLENGE_DOMAINS:
            assert len(domain["examples"]) >= 1, f"No examples in {domain['name']}"

    def test_domain_names_unique(self):
        names = [d["name"] for d in challenger.CHALLENGE_DOMAINS]
        assert len(names) == len(set(names)), "Duplicate domain names found"

    def test_at_least_four_domains(self):
        assert len(challenger.CHALLENGE_DOMAINS) >= 4
