"""Tests for GENOME — Exportable DNA Config."""

import json
from unittest.mock import patch

import pytest

from pulse.src import genome, thalamus


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    bf = tmp_path / "thalamus.jsonl"
    sf = tmp_path / "genome.json"
    with patch.object(genome, "STATE_DIR", tmp_path), \
         patch.object(genome, "STATE_FILE", sf), \
         patch.object(thalamus, "STATE_DIR", tmp_path), \
         patch.object(thalamus, "BROADCAST_FILE", bf):
        yield tmp_path


class TestExportImport:
    def test_export(self):
        g = genome.export_genome()
        assert g["version"] == "3.0"
        assert "modules" in g
        assert "endocrine" in g["modules"]

    def test_import(self):
        g = genome.export_genome()
        g["version"] = "3.1"
        genome.import_genome(g)
        exported = genome.export_genome()
        assert exported["version"] == "3.1"

    def test_import_broadcasts(self):
        g = genome.export_genome()
        genome.import_genome(g)
        entries = thalamus.read_by_source("genome")
        assert any(e["type"] == "import" for e in entries)


class TestModuleConfig:
    def test_get_existing(self):
        config = genome.get_module_config("endocrine")
        assert config is not None
        assert "decay_rates" in config

    def test_get_nonexistent(self):
        assert genome.get_module_config("nonexistent") is None


class TestMutation:
    def test_mutate_existing(self):
        result = genome.mutate("endocrine", "high_threshold", 0.6)
        assert result["high_threshold"] == 0.6

    def test_mutate_new_module(self):
        result = genome.mutate("new_module", "setting", 42)
        assert result["setting"] == 42

    def test_mutation_broadcasts(self):
        genome.mutate("endocrine", "test", 1)
        entries = thalamus.read_by_source("genome")
        assert any(e["type"] == "mutation" for e in entries)


class TestStatus:
    def test_status(self):
        status = genome.get_status()
        assert status["version"] == "3.0"
        assert status["modules"] > 0
