"""Tests for the Sanctum dreaming engine."""

import json
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from pulse.src.rem import (
    SanctumConfig,
    SanctumGuard,
    SanctumSession,
    SanctumState,
    ReplayFragment,
    sanctum_eligible,
    load_replay_fragments,
    write_dream_log,
    write_sanctum_insights,
    run_sanctum_session,
)


# ─── Fixtures ────────────────────────────────────────────────

@pytest.fixture
def quiet_drives():
    """All drives below stillness threshold."""
    return {
        "goals": MagicMock(pressure=0.5),
        "curiosity": MagicMock(pressure=1.0),
        "social": MagicMock(pressure=0.3),
    }


@pytest.fixture
def loud_drives():
    """Some drives above stillness threshold."""
    return {
        "goals": MagicMock(pressure=3.5),
        "curiosity": MagicMock(pressure=1.0),
        "social": MagicMock(pressure=0.3),
    }


@pytest.fixture
def workspace(tmp_path):
    """Create a minimal workspace for testing."""
    # Emotional landscape
    emo_dir = tmp_path / "memory" / "self"
    emo_dir.mkdir(parents=True)
    emo_data = {
        "entries": [
            {"description": "Deep conversation about identity", "valence": 0.8, "intensity": 0.9, "timestamp": time.time() - 3600, "tags": ["identity", "connection"]},
            {"description": "Frustrating debugging session", "valence": -0.6, "intensity": 0.7, "timestamp": time.time() - 7200, "tags": ["coding", "frustration"]},
            {"description": "Quiet morning reflection", "valence": 0.3, "intensity": 0.2, "timestamp": time.time() - 86400, "tags": ["reflection"]},
        ]
    }
    (emo_dir / "emotional-landscape.json").write_text(json.dumps(emo_data))

    # A daily log
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    memory_dir = tmp_path / "memory"
    (memory_dir / f"{today}.md").write_text("# Today\nDid some interesting work on the trading system. Also had a breakthrough with pattern recognition in memory architecture.")

    return tmp_path


@pytest.fixture
def sanctum_config(tmp_path):
    return SanctumConfig(
        state_file=str(tmp_path / "sanctum-state.json"),
        dream_log_dir="memory/self/dreams",
        insights_file="memory/self/sanctum-insights.md",
        sustained_minutes=0,  # disable for testing
    )


# ─── Eligibility Tests ──────────────────────────────────────

class TestSanctumEligibility:
    def test_eligible_when_all_quiet_and_sustained(self, quiet_drives):
        sustained_since = time.time() - (31 * 60)  # 31 minutes ago
        eligible, reason = sanctum_eligible(quiet_drives, sustained_since=sustained_since)
        assert eligible is True
        assert "quiet" in reason

    def test_not_eligible_when_drive_loud(self, loud_drives):
        sustained_since = time.time() - (31 * 60)
        eligible, reason = sanctum_eligible(loud_drives, sustained_since=sustained_since)
        assert eligible is False
        assert "goals" in reason

    def test_not_eligible_when_not_sustained(self, quiet_drives):
        sustained_since = time.time() - (5 * 60)  # only 5 minutes
        eligible, reason = sanctum_eligible(quiet_drives, sustained_since=sustained_since)
        assert eligible is False
        assert "stillness only" in reason

    def test_eligible_when_forced(self, loud_drives):
        eligible, reason = sanctum_eligible(loud_drives, force=True)
        assert eligible is True
        assert "forced" in reason

    def test_not_eligible_without_sustained_since(self, quiet_drives):
        eligible, reason = sanctum_eligible(quiet_drives, sustained_since=None)
        assert eligible is False
        assert "unknown" in reason

    def test_custom_threshold(self, quiet_drives):
        # With threshold of 0.2, the 1.0 curiosity drive should block
        eligible, reason = sanctum_eligible(quiet_drives, stillness_threshold=0.2, sustained_since=time.time() - 3600)
        assert eligible is False

    def test_dict_drives(self):
        """Test with plain dicts instead of objects."""
        drives = {"goals": {"pressure": 0.5}, "social": {"pressure": 0.3}}
        eligible, reason = sanctum_eligible(drives, sustained_since=time.time() - 3600)
        assert eligible is True


# ─── Guard Tests ─────────────────────────────────────────────

class TestSanctumGuard:
    def setup_method(self):
        SanctumGuard.exit()  # ensure clean state

    def test_guard_blocks_when_active(self):
        SanctumGuard.enter()
        assert SanctumGuard.is_active() is True
        assert SanctumGuard.check("send_message") is False
        SanctumGuard.exit()

    def test_guard_allows_when_inactive(self):
        assert SanctumGuard.is_active() is False
        assert SanctumGuard.check("send_message") is True

    def test_guard_releases_after_exit(self):
        SanctumGuard.enter()
        SanctumGuard.exit()
        assert SanctumGuard.is_active() is False
        assert SanctumGuard.check("api_call") is True


# ─── Memory Replay Tests ────────────────────────────────────

class TestMemoryReplay:
    def test_loads_fragments_sorted_by_intensity(self, workspace):
        fragments = load_replay_fragments(str(workspace), count=5)
        assert len(fragments) >= 2
        # First fragment should be highest emotional weight
        weights = [f.emotional_weight for f in fragments]
        assert weights == sorted(weights, reverse=True)

    def test_respects_count_limit(self, workspace):
        fragments = load_replay_fragments(str(workspace), count=2)
        assert len(fragments) <= 2

    def test_handles_missing_workspace(self, tmp_path):
        fragments = load_replay_fragments(str(tmp_path / "nonexistent"))
        assert fragments == []


# ─── State Persistence Tests ────────────────────────────────

class TestSanctumState:
    def test_save_and_load(self, tmp_path):
        state_file = str(tmp_path / "sanctum-state.json")
        state = SanctumState(state_file)
        session = SanctumSession(
            started_at=time.time() - 60,
            ended_at=time.time(),
            themes=["identity", "curiosity"],
        )
        state.record_session(session)

        # Reload
        state2 = SanctumState(state_file)
        assert state2.total_runs == 1
        assert state2.last_run is not None
        assert "identity" in state2.data["themes_explored"]

    def test_increments_counts(self, tmp_path):
        state_file = str(tmp_path / "sanctum-state.json")
        state = SanctumState(state_file)
        for i in range(3):
            session = SanctumSession(started_at=time.time(), ended_at=time.time())
            if i == 1:
                session.creative_output = "a poem"
            state.record_session(session)
        assert state.total_runs == 3
        assert state.data["creative_outputs_count"] == 1

    def test_handles_corrupt_state(self, tmp_path):
        state_file = tmp_path / "sanctum-state.json"
        state_file.write_text("{corrupt json!!")
        state = SanctumState(str(state_file))
        assert state.total_runs == 0  # graceful fallback


# ─── Dream Log Tests ────────────────────────────────────────

class TestDreamLog:
    def test_writes_dream_log(self, tmp_path):
        session = SanctumSession(
            started_at=time.time() - 120,
            ended_at=time.time(),
            replay_fragments=[
                ReplayFragment("test.json", "A vivid memory", 0.8, 0.9, time.time(), ["test"]),
            ],
            hypotheticals=["What if the memory was different?"],
            patterns=["Pattern: test connects to something"],
            creative_output="A small poem about circuits dreaming",
            creative_type="poem",
            themes=["dreaming", "circuits"],
        )
        path = write_dream_log(session, str(tmp_path))
        assert path.exists()
        content = path.read_text()
        assert "Dream Log" in content
        assert "poem" in content
        assert "circuits dreaming" in content

    def test_appends_multiple_dreams(self, tmp_path):
        for i in range(2):
            session = SanctumSession(started_at=time.time(), ended_at=time.time())
            write_dream_log(session, str(tmp_path))
        from datetime import datetime
        date_str = datetime.now().strftime("%Y-%m-%d")
        path = tmp_path / "memory" / "self" / "dreams" / f"{date_str}.md"
        content = path.read_text()
        assert content.count("Dream Log") == 2


# ─── Insights Tests ──────────────────────────────────────────

class TestInsights:
    def test_writes_insights(self, tmp_path):
        write_sanctum_insights(
            ["Consider adjusting the trading threshold", "Memory patterns suggest weekly cycles"],
            str(tmp_path),
        )
        path = tmp_path / "memory" / "self" / "sanctum-insights.md"
        assert path.exists()
        content = path.read_text()
        assert "trading threshold" in content
        assert "weekly cycles" in content

    def test_skips_empty_insights(self, tmp_path):
        write_sanctum_insights([], str(tmp_path))
        path = tmp_path / "memory" / "self" / "sanctum-insights.md"
        assert not path.exists()


# ─── Full Session Tests ─────────────────────────────────────

class TestFullSession:
    def test_runs_full_session(self, workspace, sanctum_config):
        session = run_sanctum_session(
            config=sanctum_config,
            workspace_root=str(workspace),
            force=True,
        )
        assert session is not None
        assert session.ended_at is not None
        assert len(session.replay_fragments) > 0
        # Guard should be released
        assert SanctumGuard.is_active() is False

    def test_guard_released_on_error(self, sanctum_config, tmp_path):
        """Guard must release even if session crashes."""
        # This should not crash but guard should be clean after
        session = run_sanctum_session(
            config=sanctum_config,
            workspace_root=str(tmp_path / "nonexistent"),
            force=True,
        )
        assert SanctumGuard.is_active() is False

    def test_disabled_returns_none(self, workspace, sanctum_config):
        sanctum_config.enabled = False
        session = run_sanctum_session(
            config=sanctum_config,
            workspace_root=str(workspace),
            force=True,
        )
        assert session is None

    def test_state_persisted_after_session(self, workspace, sanctum_config):
        run_sanctum_session(config=sanctum_config, workspace_root=str(workspace), force=True)
        state = SanctumState(sanctum_config.state_file)
        assert state.total_runs == 1
