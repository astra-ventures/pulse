"""Tests for state persistence — load, save, atomic writes."""

import json
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config import PulseConfig
from src.state.persistence import StatePersistence


class TestStatePersistence:
    """Test state save/load cycle."""

    def _make_persistence(self, tmpdir: str) -> StatePersistence:
        config = PulseConfig()
        config.state.dir = tmpdir
        return StatePersistence(config)

    def test_fresh_state_loads_empty(self):
        with tempfile.TemporaryDirectory() as d:
            sp = self._make_persistence(d)
            sp.load()
            assert sp._data == {}

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            sp = self._make_persistence(d)
            sp.load()
            sp.set("test_key", {"value": 42})
            sp.save()

            sp2 = self._make_persistence(d)
            sp2.load()
            assert sp2.get("test_key") == {"value": 42}

    def test_save_creates_state_file(self):
        with tempfile.TemporaryDirectory() as d:
            sp = self._make_persistence(d)
            sp.load()
            sp.save()
            assert sp.state_file.exists()

    def test_state_file_is_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            sp = self._make_persistence(d)
            sp.load()
            sp.set("hello", "world")
            sp.save()
            data = json.loads(sp.state_file.read_text())
            assert data["hello"] == "world"
            assert "_saved_at" in data

    def test_corrupt_state_file_starts_fresh(self):
        with tempfile.TemporaryDirectory() as d:
            sp = self._make_persistence(d)
            # Write corrupt JSON
            sp.state_file.write_text("{invalid json!!")
            sp.load()
            assert sp._data == {}
