"""DriveEngine source refresh tests.

These tests protect against a regression where the `unfinished` drive would pin
at max pressure because hypotheses with `status: blocked` still have `outcome: null`.
"""

import json
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config import PulseConfig, DriveCategory
from src.state.persistence import StatePersistence
from src.drives.engine import DriveEngine


def _write(p: Path, obj):
    p.write_text(json.dumps(obj, indent=2))


def test_unfinished_spike_ignores_blocked_hypotheses(tmp_path: Path):
    cfg = PulseConfig()
    cfg.workspace.root = str(tmp_path)
    cfg.workspace.hypotheses = "hypotheses.json"
    cfg.drives.categories = {
        "unfinished": DriveCategory(weight=1.0, source="hypotheses")
    }

    state = StatePersistence(cfg)
    engine = DriveEngine(cfg, state)

    hyp_path = tmp_path / "hypotheses.json"
    _write(
        hyp_path,
        [
            {"id": "h1", "status": "blocked", "outcome": None},
            {"id": "h2", "status": "ready_for_approval", "outcome": None},
            {"id": "h3", "status": "untested", "outcome": None},
            {"id": "h4", "status": "testing", "outcome": None},
        ],
    )

    engine.refresh_sources()

    # Only the 2 active statuses should count: untested + testing => 0.04 spike
    assert abs(engine.drives["unfinished"].pressure - 0.04) < 1e-6

    # No further spike if file didn't change
    engine.refresh_sources()
    assert abs(engine.drives["unfinished"].pressure - 0.04) < 1e-6


def test_unfinished_does_not_spike_when_only_blocked(tmp_path: Path):
    cfg = PulseConfig()
    cfg.workspace.root = str(tmp_path)
    cfg.workspace.hypotheses = "hypotheses.json"
    cfg.drives.categories = {
        "unfinished": DriveCategory(weight=1.0, source="hypotheses")
    }

    state = StatePersistence(cfg)
    engine = DriveEngine(cfg, state)

    hyp_path = tmp_path / "hypotheses.json"
    _write(
        hyp_path,
        [
            {"id": "h1", "status": "blocked", "outcome": None},
            {"id": "h2", "status": "ready_for_approval", "outcome": None},
        ],
    )

    engine.refresh_sources()
    assert engine.drives["unfinished"].pressure == 0.0

    # Update file mtime and content; still should not spike.
    time.sleep(0.02)
    _write(
        hyp_path,
        [
            {"id": "h1", "status": "blocked", "outcome": None, "notes": "still blocked"},
        ],
    )
    engine.refresh_sources()
    assert engine.drives["unfinished"].pressure == 0.0
