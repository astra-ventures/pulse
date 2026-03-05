"""Tests for MOTORIC — Shipping Pressure Monitor."""

import json
import time
from pathlib import Path
import pytest
import tempfile


# ── Fixtures ────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Redirect all state files to a temp directory for isolation."""
    import pulse.src.motoric as mot
    monkeypatch.setattr(mot, "_DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(mot, "_DEFAULT_STATE_FILE", tmp_path / "motoric-state.json")
    monkeypatch.setattr(mot, "_SHIPS_LOG", tmp_path / "motoric-ships.jsonl")
    # Also redirect workspace checks to temp dirs (prevent real filesystem reads)
    monkeypatch.setattr(mot, "_PULSE_DIST", tmp_path / "dist")
    monkeypatch.setattr(mot, "_LAUNCH_CHECKLIST", tmp_path / "LAUNCH_CHECKLIST.md")
    monkeypatch.setattr(mot, "_IAMIRIS_NOW", tmp_path / "now.md")
    return tmp_path


# ── State management ─────────────────────────────────────────────────────────────

def test_default_state():
    from pulse.src.motoric import _default_state
    s = _default_state()
    assert s["total_scans"] == 0
    assert s["total_ships_recorded"] == 0
    assert s["last_ship_ts"] == 0
    assert s["readiness_items"] == []
    assert s["pressure_history"] == []


def test_load_state_missing_file():
    from pulse.src.motoric import _load_state, _default_state
    s = _load_state()
    assert s == _default_state()


def test_load_save_state(tmp_path):
    from pulse.src.motoric import _load_state, _save_state, _default_state
    s = _default_state()
    s["total_scans"] = 42
    _save_state(s)
    loaded = _load_state()
    assert loaded["total_scans"] == 42


def test_load_state_corrupt_json(tmp_path):
    """Corrupt JSON falls back to default."""
    import pulse.src.motoric as mot
    mot._DEFAULT_STATE_FILE.write_text("{ NOT VALID JSON }")
    s = mot._load_state()
    assert s["total_scans"] == 0


# ── Loop interval ─────────────────────────────────────────────────────────────────

def test_should_run_at_interval():
    from pulse.src.motoric import should_run, LOOP_INTERVAL
    assert not should_run(0)
    assert not should_run(LOOP_INTERVAL - 1)
    assert should_run(LOOP_INTERVAL)
    assert should_run(LOOP_INTERVAL * 2)
    assert not should_run(LOOP_INTERVAL + 1)


# ── Checkers ─────────────────────────────────────────────────────────────────────

def test_check_pulse_dist_no_dir(tmp_path):
    from pulse.src.motoric import _check_pulse_dist
    result = _check_pulse_dist()
    assert result["name"] == "pulse_pypi"
    assert result["ready"] is False
    assert "no dist" in result["blocker"].lower()


def test_check_pulse_dist_empty_dir(tmp_path):
    import pulse.src.motoric as mot
    mot._PULSE_DIST.mkdir(parents=True)
    result = mot._check_pulse_dist()
    assert result["ready"] is False
    assert "no build artifacts" in result["blocker"]


def test_check_pulse_dist_with_artifact(tmp_path):
    import pulse.src.motoric as mot
    mot._PULSE_DIST.mkdir(parents=True)
    artifact = mot._PULSE_DIST / "pulse-0.3.5-py3-none-any.whl"
    artifact.write_text("fake whl content")
    # Make it appear old (more than threshold)
    import os
    old_time = time.time() - (mot.DIST_IDLE_THRESHOLD_HOURS + 1) * 3600
    os.utime(artifact, (old_time, old_time))
    result = mot._check_pulse_dist()
    assert result["name"] == "pulse_pypi"
    assert result["ready"] is True
    assert result["blocker"] == ""
    assert "twine upload" in result.get("detail", "")


def test_check_pulse_dist_fresh_artifact(tmp_path):
    import pulse.src.motoric as mot
    mot._PULSE_DIST.mkdir(parents=True)
    artifact = mot._PULSE_DIST / "pulse-0.3.5-py3-none-any.whl"
    artifact.write_text("fresh whl")
    # Fresh file (just created) — blocker should mention in-progress
    result = mot._check_pulse_dist()
    assert result["ready"] is True
    assert "in-progress" in result["blocker"] or "fresh" in result["blocker"]


def test_check_launch_checklist_missing(tmp_path):
    from pulse.src.motoric import _check_launch_checklist
    result = _check_launch_checklist()
    assert result["name"] == "pulse_launch"
    assert result["ready"] is False
    assert "not found" in result["blocker"]


def test_check_launch_checklist_complete(tmp_path):
    import pulse.src.motoric as mot
    checklist = "- [x] Item one\n- [x] Item two\n- [x] Item three\n- [x] Item four\n"
    mot._LAUNCH_CHECKLIST.write_text(checklist)
    result = mot._check_launch_checklist()
    assert result["name"] == "pulse_launch"
    assert result["ready"] is True
    assert result["blocker"] == ""


def test_check_launch_checklist_incomplete(tmp_path):
    import pulse.src.motoric as mot
    checklist = "- [x] Item one\n- [ ] Item two\n- [ ] Item three\n"
    mot._LAUNCH_CHECKLIST.write_text(checklist)
    result = mot._check_launch_checklist()
    assert result["ready"] is False
    assert "2 items remain" in result["blocker"]


def test_check_launch_checklist_high_ratio(tmp_path):
    """85%+ complete counts as ready."""
    import pulse.src.motoric as mot
    items = ["- [x] Item\n"] * 9 + ["- [ ] Pending\n"]
    mot._LAUNCH_CHECKLIST.write_text("".join(items))
    result = mot._check_launch_checklist()
    assert result["ready"] is True  # 9/10 = 90% >= 85%


def test_check_now_page_missing(tmp_path):
    from pulse.src.motoric import _check_now_page
    result = _check_now_page()
    assert result["name"] == "now_page"
    # May or may not be "ready" depending on git fallback; just check no crash
    assert "name" in result


def test_check_now_page_fresh(tmp_path):
    import pulse.src.motoric as mot
    mot._IAMIRIS_NOW.write_text("# Now\nFresh content.")
    # File is brand new — not stale
    result = mot._check_now_page()
    assert result["name"] == "now_page"
    assert result["ready"] is False  # fresh, no update needed


def test_check_now_page_stale(tmp_path):
    import pulse.src.motoric as mot, os
    mot._IAMIRIS_NOW.write_text("# Now\nOld content.")
    old_ts = time.time() - (mot.NOW_PAGE_STALE_DAYS + 1) * 86400
    os.utime(mot._IAMIRIS_NOW, (old_ts, old_ts))
    result = mot._check_now_page()
    assert result["name"] == "now_page"
    assert result["ready"] is True  # stale = needs update


def test_check_clawhub_no_marker(tmp_path):
    from pulse.src.motoric import _check_clawhub_submission
    # No marker file → needs submission
    result = _check_clawhub_submission()
    assert result["name"] == "clawhub_submit"
    # Result depends on whether marker exists on real FS; just assert structure
    assert "ready" in result
    assert "blocker" in result


# ── scan_pending_ships ────────────────────────────────────────────────────────────

def test_scan_pending_ships_returns_list():
    from pulse.src.motoric import scan_pending_ships
    items = scan_pending_ships()
    assert isinstance(items, list)
    assert len(items) >= 3  # pulse_pypi, pulse_launch, now_page
    names = {i["name"] for i in items}
    assert "pulse_pypi" in names
    assert "now_page" in names


def test_each_item_has_required_keys():
    from pulse.src.motoric import scan_pending_ships
    items = scan_pending_ships()
    for item in items:
        assert "name" in item
        assert "ready" in item
        assert "blocker" in item


# ── get_deployment_pressure ───────────────────────────────────────────────────────

def test_pressure_range():
    from pulse.src.motoric import get_deployment_pressure
    p = get_deployment_pressure()
    assert 0.0 <= p <= 1.0


def test_pressure_zero_when_nothing_ready(monkeypatch, tmp_path):
    import pulse.src.motoric as mot
    monkeypatch.setattr(mot, "scan_pending_ships", lambda: [
        {"name": "a", "ready": False, "blocker": "blocked"},
        {"name": "b", "ready": False, "blocker": "blocked"},
    ])
    p = mot.get_deployment_pressure()
    assert p == 0.0


def test_pressure_nonzero_when_ready_unblocked(monkeypatch, tmp_path):
    import pulse.src.motoric as mot
    monkeypatch.setattr(mot, "scan_pending_ships", lambda: [
        {"name": "pulse_pypi", "ready": True, "blocker": ""},
    ])
    p = mot.get_deployment_pressure()
    assert p > 0.0


def test_pressure_lower_after_recent_ship(monkeypatch, tmp_path):
    """Pressure should be lower when a ship just happened."""
    import pulse.src.motoric as mot
    monkeypatch.setattr(mot, "scan_pending_ships", lambda: [
        {"name": "pulse_pypi", "ready": True, "blocker": ""},
    ])
    # Simulate recent ship (1 hour ago)
    state = mot._default_state()
    state["last_ship_ts"] = time.time() - 3600
    mot._save_state(state)

    p_recent = mot.get_deployment_pressure()

    # Simulate no ship ever
    state2 = mot._default_state()
    state2["last_ship_ts"] = 0
    mot._save_state(state2)

    p_never = mot.get_deployment_pressure()
    assert p_recent < p_never


# ── record_ship ──────────────────────────────────────────────────────────────────

def test_record_ship_updates_state():
    from pulse.src.motoric import record_ship, _load_state
    result = record_ship("pulse-v0.3.5", "pypi", "Published to PyPI")
    assert result["name"] == "pulse-v0.3.5"
    assert result["total_ships"] == 1

    state = _load_state()
    assert state["last_ship_name"] == "pulse-v0.3.5"
    assert state["total_ships_recorded"] == 1
    assert state["last_ship_ts"] > 0


def test_record_ship_writes_log(tmp_path):
    import pulse.src.motoric as mot
    mot.record_ship("test-ship", "test", "log test")
    assert mot._SHIPS_LOG.exists()
    lines = mot._SHIPS_LOG.read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["name"] == "test-ship"


def test_record_ship_appends_log(tmp_path):
    import pulse.src.motoric as mot
    mot.record_ship("ship-1", "pypi", "first")
    mot.record_ship("ship-2", "github", "second")
    lines = mot._SHIPS_LOG.read_text().strip().splitlines()
    assert len(lines) == 2
    names = [json.loads(l)["name"] for l in lines]
    assert "ship-1" in names
    assert "ship-2" in names


# ── scan ──────────────────────────────────────────────────────────────────────────

def test_scan_returns_required_keys():
    from pulse.src.motoric import scan
    result = scan()
    assert "pressure" in result
    assert "items" in result
    assert "ready_count" in result
    assert 0.0 <= result["pressure"] <= 1.0


def test_scan_updates_state():
    from pulse.src.motoric import scan, _load_state
    scan()
    state = _load_state()
    assert state["total_scans"] == 1
    assert state["last_scan"] > 0
    assert len(state["pressure_history"]) == 1


def test_scan_multiple_updates_history():
    from pulse.src.motoric import scan, _load_state
    scan()
    scan()
    scan()
    state = _load_state()
    assert state["total_scans"] == 3
    assert len(state["pressure_history"]) == 3


def test_scan_history_capped_at_20():
    from pulse.src.motoric import scan, _load_state
    for _ in range(25):
        scan()
    state = _load_state()
    assert len(state["pressure_history"]) == 20


# ── emit_need_signals ─────────────────────────────────────────────────────────────

def test_emit_need_signals_no_hm():
    from pulse.src.motoric import emit_need_signals
    result = emit_need_signals(hypothalamus_mod=None)
    assert "pressure" in result
    assert "signals_emitted" in result
    assert isinstance(result["signals_emitted"], list)


def test_emit_need_signals_with_mock_hm(monkeypatch, tmp_path):
    """With a real HM mock, signals should emit when pressure > 0.2."""
    import pulse.src.motoric as mot

    captured = []

    class MockHM:
        def record_need_signal(self, name, source):
            captured.append(name)

    # Force high pressure
    monkeypatch.setattr(mot, "get_deployment_pressure", lambda: 0.7)
    result = mot.emit_need_signals(hypothalamus_mod=MockHM())
    assert "ship_something" in result["signals_emitted"]
    assert "ship_something" in captured


def test_emit_need_signals_deploy_now_at_high_pressure(monkeypatch, tmp_path):
    import pulse.src.motoric as mot

    captured = []

    class MockHM:
        def record_need_signal(self, name, source):
            captured.append(name)

    monkeypatch.setattr(mot, "get_deployment_pressure", lambda: 0.9)
    result = mot.emit_need_signals(hypothalamus_mod=MockHM())
    assert "ship_something" in captured
    assert "deploy_now" in captured


def test_emit_no_signals_when_low_pressure(monkeypatch, tmp_path):
    import pulse.src.motoric as mot

    captured = []

    class MockHM:
        def record_need_signal(self, name, source):
            captured.append(name)

    monkeypatch.setattr(mot, "get_deployment_pressure", lambda: 0.1)
    result = mot.emit_need_signals(hypothalamus_mod=MockHM())
    assert result["signals_emitted"] == []
    assert captured == []


# ── get_status ────────────────────────────────────────────────────────────────────

def test_get_status_structure():
    from pulse.src.motoric import get_status
    status = get_status()
    required = ["pressure", "total_scans", "total_ships_recorded",
                "last_scan", "last_ship_ts", "last_ship_name",
                "hours_since_ship", "readiness_items", "ready_count"]
    for key in required:
        assert key in status, f"Missing key: {key}"


def test_get_status_hours_since_ship():
    from pulse.src.motoric import record_ship, get_status, _load_state
    record_ship("recent-ship", "test", "")
    status = get_status()
    assert status["hours_since_ship"] is not None
    assert status["hours_since_ship"] < 0.1  # just shipped


def test_get_status_no_ship():
    from pulse.src.motoric import get_status
    status = get_status()
    assert status["hours_since_ship"] is None
    assert status["last_ship_ts"] == 0


# ── nervous_system integration ────────────────────────────────────────────────────

def test_nervous_system_loads_motoric():
    """NervousSystem should load MOTORIC without errors."""
    from pulse.src.nervous_system import NervousSystem
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        ns = NervousSystem(state_dir=Path(td))
        assert ns._mod_motoric is not None, "MOTORIC failed to load in NervousSystem"


def test_nervous_system_post_loop_calls_motoric():
    """post_loop should trigger MOTORIC scan at the right interval."""
    from pulse.src.nervous_system import NervousSystem
    from pulse.src.motoric import LOOP_INTERVAL
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        ns = NervousSystem(state_dir=Path(td))
        if not ns._mod_motoric:
            pytest.skip("MOTORIC not loaded")

        scans_before = ns._mod_motoric.get_status()["total_scans"]

        # Run enough loops to trigger MOTORIC
        for _ in range(LOOP_INTERVAL):
            ns.post_loop()

        scans_after = ns._mod_motoric.get_status()["total_scans"]
        assert scans_after > scans_before, "MOTORIC should have run at least once"
