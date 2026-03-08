"""CORPUS — Shared ENGRAM memory pool across trusted Pulse peers."""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

from src import engram as _engram
from src import thalamus

logger = logging.getLogger("pulse.corpus")

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state" / "corpus"
_SHAREABLE_FILE = _DEFAULT_STATE_DIR / "shareable.json"
_RECEIVED_FILE = _DEFAULT_STATE_DIR / "received.json"

MAX_RECEIVED_PER_PEER = 100
MAX_SHAREABLE = 200
RECEIVED_MAX_AGE_SECONDS = 60 * 60 * 24 * 30


def _state_file(state_dir: Optional[Path], name: str) -> Path:
    if state_dir:
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir / name
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    return _DEFAULT_STATE_DIR / name


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, type(default)) else default
    except (json.JSONDecodeError, OSError):
        return default


def _save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2))


def mark_shareable(
    engram_id: str,
    tags: Optional[list[str]] = None,
    visibility: str = "trusted",
    state_dir: Optional[Path] = None,
) -> dict:
    if visibility not in ("trusted", "local"):
        raise ValueError("Invalid visibility. Must be 'trusted' or 'local'.")

    store = _engram._load_store()
    src = next((e for e in store if e.get("id") == engram_id), None)
    if not src:
        raise ValueError(f"Engram '{engram_id}' not found in local ENGRAM store.")

    path = _state_file(state_dir, "shareable.json")
    records = _load_json(path, [])

    existing = next((r for r in records if r.get("engram_id") == engram_id), None)
    if existing:
        existing["tags"] = tags or existing.get("tags", [])
        existing["visibility"] = visibility
        existing["updated_at"] = time.time()
        _save_json(path, records)
        return existing

    record = {
        "corpus_id": str(uuid.uuid4()),
        "engram_id": engram_id,
        "event": src.get("event", ""),
        "emotion": src.get("emotion", {}),
        "location": src.get("location", ""),
        "timestamp": src.get("timestamp", time.time() * 1000),
        "tags": tags or [],
        "visibility": visibility,
        "shared_at": time.time(),
        "updated_at": time.time(),
    }

    if len(records) >= MAX_SHAREABLE:
        records.sort(key=lambda r: r.get("shared_at", 0))
        records = records[-(MAX_SHAREABLE - 1):]

    records.append(record)
    _save_json(path, records)

    thalamus.append({
        "source": "CORPUS",
        "event": "engram_shared",
        "engram_id": engram_id,
        "corpus_id": record["corpus_id"],
        "visibility": visibility,
    })
    return record


def unshare(engram_id: str, state_dir: Optional[Path] = None) -> bool:
    path = _state_file(state_dir, "shareable.json")
    records = _load_json(path, [])
    before = len(records)
    records = [r for r in records if r.get("engram_id") != engram_id]
    if len(records) == before:
        return False
    _save_json(path, records)
    thalamus.append({"source": "CORPUS", "event": "engram_unshared", "engram_id": engram_id})
    return True


def get_shareable(visibility_filter: Optional[str] = None, state_dir: Optional[Path] = None) -> list[dict]:
    path = _state_file(state_dir, "shareable.json")
    records = _load_json(path, [])
    if visibility_filter:
        records = [r for r in records if r.get("visibility") == visibility_filter]
    return records


def receive_from_peer(peer_id: str, engrams: list[dict], state_dir: Optional[Path] = None) -> dict:
    if not isinstance(engrams, list):
        raise ValueError("engrams must be a list")

    path = _state_file(state_dir, "received.json")
    received = _load_json(path, {})
    bucket = received.get(peer_id, [])
    existing = {e.get("corpus_id") for e in bucket}

    accepted = rejected = duplicates = 0
    for eng in engrams:
        if not isinstance(eng, dict):
            rejected += 1
            continue
        cid = eng.get("corpus_id")
        if not cid:
            rejected += 1
            continue
        if cid in existing:
            duplicates += 1
            continue
        row = dict(eng)
        row["received_from"] = peer_id
        row["received_at"] = time.time()
        bucket.append(row)
        existing.add(cid)
        accepted += 1

    if len(bucket) > MAX_RECEIVED_PER_PEER:
        bucket.sort(key=lambda r: r.get("received_at", 0))
        bucket = bucket[-MAX_RECEIVED_PER_PEER:]

    received[peer_id] = bucket
    _save_json(path, received)

    summary = {
        "peer_id": peer_id,
        "accepted": accepted,
        "rejected": rejected,
        "duplicates": duplicates,
        "total_from_peer": len(bucket),
    }
    if accepted > 0:
        thalamus.append({"source": "CORPUS", "event": "engrams_received", **summary})
    return summary


def get_received(peer_id: Optional[str] = None, state_dir: Optional[Path] = None) -> dict | list:
    path = _state_file(state_dir, "received.json")
    received = _load_json(path, {})
    if peer_id is not None:
        return received.get(peer_id, [])
    return received


def pull_from_peer(endpoint: str, token: str, peer_id: str, state_dir: Optional[Path] = None) -> dict:
    url = f"{endpoint.rstrip('/')}/pneuma/corpus"
    try:
        req = Request(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="GET",
        )
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        engrams = data if isinstance(data, list) else data.get("engrams", [])
        out = receive_from_peer(peer_id, engrams, state_dir=state_dir)
        out["source_endpoint"] = endpoint
        return out
    except URLError as exc:
        return {"error": str(exc), "source_endpoint": endpoint, "accepted": 0}
    except Exception as exc:  # bad json / schema
        return {"error": f"bad_response: {exc}", "source_endpoint": endpoint, "accepted": 0}


def push_to_peer(
    endpoint: str,
    token: str,
    engram_ids: Optional[list[str]] = None,
    state_dir: Optional[Path] = None,
) -> dict:
    shareable = get_shareable(state_dir=state_dir)
    if engram_ids is not None:
        shareable = [r for r in shareable if r.get("engram_id") in engram_ids]
    if not shareable:
        return {"pushed": 0, "message": "no_shareable_engrams"}

    url = f"{endpoint.rstrip('/')}/corpus/ingest"
    payload = json.dumps({"engrams": shareable}).encode()
    try:
        req = Request(
            url,
            data=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=10) as resp:
            out = json.loads(resp.read().decode())
        out["pushed"] = len(shareable)
        out["target_endpoint"] = endpoint
        thalamus.append({"source": "CORPUS", "event": "engrams_pushed", "count": len(shareable), "target": endpoint})
        return out
    except URLError as exc:
        return {"error": str(exc), "target_endpoint": endpoint, "pushed": 0}
    except Exception as exc:
        return {"error": f"bad_response: {exc}", "target_endpoint": endpoint, "pushed": 0}


def prune_stale_received(max_age_seconds: float = RECEIVED_MAX_AGE_SECONDS, state_dir: Optional[Path] = None) -> dict:
    path = _state_file(state_dir, "received.json")
    received = _load_json(path, {})
    if not received:
        return {}
    cutoff = time.time() - max_age_seconds
    pruned = {}
    for peer, bucket in list(received.items()):
        before = len(bucket)
        keep = [r for r in bucket if r.get("received_at", 0) >= cutoff]
        if len(keep) != before:
            pruned[peer] = before - len(keep)
        received[peer] = keep
    if pruned:
        _save_json(path, received)
    return pruned


def get_status(state_dir: Optional[Path] = None) -> dict:
    shareable = get_shareable(state_dir=state_dir)
    received = get_received(state_dir=state_dir)
    per_peer = {k: len(v) for k, v in received.items()} if isinstance(received, dict) else {}
    return {
        "shareable_count": len(shareable),
        "received_peers": len(per_peer),
        "received_total": sum(per_peer.values()),
        "per_peer": per_peer,
        "state_files": {"shareable": str(_SHAREABLE_FILE), "received": str(_RECEIVED_FILE)},
    }


def should_run(loop_count: int, interval: int = 150) -> bool:
    return loop_count > 0 and loop_count % interval == 0


def update(loop_count: int) -> Optional[dict]:
    if not should_run(loop_count):
        return None
    return {"pruned": prune_stale_received()}
