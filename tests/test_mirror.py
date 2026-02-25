"""Tests for MIRROR v2 — Bidirectional Modeling."""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from pulse.src.mirror import (
    get_josh_model, get_iris_model, update_josh_model,
    check_iris_model_updates, integrate_feedback,
    get_alignment_report, get_relational_state, _load_state, _save_state,
)


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    state_file = tmp_path / "mirror-state.json"
    monkeypatch.setattr("pulse.src.mirror._DEFAULT_STATE_FILE", state_file)
    monkeypatch.setattr("pulse.src.mirror._DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr("pulse.src.mirror.thalamus", MagicMock())

    josh_path = tmp_path / "josh_model.md"
    iris_path = tmp_path / "iris_model.md"
    monkeypatch.setattr("pulse.src.mirror.JOSH_MODEL_PATH", josh_path)
    monkeypatch.setattr("pulse.src.mirror.IRIS_MODEL_PATH", iris_path)

    josh_path.write_text("# Josh Model\n\n## Current state\nFeeling good\n\n## Patterns\nLikes building\n")
    iris_path.write_text("# Iris Model\n\n## What I see in you\nCurious and warm\n\n## Your strengths\nCreative problem solving\n\n## Your blind spots\nSometimes overthinks\n")

    yield tmp_path


class TestGetModels:
    def test_josh_model(self):
        model = get_josh_model()
        assert "Current state" in model
        assert "Feeling good" in model["Current state"]

    def test_iris_model(self):
        model = get_iris_model()
        assert "What I see in you" in model
        assert "Curious" in model["What I see in you"]

    def test_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pulse.src.mirror.JOSH_MODEL_PATH", tmp_path / "nonexistent.md")
        assert get_josh_model() == {}


class TestUpdateJoshModel:
    def test_update_section(self):
        update_josh_model("Current state", "Feeling great!")
        model = get_josh_model()
        assert "Feeling great!" in model["Current state"]


class TestCheckUpdates:
    def test_first_check_detects_content(self):
        changes = check_iris_model_updates()
        assert len(changes) > 0

    def test_no_change_second_check(self):
        check_iris_model_updates()
        changes = check_iris_model_updates()
        assert changes == []

    def test_detects_edit(self, tmp_path, monkeypatch):
        iris_path = monkeypatch.setattr("pulse.src.mirror.IRIS_MODEL_PATH",
                                         tmp_path / "iris_model.md") or (tmp_path / "iris_model.md")
        check_iris_model_updates()
        # Simulate Josh editing
        iris_path.write_text("# Iris Model\n\n## What I see in you\nMore curious than ever\n\n## Your strengths\nAdapting fast\n")
        changes = check_iris_model_updates()
        assert len(changes) > 0

    def test_missing_iris_model(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pulse.src.mirror.IRIS_MODEL_PATH", tmp_path / "gone.md")
        assert check_iris_model_updates() == []


class TestIntegrateFeedback:
    def test_broadcasts_to_thalamus(self):
        import pulse.src.mirror as mirror_mod
        integrate_feedback(["Section 'strengths' updated"])
        mirror_mod.thalamus.append.assert_called_once()
        call_data = mirror_mod.thalamus.append.call_args[0][0]
        assert call_data["source"] == "mirror"

    def test_empty_changes_noop(self):
        import pulse.src.mirror as mirror_mod
        integrate_feedback([])
        mirror_mod.thalamus.append.assert_not_called()


class TestAlignmentReport:
    def test_report_structure(self):
        report = get_alignment_report()
        assert "self_view" in report
        assert "josh_view" in report
        assert report["has_external_feedback"] is True

    def test_josh_view_populated(self):
        report = get_alignment_report()
        assert "Curious" in report["josh_view"]["observations"]


class TestRelationalState:
    def test_state_structure(self):
        state = get_relational_state()
        assert "josh_state" in state
        assert "iris_external_view" in state
        assert state["relationship"]["bidirectional"] is True

    def test_timestamps(self):
        state = get_relational_state()
        assert state["ts"] > 0
