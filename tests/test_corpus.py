"""Tests for CORPUS — shared memory pool across trusted Pulse peers.

Covers: mark_shareable, unshare, get_shareable, receive_from_peer,
        get_received, prune_stale_received, push_to_peer (network mock),
        pull_from_peer (network mock), get_status, should_run, update.
"""

import json
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import src.corpus as corpus


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_state(tmp_path) -> Path:
    """A fresh temporary state directory for each test."""
    return tmp_path / "corpus"


@pytest.fixture
def sample_engram_id(monkeypatch) -> str:
    """Patch _engram._load_store() so mark_shareable finds a local engram."""
    eid = str(uuid.uuid4())
    sample = {
        "id": eid,
        "event": "Discovered a breakthrough in CORPUS design",
        "emotion": {"valence": 0.85, "intensity": 0.7, "label": "excited"},
        "location": "main_session",
        "timestamp": time.time() * 1000,
        "associations": [],
        "recall_count": 0,
        "last_recalled": None,
    }
    monkeypatch.setattr(corpus._engram, "_load_store", lambda: [sample])
    return eid


@pytest.fixture
def sample_engram_id_2(monkeypatch) -> tuple[str, str]:
    """Two sample engrams in the local store."""
    eid1 = str(uuid.uuid4())
    eid2 = str(uuid.uuid4())
    store = [
        {
            "id": eid1,
            "event": "First memory",
            "emotion": {"valence": 0.5, "intensity": 0.5, "label": "calm"},
            "location": "main_session",
            "timestamp": time.time() * 1000,
            "associations": [],
            "recall_count": 0,
            "last_recalled": None,
        },
        {
            "id": eid2,
            "event": "Second memory",
            "emotion": {"valence": 0.6, "intensity": 0.6, "label": "curious"},
            "location": "cron_session",
            "timestamp": (time.time() + 1) * 1000,
            "associations": [],
            "recall_count": 0,
            "last_recalled": None,
        },
    ]
    monkeypatch.setattr(corpus._engram, "_load_store", lambda: store)
    return eid1, eid2


# ── mark_shareable ────────────────────────────────────────────────────────────

class TestMarkShareable:
    def test_creates_record(self, tmp_state, sample_engram_id, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        record = corpus.mark_shareable(sample_engram_id, state_dir=tmp_state)

        assert record["engram_id"] == sample_engram_id
        assert record["visibility"] == "trusted"
        assert "corpus_id" in record
        assert "shared_at" in record

    def test_tags_stored(self, tmp_state, sample_engram_id, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        record = corpus.mark_shareable(
            sample_engram_id, tags=["insight", "breakthrough"], state_dir=tmp_state
        )
        assert record["tags"] == ["insight", "breakthrough"]

    def test_local_visibility(self, tmp_state, sample_engram_id, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        record = corpus.mark_shareable(
            sample_engram_id, visibility="local", state_dir=tmp_state
        )
        assert record["visibility"] == "local"

    def test_invalid_visibility_raises(self, tmp_state, sample_engram_id, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        with pytest.raises(ValueError, match="Invalid visibility"):
            corpus.mark_shareable(
                sample_engram_id, visibility="public", state_dir=tmp_state
            )

    def test_unknown_engram_raises(self, tmp_state, monkeypatch):
        monkeypatch.setattr(corpus._engram, "_load_store", lambda: [])
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        with pytest.raises(ValueError, match="not found"):
            corpus.mark_shareable("nonexistent-id", state_dir=tmp_state)

    def test_idempotent_update(self, tmp_state, sample_engram_id, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        r1 = corpus.mark_shareable(sample_engram_id, tags=["a"], state_dir=tmp_state)
        r2 = corpus.mark_shareable(sample_engram_id, tags=["b"], state_dir=tmp_state)

        # Second call updates, doesn't duplicate
        records = corpus.get_shareable(state_dir=tmp_state)
        assert len(records) == 1
        assert records[0]["tags"] == ["b"]
        # corpus_id unchanged
        assert records[0]["corpus_id"] == r1["corpus_id"]

    def test_persisted_to_disk(self, tmp_state, sample_engram_id, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        corpus.mark_shareable(sample_engram_id, state_dir=tmp_state)

        shareable_file = tmp_state / "shareable.json"
        assert shareable_file.exists()
        data = json.loads(shareable_file.read_text())
        assert len(data) == 1
        assert data[0]["engram_id"] == sample_engram_id

    def test_evicts_oldest_when_at_cap(self, tmp_state, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)

        # Build cap + 1 engrams
        cap = corpus.MAX_SHAREABLE
        ids = [str(uuid.uuid4()) for _ in range(cap + 1)]
        store = [
            {
                "id": eid,
                "event": f"memory {i}",
                "emotion": {},
                "location": "main_session",
                "timestamp": (time.time() + i) * 1000,
                "associations": [],
                "recall_count": 0,
                "last_recalled": None,
            }
            for i, eid in enumerate(ids)
        ]

        # Pre-fill shareable with cap records
        pre_records = [
            {
                "corpus_id": str(uuid.uuid4()),
                "engram_id": eid,
                "event": "",
                "emotion": {},
                "location": "",
                "timestamp": time.time() * 1000 + i,
                "tags": [],
                "visibility": "trusted",
                "shared_at": time.time() + i,
                "updated_at": time.time() + i,
            }
            for i, eid in enumerate(ids[:cap])
        ]
        shareable_file = tmp_state / "shareable.json"
        tmp_state.mkdir(parents=True, exist_ok=True)
        shareable_file.write_text(json.dumps(pre_records))

        # Mark the (cap+1)th engram shareable — should evict oldest
        last_id = ids[-1]
        monkeypatch.setattr(corpus._engram, "_load_store", lambda: [store[-1]])
        corpus.mark_shareable(last_id, state_dir=tmp_state)

        result = corpus.get_shareable(state_dir=tmp_state)
        assert len(result) == cap
        assert any(r["engram_id"] == last_id for r in result)


# ── unshare ───────────────────────────────────────────────────────────────────

class TestUnshare:
    def test_removes_existing(self, tmp_state, sample_engram_id, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        corpus.mark_shareable(sample_engram_id, state_dir=tmp_state)
        removed = corpus.unshare(sample_engram_id, state_dir=tmp_state)

        assert removed is True
        assert corpus.get_shareable(state_dir=tmp_state) == []

    def test_returns_false_when_not_present(self, tmp_state, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        result = corpus.unshare("ghost-id", state_dir=tmp_state)
        assert result is False

    def test_publishes_thalamus_event(self, tmp_state, sample_engram_id, monkeypatch):
        events = []
        monkeypatch.setattr(
            corpus.thalamus, "append",
            lambda *a, **k: events.append(a),
        )
        corpus.mark_shareable(sample_engram_id, state_dir=tmp_state)
        corpus.unshare(sample_engram_id, state_dir=tmp_state)

        unshare_events = [e for e in events if "unshared" in str(e)]
        assert len(unshare_events) == 1


# ── get_shareable ─────────────────────────────────────────────────────────────

class TestGetShareable:
    def test_returns_empty_when_no_file(self, tmp_state):
        result = corpus.get_shareable(state_dir=tmp_state)
        assert result == []

    def test_visibility_filter(self, tmp_state, sample_engram_id_2, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        eid1, eid2 = sample_engram_id_2

        store = corpus._engram._load_store()
        # mark_shareable calls _load_store internally — already patched

        corpus.mark_shareable(eid1, visibility="trusted", state_dir=tmp_state)
        corpus.mark_shareable(eid2, visibility="local", state_dir=tmp_state)

        trusted = corpus.get_shareable(visibility_filter="trusted", state_dir=tmp_state)
        local = corpus.get_shareable(visibility_filter="local", state_dir=tmp_state)
        all_rec = corpus.get_shareable(state_dir=tmp_state)

        assert len(trusted) == 1
        assert len(local) == 1
        assert len(all_rec) == 2

    def test_handles_corrupt_file(self, tmp_state):
        tmp_state.mkdir(parents=True, exist_ok=True)
        (tmp_state / "shareable.json").write_text("not-json{{")
        result = corpus.get_shareable(state_dir=tmp_state)
        assert result == []

    def test_handles_wrong_type_in_file(self, tmp_state):
        tmp_state.mkdir(parents=True, exist_ok=True)
        (tmp_state / "shareable.json").write_text('{"key": "value"}')
        result = corpus.get_shareable(state_dir=tmp_state)
        assert result == []


# ── receive_from_peer ─────────────────────────────────────────────────────────

class TestReceiveFromPeer:
    def _make_engram(self, idx: int = 0) -> dict:
        return {
            "corpus_id": str(uuid.uuid4()),
            "engram_id": str(uuid.uuid4()),
            "event": f"peer event {idx}",
            "emotion": {"valence": 0.5 + idx * 0.1, "intensity": 0.5, "label": "calm"},
            "location": "main_session",
            "timestamp": time.time() * 1000 + idx,
            "tags": ["peer"],
            "visibility": "trusted",
            "shared_at": time.time() + idx,
            "updated_at": time.time() + idx,
        }

    def test_accepts_valid_engrams(self, tmp_state, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        engrams = [self._make_engram(i) for i in range(5)]
        result = corpus.receive_from_peer("scout", engrams, state_dir=tmp_state)

        assert result["accepted"] == 5
        assert result["rejected"] == 0
        assert result["duplicates"] == 0
        assert result["peer_id"] == "scout"

    def test_deduplicates(self, tmp_state, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        e = self._make_engram(0)
        corpus.receive_from_peer("scout", [e], state_dir=tmp_state)
        result = corpus.receive_from_peer("scout", [e], state_dir=tmp_state)

        assert result["accepted"] == 0
        assert result["duplicates"] == 1

    def test_rejects_non_dict(self, tmp_state, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        result = corpus.receive_from_peer("scout", ["not_a_dict", 42], state_dir=tmp_state)
        assert result["rejected"] == 2
        assert result["accepted"] == 0

    def test_rejects_missing_corpus_id(self, tmp_state, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        bad = {"engram_id": str(uuid.uuid4()), "event": "no corpus_id"}
        result = corpus.receive_from_peer("scout", [bad], state_dir=tmp_state)
        assert result["rejected"] == 1

    def test_raises_on_non_list(self, tmp_state):
        with pytest.raises(ValueError, match="must be a list"):
            corpus.receive_from_peer("scout", "not-a-list", state_dir=tmp_state)

    def test_multiple_peers_stored_separately(self, tmp_state, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        eng_a = self._make_engram(0)
        eng_b = self._make_engram(1)

        corpus.receive_from_peer("peer_a", [eng_a], state_dir=tmp_state)
        corpus.receive_from_peer("peer_b", [eng_b], state_dir=tmp_state)

        received = corpus.get_received(state_dir=tmp_state)
        assert "peer_a" in received
        assert "peer_b" in received
        assert len(received["peer_a"]) == 1
        assert len(received["peer_b"]) == 1

    def test_per_peer_cap_enforced(self, tmp_state, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        cap = corpus.MAX_RECEIVED_PER_PEER
        # Fill exactly at cap
        engrams = [self._make_engram(i) for i in range(cap + 10)]
        corpus.receive_from_peer("greedy_peer", engrams, state_dir=tmp_state)

        received = corpus.get_received("greedy_peer", state_dir=tmp_state)
        assert len(received) == cap

    def test_annotates_received_metadata(self, tmp_state, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        e = self._make_engram(0)
        corpus.receive_from_peer("scout", [e], state_dir=tmp_state)

        stored = corpus.get_received("scout", state_dir=tmp_state)
        assert len(stored) == 1
        assert stored[0]["received_from"] == "scout"
        assert "received_at" in stored[0]


# ── get_received ──────────────────────────────────────────────────────────────

class TestGetReceived:
    def test_returns_empty_dict_when_no_file(self, tmp_state):
        result = corpus.get_received(state_dir=tmp_state)
        assert result == {}

    def test_returns_list_for_specific_peer(self, tmp_state, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        e = {
            "corpus_id": str(uuid.uuid4()),
            "engram_id": str(uuid.uuid4()),
            "event": "something",
            "emotion": {},
            "location": "main_session",
            "timestamp": time.time() * 1000,
            "tags": [],
            "visibility": "trusted",
            "shared_at": time.time(),
            "updated_at": time.time(),
        }
        corpus.receive_from_peer("forge", [e], state_dir=tmp_state)

        result = corpus.get_received("forge", state_dir=tmp_state)
        assert isinstance(result, list)
        assert len(result) == 1

    def test_returns_empty_list_for_unknown_peer(self, tmp_state):
        result = corpus.get_received("nonexistent", state_dir=tmp_state)
        assert result == []

    def test_handles_corrupt_received_file(self, tmp_state):
        tmp_state.mkdir(parents=True, exist_ok=True)
        (tmp_state / "received.json").write_text("{{corrupt")
        result = corpus.get_received(state_dir=tmp_state)
        assert result == {}


# ── prune_stale_received ──────────────────────────────────────────────────────

class TestPruneStaleReceived:
    def test_prunes_old_entries(self, tmp_state, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)

        old_entry = {
            "corpus_id": str(uuid.uuid4()),
            "engram_id": str(uuid.uuid4()),
            "event": "old",
            "received_from": "scout",
            "received_at": time.time() - 40 * 86400,  # 40 days ago
        }
        recent_entry = {
            "corpus_id": str(uuid.uuid4()),
            "engram_id": str(uuid.uuid4()),
            "event": "recent",
            "received_from": "scout",
            "received_at": time.time() - 1,  # 1 second ago
        }

        tmp_state.mkdir(parents=True, exist_ok=True)
        (tmp_state / "received.json").write_text(
            json.dumps({"scout": [old_entry, recent_entry]})
        )

        pruned = corpus.prune_stale_received(max_age_seconds=30 * 86400, state_dir=tmp_state)

        assert pruned.get("scout") == 1

        remaining = corpus.get_received("scout", state_dir=tmp_state)
        assert len(remaining) == 1
        assert remaining[0]["event"] == "recent"

    def test_returns_empty_when_nothing_to_prune(self, tmp_state, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        result = corpus.prune_stale_received(state_dir=tmp_state)
        assert result == {}

    def test_no_op_when_file_missing(self, tmp_state):
        result = corpus.prune_stale_received(state_dir=tmp_state)
        assert result == {}


# ── push_to_peer (mocked network) ────────────────────────────────────────────

class TestPushToPeer:
    def test_returns_no_shareable_when_empty(self, tmp_state):
        result = corpus.push_to_peer(
            "http://localhost:9721", "token", state_dir=tmp_state
        )
        assert result["pushed"] == 0
        assert "no_shareable_engrams" in result["message"]

    def test_pushes_and_returns_peer_response(self, tmp_state, sample_engram_id, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        corpus.mark_shareable(sample_engram_id, state_dir=tmp_state)

        mock_response_body = json.dumps({"accepted": 1}).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("src.corpus.urlopen", return_value=mock_resp):
            result = corpus.push_to_peer(
                "http://peer:9720", "tok", state_dir=tmp_state
            )

        assert result["pushed"] == 1
        assert result.get("accepted") == 1

    def test_filters_by_engram_ids(self, tmp_state, sample_engram_id_2, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        eid1, eid2 = sample_engram_id_2
        corpus.mark_shareable(eid1, state_dir=tmp_state)
        corpus.mark_shareable(eid2, state_dir=tmp_state)

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"accepted": 1}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        captured_payload = {}

        def mock_urlopen(req, timeout=10):
            body = req.data
            captured_payload["body"] = json.loads(body.decode())
            return mock_resp

        with patch("src.corpus.urlopen", side_effect=mock_urlopen):
            corpus.push_to_peer(
                "http://peer:9720", "tok",
                engram_ids=[eid1],
                state_dir=tmp_state
            )

        sent = captured_payload["body"]["engrams"]
        assert len(sent) == 1
        assert sent[0]["engram_id"] == eid1

    def test_handles_network_error(self, tmp_state, sample_engram_id, monkeypatch):
        from urllib.error import URLError
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        corpus.mark_shareable(sample_engram_id, state_dir=tmp_state)

        with patch("src.corpus.urlopen", side_effect=URLError("refused")):
            result = corpus.push_to_peer(
                "http://dead:9720", "tok", state_dir=tmp_state
            )

        assert "error" in result
        assert result["pushed"] == 0


# ── pull_from_peer (mocked network) ──────────────────────────────────────────

class TestPullFromPeer:
    def _make_shareable_record(self, idx: int = 0) -> dict:
        return {
            "corpus_id": str(uuid.uuid4()),
            "engram_id": str(uuid.uuid4()),
            "event": f"peer shareable {idx}",
            "emotion": {"valence": 0.6, "intensity": 0.5, "label": "calm"},
            "location": "main_session",
            "timestamp": time.time() * 1000 + idx,
            "tags": ["remote"],
            "visibility": "trusted",
            "shared_at": time.time() + idx,
            "updated_at": time.time() + idx,
        }

    def test_pulls_and_ingests(self, tmp_state, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        remote = [self._make_shareable_record(i) for i in range(3)]

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(remote).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("src.corpus.urlopen", return_value=mock_resp):
            result = corpus.pull_from_peer(
                "http://peer:9720", "tok", "scout", state_dir=tmp_state
            )

        assert result["accepted"] == 3
        assert result["source_endpoint"] == "http://peer:9720"

    def test_handles_list_or_wrapped_response(self, tmp_state, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        remote = [self._make_shareable_record()]

        # Test with {"engrams": [...]} wrapper
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"engrams": remote}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("src.corpus.urlopen", return_value=mock_resp):
            result = corpus.pull_from_peer(
                "http://peer:9720", "tok", "scout", state_dir=tmp_state
            )

        assert result["accepted"] == 1

    def test_handles_network_error(self, tmp_state):
        from urllib.error import URLError
        with patch("src.corpus.urlopen", side_effect=URLError("refused")):
            result = corpus.pull_from_peer(
                "http://dead:9720", "tok", "scout", state_dir=tmp_state
            )

        assert "error" in result
        assert result["accepted"] == 0

    def test_handles_bad_json(self, tmp_state, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("src.corpus.urlopen", return_value=mock_resp):
            result = corpus.pull_from_peer(
                "http://peer:9720", "tok", "scout", state_dir=tmp_state
            )

        assert "error" in result
        assert result["accepted"] == 0


# ── get_status ────────────────────────────────────────────────────────────────

class TestGetStatus:
    def test_empty_state(self, tmp_state):
        status = corpus.get_status(state_dir=tmp_state)
        assert status["shareable_count"] == 0
        assert status["received_peers"] == 0
        assert status["received_total"] == 0

    def test_counts_correctly(self, tmp_state, sample_engram_id, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)
        corpus.mark_shareable(sample_engram_id, state_dir=tmp_state)

        e = {
            "corpus_id": str(uuid.uuid4()),
            "engram_id": str(uuid.uuid4()),
            "event": "remote",
            "emotion": {},
            "location": "main_session",
            "timestamp": time.time() * 1000,
            "tags": [],
            "visibility": "trusted",
            "shared_at": time.time(),
            "updated_at": time.time(),
        }
        corpus.receive_from_peer("scout", [e], state_dir=tmp_state)

        status = corpus.get_status(state_dir=tmp_state)
        assert status["shareable_count"] == 1
        assert status["received_peers"] == 1
        assert status["received_total"] == 1


# ── should_run / update ───────────────────────────────────────────────────────

class TestShouldRun:
    def test_fires_on_interval(self):
        assert corpus.should_run(150) is True
        assert corpus.should_run(300) is True

    def test_does_not_fire_on_zero(self):
        assert corpus.should_run(0) is False

    def test_does_not_fire_between_intervals(self):
        assert corpus.should_run(1) is False
        assert corpus.should_run(149) is False
        assert corpus.should_run(151) is False

    def test_custom_interval(self):
        assert corpus.should_run(50, interval=50) is True
        assert corpus.should_run(100, interval=50) is True
        assert corpus.should_run(51, interval=50) is False


class TestUpdate:
    def test_returns_none_off_cycle(self, tmp_state):
        result = corpus.update(1)
        assert result is None

    def test_returns_pruned_dict_on_cycle(self, tmp_state, monkeypatch):
        # Patch prune_stale_received to avoid real file I/O
        monkeypatch.setattr(corpus, "prune_stale_received", lambda: {})
        result = corpus.update(150)
        assert result is not None
        assert "pruned" in result


# ── Integration: mark → get → unshare ────────────────────────────────────────

class TestIntegration:
    def test_full_share_lifecycle(self, tmp_state, sample_engram_id, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)

        # Share
        record = corpus.mark_shareable(
            sample_engram_id, tags=["key"], visibility="trusted", state_dir=tmp_state
        )
        assert record["engram_id"] == sample_engram_id

        # Read back
        shareable = corpus.get_shareable(state_dir=tmp_state)
        assert len(shareable) == 1
        assert shareable[0]["tags"] == ["key"]

        # Unshare
        removed = corpus.unshare(sample_engram_id, state_dir=tmp_state)
        assert removed is True

        # Gone
        shareable = corpus.get_shareable(state_dir=tmp_state)
        assert shareable == []

    def test_receive_then_query_by_peer(self, tmp_state, monkeypatch):
        monkeypatch.setattr(corpus.thalamus, "append", lambda *a, **k: None)

        engrams = [
            {
                "corpus_id": str(uuid.uuid4()),
                "engram_id": str(uuid.uuid4()),
                "event": f"e{i}",
                "emotion": {},
                "location": "main_session",
                "timestamp": time.time() * 1000 + i,
                "tags": [],
                "visibility": "trusted",
                "shared_at": time.time(),
                "updated_at": time.time(),
            }
            for i in range(4)
        ]
        corpus.receive_from_peer("forge", engrams[:2], state_dir=tmp_state)
        corpus.receive_from_peer("scout", engrams[2:], state_dir=tmp_state)

        forge_received = corpus.get_received("forge", state_dir=tmp_state)
        scout_received = corpus.get_received("scout", state_dir=tmp_state)
        all_received = corpus.get_received(state_dir=tmp_state)

        assert len(forge_received) == 2
        assert len(scout_received) == 2
        assert set(all_received.keys()) == {"forge", "scout"}
