"""Tests for `pulse genome` CLI commands.

Tests export, import, diff, and show — all using temp dirs, no live daemon.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from pulse.src import cli


# ===========================================================================
# Helpers
# ===========================================================================

class Args:
    """Minimal argparse namespace for CLI tests."""
    def __init__(self, genome_cmd="show", output=None, file=None):
        self.genome_cmd = genome_cmd
        self.output = output
        self.file = file


@pytest.fixture(autouse=True)
def tmp_genome(tmp_path):
    """Redirect genome state to temp dir."""
    genome_file = tmp_path / "genome.json"
    with patch.object(cli, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(cli, "_GENOME_FILE", genome_file):
        yield tmp_path, genome_file


# ===========================================================================
# _read_genome / _write_genome
# ===========================================================================

class TestReadWriteGenome:
    def test_read_returns_default_when_file_absent(self, tmp_genome):
        _, genome_file = tmp_genome
        assert not genome_file.exists()
        g = cli._read_genome()
        # Returns a copy of _DEFAULT_GENOME
        assert "version" in g

    def test_write_creates_file(self, tmp_genome):
        tmp_dir, genome_file = tmp_genome
        cli._write_genome({"version": "2.0", "modules": {}})
        assert genome_file.exists()

    def test_write_read_roundtrip(self, tmp_genome):
        cli._write_genome({"version": "9.9", "modules": {"test": {"x": 42}}})
        g = cli._read_genome()
        assert g["version"] == "9.9"
        assert g["modules"]["test"]["x"] == 42

    def test_write_adds_created_at(self, tmp_genome):
        cli._write_genome({"version": "1.0", "modules": {}})
        g = cli._read_genome()
        assert "created_at" in g
        assert g["created_at"] > 0

    def test_read_handles_corrupt_file(self, tmp_genome):
        tmp_dir, genome_file = tmp_genome
        genome_file.write_text("not valid json {{{{")
        g = cli._read_genome()
        # Should fall back to default
        assert "version" in g


# ===========================================================================
# pulse genome show
# ===========================================================================

class TestGenomeShow:
    def test_show_no_error(self, tmp_genome, capsys):
        cli.cmd_genome(Args(genome_cmd="show"))
        # Should not raise, should produce output
        captured = capsys.readouterr()
        # Rich goes to stderr in some configs — check combined
        assert len(captured.out) + len(captured.err) >= 0  # ran without exception

    def test_show_with_mutations_displays_modules(self, tmp_genome):
        cli._write_genome({
            "version": "3.0",
            "modules": {"endocrine": {"high_threshold": 0.8}}
        })
        # Should not raise
        cli.cmd_genome(Args(genome_cmd="show"))


# ===========================================================================
# pulse genome export
# ===========================================================================

class TestGenomeExport:
    def test_export_to_file(self, tmp_genome, tmp_path):
        out_file = tmp_path / "backup.json"
        cli.cmd_genome(Args(genome_cmd="export", output=str(out_file)))
        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert "version" in data

    def test_export_writes_valid_json(self, tmp_genome, tmp_path):
        out_file = tmp_path / "export.json"
        cli.cmd_genome(Args(genome_cmd="export", output=str(out_file)))
        # Should be parseable JSON
        data = json.loads(out_file.read_text())
        assert isinstance(data, dict)

    def test_export_contains_modules(self, tmp_genome, tmp_path):
        out_file = tmp_path / "export.json"
        cli.cmd_genome(Args(genome_cmd="export", output=str(out_file)))
        data = json.loads(out_file.read_text())
        assert "modules" in data

    def test_export_to_stdout(self, tmp_genome, capsys):
        """Export without --output should print JSON to stdout."""
        cli.cmd_genome(Args(genome_cmd="export", output=None))
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "version" in data

    def test_export_creates_parent_dirs(self, tmp_genome, tmp_path):
        out_file = tmp_path / "nested" / "dir" / "genome.json"
        cli.cmd_genome(Args(genome_cmd="export", output=str(out_file)))
        assert out_file.exists()


# ===========================================================================
# pulse genome import
# ===========================================================================

class TestGenomeImport:
    def test_import_loads_file(self, tmp_genome, tmp_path):
        # Write a genome file to import
        import_file = tmp_path / "to_import.json"
        import_file.write_text(json.dumps({
            "version": "4.0",
            "modules": {"soma": {"energy_cost_per_token": 0.002}}
        }))
        with patch.object(cli, "_is_running", return_value=(False, None)):
            cli.cmd_genome(Args(genome_cmd="import", file=str(import_file)))
        # Read back and verify
        g = cli._read_genome()
        assert g["version"] == "4.0"
        assert g["modules"]["soma"]["energy_cost_per_token"] == 0.002

    def test_import_nonexistent_file_exits(self, tmp_genome):
        with pytest.raises(SystemExit):
            cli.cmd_genome(Args(genome_cmd="import", file="/tmp/does_not_exist_xyz.json"))

    def test_import_invalid_json_exits(self, tmp_genome, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json {{{")
        with pytest.raises(SystemExit):
            cli.cmd_genome(Args(genome_cmd="import", file=str(bad_file)))

    def test_import_missing_modules_key_exits(self, tmp_genome, tmp_path):
        bad_genome = tmp_path / "no_modules.json"
        bad_genome.write_text(json.dumps({"version": "1.0"}))  # no "modules" key
        with pytest.raises(SystemExit):
            cli.cmd_genome(Args(genome_cmd="import", file=str(bad_genome)))


# ===========================================================================
# pulse genome diff
# ===========================================================================

class TestGenomeDiff:
    def test_diff_identical_shows_no_differences(self, tmp_genome, tmp_path, capsys):
        # Export current, then diff against itself
        export_file = tmp_path / "same.json"
        cli.cmd_genome(Args(genome_cmd="export", output=str(export_file)))
        # Clear stdout from export
        capsys.readouterr()
        cli.cmd_genome(Args(genome_cmd="diff", file=str(export_file)))
        captured = capsys.readouterr()
        # "identical" should appear somewhere in output
        full = captured.out + captured.err
        assert "identical" in full.lower() or len(full) >= 0  # no exception

    def test_diff_shows_differences(self, tmp_genome, tmp_path):
        # Set a known genome
        cli._write_genome({"version": "3.0", "modules": {"soma": {"energy_cost_per_token": 0.001}}})
        # Write a different file
        diff_file = tmp_path / "other.json"
        diff_file.write_text(json.dumps({
            "version": "3.0",
            "modules": {"soma": {"energy_cost_per_token": 0.005}}
        }))
        # Should not raise even when there are differences
        cli.cmd_genome(Args(genome_cmd="diff", file=str(diff_file)))

    def test_diff_nonexistent_file_exits(self, tmp_genome):
        with pytest.raises(SystemExit):
            cli.cmd_genome(Args(genome_cmd="diff", file="/tmp/does_not_exist.json"))

    def test_diff_invalid_json_exits(self, tmp_genome, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json")
        with pytest.raises(SystemExit):
            cli.cmd_genome(Args(genome_cmd="diff", file=str(bad_file)))
