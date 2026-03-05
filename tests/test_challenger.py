"""Tests for CHALLENGER — Goal Expansion & Complexity Escalation Engine."""

import json
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


@pytest.fixture
def challenger_module(tmp_path):
    """Import challenger with isolated state directory."""
    from pulse.src import challenger

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    challenger._DEFAULT_STATE_DIR = state_dir
    challenger._DEFAULT_STATE_FILE = state_dir / "challenger-state.json"
    challenger._THALAMUS_FILE = state_dir / "thalamus.jsonl"
    return challenger


@pytest.fixture
def thalamus_mock():
    """Mock thalamus.append to capture broadcasts."""
    with patch("pulse.src.challenger.thalamus") as mock:
        mock.append = MagicMock()
        yield mock


# ── State management ────────────────────────────────────────────────────────────

class TestStateManagement:
    def test_default_state(self, challenger_module):
        state = challenger_module._default_state()
        assert state["total_scans"] == 0
        assert state["total_challenges_issued"] == 0
        assert state["current_tier"] == 2
        assert state["challenge_history"] == []
        assert state["growth_trajectory"] == []

    def test_save_and_load_state(self, challenger_module):
        state = challenger_module._default_state()
        state["total_scans"] = 5
        state["current_tier"] = 3
        challenger_module._save_state(state)

        loaded = challenger_module._load_state()
        assert loaded["total_scans"] == 5
        assert loaded["current_tier"] == 3

    def test_load_corrupt_state_returns_default(self, challenger_module):
        challenger_module._DEFAULT_STATE_FILE.write_text("not valid json{{{")
        state = challenger_module._load_state()
        assert state["total_scans"] == 0

    def test_load_missing_state_returns_default(self, challenger_module):
        state = challenger_module._load_state()
        assert state["total_scans"] == 0

    def test_load_state_fills_missing_keys(self, challenger_module):
        # Save state with only some keys
        partial = {"total_scans": 10}
        challenger_module._DEFAULT_STATE_FILE.write_text(json.dumps(partial))
        loaded = challenger_module._load_state()
        assert loaded["total_scans"] == 10
        assert loaded["current_tier"] == 2  # filled from default


# ── Loop interval ───────────────────────────────────────────────────────────────

class TestShouldRun:
    def test_never_on_zero(self, challenger_module):
        assert not challenger_module.should_run(0)

    def test_runs_on_interval(self, challenger_module):
        assert challenger_module.should_run(60)
        assert challenger_module.should_run(120)
        assert challenger_module.should_run(180)

    def test_skips_off_interval(self, challenger_module):
        assert not challenger_module.should_run(1)
        assert not challenger_module.should_run(30)
        assert not challenger_module.should_run(59)
        assert not challenger_module.should_run(61)


# ── Domain atrophy ──────────────────────────────────────────────────────────────

class TestDomainAtrophy:
    def test_all_domains_atrophied_when_never_challenged(self, challenger_module):
        state = challenger_module._default_state()
        atrophied = challenger_module._detect_atrophied_domains(state)
        assert len(atrophied) == len(challenger_module.ALL_DOMAINS)

    def test_recently_challenged_domain_not_atrophied(self, challenger_module):
        state = challenger_module._default_state()
        state["domain_last_challenged"] = {"engineering": time.time()}
        atrophied = challenger_module._detect_atrophied_domains(state)
        assert "engineering" not in atrophied

    def test_old_challenge_counts_as_atrophied(self, challenger_module):
        state = challenger_module._default_state()
        old_ts = time.time() - (72 * 3600)  # 72 hours ago
        state["domain_last_challenged"] = {"engineering": old_ts}
        atrophied = challenger_module._detect_atrophied_domains(state)
        assert "engineering" in atrophied


# ── Growth trajectory ───────────────────────────────────────────────────────────

class TestGrowthAnalysis:
    def test_insufficient_data(self, challenger_module):
        state = challenger_module._default_state()
        state["growth_trajectory"] = [{"ts": time.time(), "tier": 2}]
        result = challenger_module._analyze_growth(state)
        assert result["trend"] == "insufficient_data"

    def test_flat_trend(self, challenger_module):
        state = challenger_module._default_state()
        state["growth_trajectory"] = [
            {"ts": time.time() - i * 3600, "tier": 3} for i in range(10)
        ]
        result = challenger_module._analyze_growth(state)
        assert result["trend"] == "flat"

    def test_ascending_trend(self, challenger_module):
        state = challenger_module._default_state()
        trajectory = []
        # Older entries: tier 2
        for i in range(5):
            trajectory.append({"ts": time.time() - (10 - i) * 3600, "tier": 2})
        # Recent entries: tier 4
        for i in range(5):
            trajectory.append({"ts": time.time() - (5 - i) * 3600, "tier": 4})
        state["growth_trajectory"] = trajectory
        result = challenger_module._analyze_growth(state)
        assert result["trend"] == "ascending"
        assert result["recent_avg"] > result["older_avg"]

    def test_descending_trend(self, challenger_module):
        state = challenger_module._default_state()
        trajectory = []
        # Older entries: tier 4
        for i in range(5):
            trajectory.append({"ts": time.time() - (10 - i) * 3600, "tier": 4})
        # Recent entries: tier 2
        for i in range(5):
            trajectory.append({"ts": time.time() - (5 - i) * 3600, "tier": 2})
        state["growth_trajectory"] = trajectory
        result = challenger_module._analyze_growth(state)
        assert result["trend"] == "descending"

    def test_empty_trajectory(self, challenger_module):
        state = challenger_module._default_state()
        result = challenger_module._analyze_growth(state)
        assert result["trend"] == "insufficient_data"


# ── Challenge selection ─────────────────────────────────────────────────────────

class TestChallengeSelection:
    def test_returns_valid_challenge(self, challenger_module):
        state = challenger_module._default_state()
        challenge = challenger_module._select_challenge(state)
        assert "domain" in challenge
        assert "tier" in challenge
        assert "prompt" in challenge
        assert challenge["domain"] in challenger_module.ALL_DOMAINS

    def test_prefers_specified_domain(self, challenger_module):
        state = challenger_module._default_state()
        challenge = challenger_module._select_challenge(state, prefer_domain="trading")
        assert challenge["domain"] == "trading"

    def test_rotates_away_from_last_domain(self, challenger_module):
        state = challenger_module._default_state()
        state["last_challenge_domain"] = "engineering"
        # Run 20 times — none should pick engineering (statistically near-certain)
        domains_picked = set()
        for _ in range(20):
            c = challenger_module._select_challenge(state)
            domains_picked.add(c["domain"])
        # At least one non-engineering domain was picked
        assert len(domains_picked - {"engineering"}) > 0

    def test_prefers_atrophied_domains(self, challenger_module):
        state = challenger_module._default_state()
        state["atrophied_domains"] = ["identity"]
        state["last_challenge_domain"] = "engineering"
        # With only one atrophied domain that isn't last, it should prefer it
        challenge = challenger_module._select_challenge(state)
        assert challenge["domain"] == "identity"

    def test_unknown_prefer_domain_falls_through(self, challenger_module):
        state = challenger_module._default_state()
        challenge = challenger_module._select_challenge(state, prefer_domain="nonexistent")
        # Should still return a valid challenge from known domains
        assert challenge["domain"] in challenger_module.ALL_DOMAINS


# ── Tier escalation ─────────────────────────────────────────────────────────────

class TestTierEscalation:
    def test_no_escalation_without_enough_history(self, challenger_module):
        state = challenger_module._default_state()
        state["current_tier"] = 2
        state["challenge_history"] = [{"tier": 2} for _ in range(3)]
        assert not challenger_module._should_escalate(state)

    def test_escalation_with_sufficient_history(self, challenger_module):
        state = challenger_module._default_state()
        state["current_tier"] = 2
        state["challenge_history"] = [{"tier": 2} for _ in range(10)]
        state["growth_trajectory"] = [{"ts": time.time(), "tier": 2} for _ in range(3)]
        state["escalation_cooldown_until"] = 0
        assert challenger_module._should_escalate(state)

    def test_no_escalation_at_max_tier(self, challenger_module):
        state = challenger_module._default_state()
        state["current_tier"] = 5
        state["challenge_history"] = [{"tier": 5} for _ in range(10)]
        assert not challenger_module._should_escalate(state)

    def test_no_escalation_during_cooldown(self, challenger_module):
        state = challenger_module._default_state()
        state["current_tier"] = 2
        state["challenge_history"] = [{"tier": 2} for _ in range(10)]
        state["escalation_cooldown_until"] = time.time() + 3600  # 1 hour from now
        assert not challenger_module._should_escalate(state)


# ── Full scan ───────────────────────────────────────────────────────────────────

class TestScan:
    def test_scan_returns_expected_structure(self, challenger_module, thalamus_mock):
        result = challenger_module.scan()
        assert "challenge" in result
        assert "atrophied_domains" in result
        assert "growth" in result
        assert "tier_escalated" in result
        assert "current_tier" in result

    def test_scan_increments_counters(self, challenger_module, thalamus_mock):
        challenger_module.scan()
        challenger_module.scan()
        status = challenger_module.get_status()
        assert status["total_scans"] == 2
        assert status["total_challenges_issued"] == 2

    def test_scan_broadcasts_to_thalamus(self, challenger_module, thalamus_mock):
        challenger_module.scan()
        assert thalamus_mock.append.called
        call_args = thalamus_mock.append.call_args[0][0]
        assert call_args["source"] == "challenger"
        assert call_args["type"] == "challenge_issued"

    def test_scan_with_prefer_domain(self, challenger_module, thalamus_mock):
        result = challenger_module.scan(prefer_domain="content")
        assert result["challenge"]["domain"] == "content"

    def test_scan_records_history(self, challenger_module, thalamus_mock):
        challenger_module.scan()
        state = challenger_module._load_state()
        assert len(state["challenge_history"]) == 1
        assert len(state["growth_trajectory"]) == 1

    def test_scan_history_capped_at_50(self, challenger_module, thalamus_mock):
        for _ in range(55):
            challenger_module.scan()
        state = challenger_module._load_state()
        assert len(state["challenge_history"]) == 50

    def test_scan_updates_domain_last_challenged(self, challenger_module, thalamus_mock):
        result = challenger_module.scan()
        domain = result["challenge"]["domain"]
        state = challenger_module._load_state()
        assert domain in state["domain_last_challenged"]
        assert state["domain_last_challenged"][domain] > 0


# ── Mark completed ──────────────────────────────────────────────────────────────

class TestMarkCompleted:
    def test_mark_existing_challenge(self, challenger_module, thalamus_mock):
        result = challenger_module.scan()
        domain = result["challenge"]["domain"]
        prompt = result["challenge"]["prompt"]
        assert challenger_module.mark_completed(domain, prompt) is True

    def test_mark_nonexistent_challenge(self, challenger_module):
        assert challenger_module.mark_completed("fake_domain", "fake prompt") is False

    def test_mark_already_completed(self, challenger_module, thalamus_mock):
        result = challenger_module.scan()
        domain = result["challenge"]["domain"]
        prompt = result["challenge"]["prompt"]
        challenger_module.mark_completed(domain, prompt)
        # Second attempt should fail (already completed)
        assert challenger_module.mark_completed(domain, prompt) is False


# ── Emit need signals ───────────────────────────────────────────────────────────

class TestEmitNeedSignals:
    def test_no_crash_without_hypothalamus(self, challenger_module):
        # Should not raise
        challenger_module.emit_need_signals(hypothalamus_mod=None)

    def test_emits_explore_when_many_atrophied(self, challenger_module):
        state = challenger_module._default_state()
        state["atrophied_domains"] = ["engineering", "trading", "content", "business"]
        challenger_module._save_state(state)

        mock_hypo = MagicMock()
        challenger_module.emit_need_signals(hypothalamus_mod=mock_hypo)
        mock_hypo.receive_external_signal.assert_called()

    def test_emits_new_challenge_on_descending_trend(self, challenger_module):
        state = challenger_module._default_state()
        trajectory = []
        for i in range(5):
            trajectory.append({"ts": time.time() - (10 - i) * 3600, "tier": 4})
        for i in range(5):
            trajectory.append({"ts": time.time() - (5 - i) * 3600, "tier": 1})
        state["growth_trajectory"] = trajectory
        challenger_module._save_state(state)

        mock_hypo = MagicMock()
        challenger_module.emit_need_signals(hypothalamus_mod=mock_hypo)
        # Should have called with "new_challenge"
        calls = [c[0][0] for c in mock_hypo.receive_external_signal.call_args_list]
        assert "new_challenge" in calls


# ── Get status ──────────────────────────────────────────────────────────────────

class TestGetStatus:
    def test_status_structure(self, challenger_module):
        status = challenger_module.get_status()
        assert "total_scans" in status
        assert "current_tier" in status
        assert "current_tier_label" in status
        assert "growth" in status
        assert "atrophied_domains" in status

    def test_status_after_scan(self, challenger_module, thalamus_mock):
        challenger_module.scan()
        status = challenger_module.get_status()
        assert status["total_scans"] == 1
        assert status["total_challenges_issued"] == 1
        assert status["last_challenge_domain"] != ""

    def test_status_tracks_completions(self, challenger_module, thalamus_mock):
        result = challenger_module.scan()
        challenger_module.mark_completed(
            result["challenge"]["domain"],
            result["challenge"]["prompt"],
        )
        status = challenger_module.get_status()
        assert status["challenges_completed"] == 1


# ── Difficulty tiers ────────────────────────────────────────────────────────────

class TestDifficultyTiers:
    def test_all_tiers_have_labels(self, challenger_module):
        for tier_num in range(1, 6):
            assert tier_num in challenger_module.DIFFICULTY_TIERS

    def test_all_template_tiers_are_valid(self, challenger_module):
        for domain, templates in challenger_module.CHALLENGE_TEMPLATES.items():
            for t in templates:
                assert 1 <= t["tier"] <= 5, f"Invalid tier {t['tier']} in {domain}"
                assert len(t["prompt"]) > 0, f"Empty prompt in {domain}"

    def test_all_domains_have_templates(self, challenger_module):
        for domain in challenger_module.ALL_DOMAINS:
            assert domain in challenger_module.CHALLENGE_TEMPLATES
            assert len(challenger_module.CHALLENGE_TEMPLATES[domain]) > 0


# ── Integration with NervousSystem ──────────────────────────────────────────────

class TestNervousSystemIntegration:
    def test_module_loads_in_nervous_system(self, tmp_path):
        """Verify CHALLENGER loads in the NervousSystem registry."""
        from pulse.src.nervous_system import NervousSystem
        ns = NervousSystem(state_dir=tmp_path / "state")
        assert ns._mod_challenger is not None

    def test_module_has_required_interface(self, challenger_module):
        """Verify CHALLENGER has all methods the NervousSystem expects."""
        assert callable(challenger_module.should_run)
        assert callable(challenger_module.scan)
        assert callable(challenger_module.emit_need_signals)
        assert callable(challenger_module.get_status)
