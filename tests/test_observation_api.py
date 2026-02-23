"""Tests for Pulse Observation API (pulse.src.observation_api)."""

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

# fastapi is an optional dependency (pip install pulse-agent[observation])
# Skip this entire module if it isn't installed rather than error.
fastapi = pytest.importorskip("fastapi", reason="fastapi not installed; run: pip install 'pulse-agent[observation]'")
from fastapi.testclient import TestClient


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def state_dir(tmp_path):
    """Temporary state directory pre-populated with sample state files."""
    # drive-performance.json
    (tmp_path / "drive-performance.json").write_text(json.dumps({
        "drives": {"curiosity": 1.8, "goals": 2.1, "connection": 0.9, "autonomy": 1.4}
    }))
    # endocrine-state.json
    (tmp_path / "endocrine-state.json").write_text(json.dumps({
        "hormones": {"cortisol": 0.22, "dopamine": 0.65, "serotonin": 0.78,
                     "oxytocin": 0.40, "adrenaline": 0.08, "melatonin": 0.12}
    }))
    # limbic-state.json
    (tmp_path / "limbic-state.json").write_text(json.dumps({
        "current_valence": 0.4, "current_intensity": 0.6,
        "current_emotion": "curious", "active_pattern": "exploration",
        "recent_memories": [{"event": "built the 3D Internet moon", "valence": 0.8}],
    }))
    # circadian-state.json
    (tmp_path / "circadian-state.json").write_text(json.dumps({
        "energy_level": 0.55, "sleep_phase": "late-night",
        "peak_energy_hour": 14, "is_resting": False, "sleep_quality_avg": 0.72,
    }))
    # soma-state.json
    (tmp_path / "soma-state.json").write_text(json.dumps({
        "energy": 0.65, "strain": 0.12, "readiness": 0.78
    }))
    # chronicle.jsonl
    events = [
        {"timestamp": time.time() - i * 60, "level": "info", "message": f"Event {i}"}
        for i in range(25)
    ]
    (tmp_path / "chronicle.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    # engram-store.json
    (tmp_path / "engram-store.json").write_text(json.dumps({
        "engrams": [
            {"id": "e1", "content": "built the moon at 1 AM", "importance": 0.9},
            {"id": "e2", "content": "Pulse v0.3.0 planning", "importance": 0.8},
            {"id": "e3", "content": "unrelated entry", "importance": 0.3},
        ]
    }))
    return tmp_path


@pytest.fixture()
def client(state_dir, monkeypatch):
    """TestClient with state dir pointed at temp dir, no auth token."""
    monkeypatch.setenv("PULSE_STATE_DIR", str(state_dir))
    monkeypatch.setenv("PULSE_OBS_TOKEN", "")

    # Re-import app after env patch to pick up new STATE_DIR
    import importlib
    import pulse.src.observation_api as obs_mod
    importlib.reload(obs_mod)

    return TestClient(obs_mod.app)


@pytest.fixture()
def auth_client(state_dir, monkeypatch):
    """TestClient with auth token required."""
    monkeypatch.setenv("PULSE_STATE_DIR", str(state_dir))
    monkeypatch.setenv("PULSE_OBS_TOKEN", "test-token-123")

    import importlib
    import pulse.src.observation_api as obs_mod
    importlib.reload(obs_mod)

    return TestClient(obs_mod.app)


# ── /health ───────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert "status" in data
        assert "daemon_alive" in data
        assert "timestamp" in data

    def test_health_daemon_alive_fresh_files(self, client):
        r = client.get("/health")
        data = r.json()
        # Files were just created → should be fresh
        assert data["daemon_alive"] is True
        assert data["status"] == "ok"

    def test_health_stale_files(self, state_dir, monkeypatch):
        """Files older than 5 min → daemon_alive=False."""
        import importlib
        monkeypatch.setenv("PULSE_STATE_DIR", str(state_dir))
        monkeypatch.setenv("PULSE_OBS_TOKEN", "")
        # Age the drive file
        drive_file = state_dir / "drive-performance.json"
        old_time = time.time() - 400
        os.utime(drive_file, (old_time, old_time))

        import pulse.src.observation_api as obs_mod
        importlib.reload(obs_mod)
        c = TestClient(obs_mod.app)
        r = c.get("/health")
        assert r.json()["daemon_alive"] is False

    def test_health_includes_state_dir(self, client):
        data = client.get("/health").json()
        assert "state_dir" in data


# ── /state ────────────────────────────────────────────────────────────────────

class TestFullState:
    def test_state_ok(self, client):
        r = client.get("/state")
        assert r.status_code == 200

    def test_state_has_all_subsystems(self, client):
        data = client.get("/state").json()
        assert "drives" in data
        assert "emotional" in data
        assert "endocrine" in data
        assert "circadian" in data
        assert "soma" in data
        assert "timestamp" in data


# ── /state/drives ─────────────────────────────────────────────────────────────

class TestDrives:
    def test_drives_ok(self, client):
        r = client.get("/state/drives")
        assert r.status_code == 200

    def test_drives_values(self, client):
        data = client.get("/state/drives").json()
        assert "values" in data
        vals = data["values"]
        assert "curiosity" in vals or len(vals) > 0

    def test_drives_pressure(self, client):
        data = client.get("/state/drives").json()
        assert "pressure" in data
        assert isinstance(data["pressure"], float)

    def test_drives_pressure_sum(self, client):
        data = client.get("/state/drives").json()
        vals = data["values"]
        expected = sum(v for v in vals.values() if isinstance(v, (int, float)))
        assert abs(data["pressure"] - round(expected, 3)) < 0.001

    def test_drives_missing_file(self, tmp_path, monkeypatch):
        """Empty state dir returns empty drives without crashing."""
        import importlib
        monkeypatch.setenv("PULSE_STATE_DIR", str(tmp_path))
        monkeypatch.setenv("PULSE_OBS_TOKEN", "")
        import pulse.src.observation_api as obs_mod
        importlib.reload(obs_mod)
        c = TestClient(obs_mod.app)
        r = c.get("/state/drives")
        assert r.status_code == 200


# ── /state/emotional ──────────────────────────────────────────────────────────

class TestEmotional:
    def test_emotional_ok(self, client):
        r = client.get("/state/emotional")
        assert r.status_code == 200

    def test_emotional_fields(self, client):
        data = client.get("/state/emotional").json()
        assert "valence" in data
        assert "intensity" in data
        assert "active_emotion" in data

    def test_emotional_valence_value(self, client):
        data = client.get("/state/emotional").json()
        assert data["valence"] == 0.4

    def test_emotional_emotion(self, client):
        data = client.get("/state/emotional").json()
        assert data["active_emotion"] == "curious"

    def test_emotional_pattern(self, client):
        data = client.get("/state/emotional").json()
        assert data["recent_pattern"] == "exploration"


# ── /state/endocrine ──────────────────────────────────────────────────────────

class TestEndocrine:
    def test_endocrine_ok(self, client):
        r = client.get("/state/endocrine")
        assert r.status_code == 200

    def test_endocrine_all_hormones(self, client):
        data = client.get("/state/endocrine").json()
        for h in ("cortisol", "dopamine", "serotonin", "oxytocin", "adrenaline", "melatonin"):
            assert h in data, f"Missing hormone: {h}"

    def test_endocrine_values_rounded(self, client):
        data = client.get("/state/endocrine").json()
        # All values should be floats with at most 4 decimal places
        for h, v in data.items():
            if h == "timestamp":
                continue
            assert isinstance(v, float)
            assert round(v, 4) == v

    def test_endocrine_dopamine_value(self, client):
        data = client.get("/state/endocrine").json()
        assert abs(data["dopamine"] - 0.65) < 0.001


# ── /state/circadian ─────────────────────────────────────────────────────────

class TestCircadian:
    def test_circadian_ok(self, client):
        r = client.get("/state/circadian")
        assert r.status_code == 200

    def test_circadian_fields(self, client):
        data = client.get("/state/circadian").json()
        assert "energy_level" in data
        assert "sleep_phase" in data
        assert "is_resting" in data

    def test_circadian_phase(self, client):
        data = client.get("/state/circadian").json()
        assert data["sleep_phase"] == "late-night"


# ── /state/soma ──────────────────────────────────────────────────────────────

class TestSoma:
    def test_soma_ok(self, client):
        r = client.get("/state/soma")
        assert r.status_code == 200

    def test_soma_fields(self, client):
        data = client.get("/state/soma").json()
        assert "energy" in data
        assert "strain" in data
        assert "readiness" in data

    def test_soma_values(self, client):
        data = client.get("/state/soma").json()
        assert abs(data["energy"] - 0.65) < 0.001
        assert abs(data["strain"] - 0.12) < 0.001


# ── /chronicle/recent ────────────────────────────────────────────────────────

class TestChronicle:
    def test_chronicle_ok(self, client):
        r = client.get("/chronicle/recent")
        assert r.status_code == 200

    def test_chronicle_default_limit(self, client):
        data = client.get("/chronicle/recent").json()
        assert len(data["events"]) <= 20

    def test_chronicle_custom_limit(self, client):
        data = client.get("/chronicle/recent?n=5").json()
        assert len(data["events"]) <= 5

    def test_chronicle_has_count(self, client):
        data = client.get("/chronicle/recent").json()
        assert "count" in data
        assert data["count"] == len(data["events"])

    def test_chronicle_events_are_dicts(self, client):
        data = client.get("/chronicle/recent").json()
        for e in data["events"]:
            assert isinstance(e, dict)

    def test_chronicle_empty_file(self, tmp_path, monkeypatch):
        import importlib
        monkeypatch.setenv("PULSE_STATE_DIR", str(tmp_path))
        monkeypatch.setenv("PULSE_OBS_TOKEN", "")
        import pulse.src.observation_api as obs_mod
        importlib.reload(obs_mod)
        c = TestClient(obs_mod.app)
        r = c.get("/chronicle/recent")
        assert r.status_code == 200
        assert r.json()["events"] == []


# ── /engram/search ────────────────────────────────────────────────────────────

class TestEngramSearch:
    def test_search_ok(self, client):
        r = client.get("/engram/search?q=moon")
        assert r.status_code == 200

    def test_search_finds_match(self, client):
        data = client.get("/engram/search?q=moon").json()
        assert data["count"] >= 1
        assert any("moon" in json.dumps(e).lower() for e in data["results"])

    def test_search_no_results(self, client):
        data = client.get("/engram/search?q=xyzzy123notfound").json()
        assert data["count"] == 0
        assert data["results"] == []

    def test_search_limit(self, client):
        data = client.get("/engram/search?q=e&limit=1").json()
        assert len(data["results"]) <= 1

    def test_search_returns_query(self, client):
        data = client.get("/engram/search?q=pulse").json()
        assert data["query"] == "pulse"

    def test_search_missing_q(self, client):
        r = client.get("/engram/search")
        assert r.status_code == 422  # FastAPI validation error


# ── Auth ──────────────────────────────────────────────────────────────────────

class TestAuth:
    def test_no_auth_required_when_no_token_set(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_auth_required_when_token_set(self, auth_client):
        r = auth_client.get("/health")
        assert r.status_code == 401

    def test_auth_accepted_with_correct_token(self, auth_client):
        r = auth_client.get("/health", headers={"Authorization": "Bearer test-token-123"})
        assert r.status_code == 200

    def test_auth_rejected_with_wrong_token(self, auth_client):
        r = auth_client.get("/health", headers={"Authorization": "Bearer wrong-token"})
        assert r.status_code == 401

    def test_auth_rejected_with_empty_header(self, auth_client):
        r = auth_client.get("/health", headers={"Authorization": ""})
        assert r.status_code == 401


# ── /dashboard ────────────────────────────────────────────────────────────────

class TestDashboard:
    def test_dashboard_ok(self, client):
        r = client.get("/dashboard")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_dashboard_has_pulse(self, client):
        r = client.get("/dashboard")
        assert "Pulse" in r.text

    def test_dashboard_has_websocket_connect(self, client):
        r = client.get("/dashboard")
        assert "/stream" in r.text

    def test_dashboard_no_auth(self, auth_client):
        """Dashboard is always accessible — token passed via query param."""
        r = auth_client.get("/dashboard")
        assert r.status_code == 200
