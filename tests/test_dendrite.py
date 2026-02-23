"""Tests for DENDRITE — Social Graph."""

import json
from unittest.mock import patch

import pytest

from pulse.src import dendrite, thalamus


@pytest.fixture(autouse=True)
def tmp_state(tmp_path):
    bf = tmp_path / "thalamus.jsonl"
    sf = tmp_path / "dendrite-state.json"
    with patch.object(dendrite, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(dendrite, "_DEFAULT_STATE_FILE", sf), \
         patch.object(thalamus, "_DEFAULT_STATE_DIR", tmp_path), \
         patch.object(thalamus, "_DEFAULT_BROADCAST_FILE", bf):
        yield tmp_path


class TestInteractions:
    def test_record_new_person(self):
        result = dendrite.record_interaction("Alice", valence=0.5)
        assert result["interaction_count"] == 1
        assert result["trust"] > 0.3

    def test_record_existing_person(self):
        dendrite.record_interaction("Alice", valence=0.5)
        result = dendrite.record_interaction("Alice", valence=0.5)
        assert result["interaction_count"] == 2

    def test_negative_interaction_lowers_trust(self):
        initial = dendrite.record_interaction("Bob", valence=0.5)
        result = dendrite.record_interaction("Bob", valence=-0.8)
        assert result["trust"] < initial["trust"]

    def test_josh_is_primary(self):
        primary = dendrite.get_primary()
        assert primary["is_primary"] is True
        assert primary["trust"] == 0.95


class TestSocialGraph:
    def test_get_person(self):
        dendrite.record_interaction("Alice")
        person = dendrite.get_person("Alice")
        assert person is not None

    def test_get_unknown_person(self):
        assert dendrite.get_person("Unknown") is None

    def test_graph_includes_josh(self):
        graph = dendrite.get_social_graph()
        assert "josh" in graph


class TestStatus:
    def test_status(self):
        status = dendrite.get_status()
        assert status["primary"] == "josh"
        assert status["total_people"] >= 1
