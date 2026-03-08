"""CORTEX_EXT — Active Learning / Knowledge Gap Identification.

This module is intentionally lightweight.

Goal:
- Observe recurring failure patterns in THALAMUS (errors, warnings, failed checks)
- Turn them into explicit "learning gaps" that the system can resolve later
  via research, new tests, docs, or new modules.

It does *not* attempt to browse the web or execute fixes directly.
It only:
- Maintains a small state file (gaps + history)
- Emits salient discoveries to THALAMUS so other systems (HYPOTHALAMUS/GERMINAL)
  can pick them up.

State file: ~/.pulse/state/cortexext-state.json
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pulse.src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "cortexext-state.json"

# Run interval for daemon loop hook (in NervousSystem.post_loop)
LOOP_INTERVAL = 150

# If a gap is observed this many times, re-emit at higher salience.
ESCALATION_COUNT = 3


def _default_state() -> dict:
    return {
        "total_scans": 0,
        "last_run": 0,
        "last_loop": 0,
        "gaps": [],  # list[{id, topic, first_seen, last_seen, count, examples:[] }]
        "history": [],  # last 20 scan summaries
    }


def _load_state() -> dict:
    if _DEFAULT_STATE_FILE.exists():
        try:
            data = json.loads(_DEFAULT_STATE_FILE.read_text())
            # minimal shape validation
            if not isinstance(data, dict):
                raise ValueError("state not dict")
            if "gaps" not in data:
                data["gaps"] = []
            if "history" not in data:
                data["history"] = []
            return data
        except Exception:
            pass
    return _default_state()


def _save_state(state: dict) -> None:
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    _DEFAULT_STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


def should_run(loop_count: int) -> bool:
    return loop_count > 0 and loop_count % LOOP_INTERVAL == 0


def _gap_id(topic: str) -> str:
    # Stable-ish id for de-duplication.
    return topic.lower().replace(" ", "_")[:96]


def _is_problem_entry(entry: dict) -> Tuple[bool, str, str]:
    """Heuristic: identify entries that likely indicate a gap.

    Returns: (is_problem, topic, example)
    """
    src = str(entry.get("source", "unknown"))
    typ = str(entry.get("type", "unknown"))
    data = entry.get("data", {})

    example = ""
    if isinstance(data, dict):
        # common patterns
        if "error" in data and data.get("error"):
            example = str(data.get("error"))
        elif "errors" in data and data.get("errors"):
            example = str(data.get("errors"))
        elif "failed" in data and data.get("failed"):
            example = str(data.get("failed"))
        elif "status" in data and data.get("status") in ("orange", "red"):
            example = f"status={data.get('status')}"
        elif "summary" in data and data.get("summary"):
            example = str(data.get("summary"))

    # A few entry types are naturally noisy; skip.
    if typ in ("startup", "shutdown"):
        return (False, "", "")

    # Problem if we have explicit error-ish payload
    problem = bool(example) or typ in ("error", "exception")

    if not problem:
        return (False, "", "")

    # Topic is coarse to reduce cardinality
    topic = f"{src}:{typ}"
    if isinstance(data, dict) and data.get("status") in ("orange", "red"):
        topic = f"{src}:health:{data.get('status')}"

    return (True, topic, example)


def run_scan(loop_count: Optional[int] = None, *, recent_n: int = 200) -> dict:
    """Scan recent THALAMUS entries and update learning gaps.

    Called periodically by NervousSystem.post_loop.
    """
    ts = time.time()
    state = _load_state()
    gaps: List[dict] = state.get("gaps", [])

    recent = thalamus.read_recent(n=recent_n)

    new_gaps = 0
    updated_gaps = 0
    escalated = 0
    broadcasts = 0

    # Index gaps by id
    idx = {g.get("id"): g for g in gaps if isinstance(g, dict) and g.get("id")}

    for entry in recent:
        if not isinstance(entry, dict):
            continue

        is_prob, topic, example = _is_problem_entry(entry)
        if not is_prob:
            continue

        gid = _gap_id(topic)
        g = idx.get(gid)
        if not g:
            g = {
                "id": gid,
                "topic": topic,
                "first_seen": ts,
                "last_seen": ts,
                "count": 1,
                "examples": [],
            }
            idx[gid] = g
            gaps.append(g)
            new_gaps += 1

            # Emit new gap immediately
            try:
                thalamus.append(
                    {
                        "source": "cortex_ext",
                        "type": "learning_gap_detected",
                        "salience": 0.6,
                        "data": {
                            "topic": topic,
                            "gap_id": gid,
                            "example": example[:280],
                        },
                    }
                )
                broadcasts += 1
            except Exception:
                pass
        else:
            g["last_seen"] = ts
            g["count"] = int(g.get("count", 0)) + 1
            updated_gaps += 1

            # Escalate if recurrent
            if g["count"] in (ESCALATION_COUNT, ESCALATION_COUNT * 2):
                try:
                    thalamus.append(
                        {
                            "source": "cortex_ext",
                            "type": "learning_gap_escalated",
                            "salience": 0.75,
                            "data": {
                                "topic": topic,
                                "gap_id": gid,
                                "count": g["count"],
                                "example": example[:280],
                            },
                        }
                    )
                    broadcasts += 1
                    escalated += 1
                except Exception:
                    pass

        # Keep a few examples per gap
        if example:
            ex = g.get("examples", [])
            if not isinstance(ex, list):
                ex = []
            if example not in ex:
                ex.append(example[:500])
                g["examples"] = ex[-5:]

    # Persist
    state["gaps"] = gaps
    state["total_scans"] = int(state.get("total_scans", 0)) + 1
    state["last_run"] = ts
    if loop_count is not None:
        state["last_loop"] = loop_count

    summary = {
        "ts": ts,
        "entries_scanned": len(recent),
        "new_gaps": new_gaps,
        "updated_gaps": updated_gaps,
        "escalated": escalated,
        "broadcasts": broadcasts,
        "total_gaps": len(gaps),
    }
    hist = state.get("history", [])
    if not isinstance(hist, list):
        hist = []
    hist.append(summary)
    state["history"] = hist[-20:]

    _save_state(state)
    return summary


def get_status() -> dict:
    state = _load_state()
    gaps = state.get("gaps", [])
    if not isinstance(gaps, list):
        gaps = []
    # Show top gaps by count
    top = sorted(
        (g for g in gaps if isinstance(g, dict)),
        key=lambda g: int(g.get("count", 0)),
        reverse=True,
    )[:10]

    return {
        "total_scans": state.get("total_scans", 0),
        "last_run": state.get("last_run", 0),
        "last_loop": state.get("last_loop", 0),
        "gap_count": len(gaps),
        "top_gaps": [
            {
                "id": g.get("id"),
                "topic": g.get("topic"),
                "count": g.get("count"),
                "last_seen": g.get("last_seen"),
            }
            for g in top
        ],
        "seconds_since_last": (
            (time.time() - state["last_run"]) if state.get("last_run") else None
        ),
    }


# --- Tests ---


def _run_tests():
    print("Testing CORTEX_EXT...")

    assert not should_run(0)
    assert not should_run(1)
    assert should_run(150)
    assert should_run(300)
    print("  ✅ should_run")

    # Force a tiny in-memory scan by patching thalamus functions.
    original_read_recent = thalamus.read_recent
    original_append = thalamus.append

    appended = []

    def _fake_recent(n=200):
        return [
            {
                "ts": int(time.time() * 1000),
                "source": "spine",
                "type": "health",
                "salience": 0.9,
                "data": {"status": "red", "error": "disk"},
            },
            {
                "ts": int(time.time() * 1000),
                "source": "cli",
                "type": "error",
                "salience": 0.8,
                "data": {"error": "traceback"},
            },
        ]

    def _fake_append(e):
        appended.append(e)
        return e

    try:
        thalamus.read_recent = _fake_recent  # type: ignore
        thalamus.append = _fake_append  # type: ignore
        summary = run_scan(loop_count=150, recent_n=5)
        assert summary["new_gaps"] >= 1
        assert len(appended) >= 1
        print("  ✅ run_scan emits to THALAMUS")
    finally:
        thalamus.read_recent = original_read_recent  # type: ignore
        thalamus.append = original_append  # type: ignore

    status = get_status()
    assert "gap_count" in status
    print("  ✅ get_status")

    print("All CORTEX_EXT tests passed! ✅")


if __name__ == "__main__":
    _run_tests()
