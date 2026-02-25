"""MIRROR v2 — Bidirectional Modeling for Pulse.

Extends josh_model.md with a reverse model: iris_model.md that Josh edits
to tell Iris what he sees. Enables alignment comparison between
self-perception (PROPRIOCEPTION) and external perception.
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "mirror-state.json"

WORKSPACE = Path.home() / ".openclaw" / "workspace"
JOSH_MODEL_PATH = WORKSPACE / "memory" / "self" / "josh_model.md"
IRIS_MODEL_PATH = WORKSPACE / "memory" / "self" / "iris_model.md"

# Sections we parse from iris_model.md
IRIS_MODEL_SECTIONS = [
    "What I see in you",
    "Your strengths",
    "Your blind spots",
    "What I need from you",
    "Patterns I've noticed",
]


# ── State persistence ───────────────────────────────────────────────────

def _load_state() -> dict:
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    if _DEFAULT_STATE_FILE.exists():
        try:
            return json.loads(_DEFAULT_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "iris_model_hash": None,
        "last_check_ts": None,
        "change_log": [],
    }


def _save_state(state: dict):
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    _DEFAULT_STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Parsing helpers ─────────────────────────────────────────────────────

def _parse_model_file(path: Path) -> dict:
    """Parse a markdown model file into sections."""
    if not path.exists():
        return {}
    text = path.read_text()
    sections = {}
    current_section = None
    current_lines = []

    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## "):
            if current_section is not None:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = stripped[3:].strip()
            current_lines = []
        elif current_section is not None:
            current_lines.append(line)

    if current_section is not None:
        sections[current_section] = "\n".join(current_lines).strip()

    return sections


def _file_hash(path: Path) -> Optional[str]:
    """Get hash of file contents."""
    if not path.exists():
        return None
    return hashlib.md5(path.read_bytes()).hexdigest()


# ── Core functions ──────────────────────────────────────────────────────

def get_josh_model() -> dict:
    """Load and parse josh_model.md."""
    return _parse_model_file(JOSH_MODEL_PATH)


def get_iris_model() -> dict:
    """Load and parse iris_model.md (Josh's view of Iris)."""
    return _parse_model_file(IRIS_MODEL_PATH)


def update_josh_model(field: str, value: str):
    """Update a section in josh_model.md."""
    sections = get_josh_model()
    sections[field] = value

    lines = [f"# Josh Model\n"]
    for section, content in sections.items():
        lines.append(f"## {section}\n{content}\n")

    JOSH_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    JOSH_MODEL_PATH.write_text("\n".join(lines))


def check_iris_model_updates() -> list[str]:
    """Detect changes in iris_model.md since last read."""
    state = _load_state()
    current_hash = _file_hash(IRIS_MODEL_PATH)

    if current_hash is None:
        return []

    prev_hash = state.get("iris_model_hash")
    state["last_check_ts"] = int(time.time() * 1000)

    if prev_hash == current_hash:
        _save_state(state)
        return []

    # File changed — identify which sections differ
    old_sections = {}
    if prev_hash is not None:
        # We don't cache old content, so just report all sections as changed on first detection
        # On subsequent changes, we compare current sections
        pass

    current_sections = get_iris_model()
    changes = [f"Section '{s}' updated" for s in current_sections if current_sections[s].strip()]

    state["iris_model_hash"] = current_hash
    if changes:
        state["change_log"].append({
            "ts": int(time.time() * 1000),
            "changes": changes,
        })
        # Keep last 50 change entries
        state["change_log"] = state["change_log"][-50:]

    _save_state(state)
    return changes


def integrate_feedback(changes: list):
    """Process Josh's edits: update PROPRIOCEPTION self-model, log to THALAMUS."""
    if not changes:
        return

    # Broadcast to THALAMUS
    thalamus.append({
        "source": "mirror",
        "type": "feedback",
        "salience": 0.8,
        "data": {"changes": changes, "from": "josh_iris_model"},
    })

    # Update PROPRIOCEPTION with external view
    try:
        from pulse.src import proprioception
        model = proprioception.get_self_model()
        model["external_feedback_ts"] = int(time.time() * 1000)
        model["external_feedback_count"] = model.get("external_feedback_count", 0) + 1
    except Exception:
        pass


def get_alignment_report() -> dict:
    """Compare self-perception (PROPRIOCEPTION) vs Josh's perception (iris_model)."""
    iris_model = get_iris_model()

    self_view = {}
    try:
        from pulse.src import proprioception
        self_view = proprioception.get_self_model()
    except Exception:
        pass

    return {
        "self_view": {
            "model": self_view.get("model", "unknown"),
            "limitations": self_view.get("limitations", []),
            "tools_count": len(self_view.get("tools_available", [])),
        },
        "josh_view": {
            "observations": iris_model.get("What I see in you", ""),
            "strengths": iris_model.get("Your strengths", ""),
            "blind_spots": iris_model.get("Your blind spots", ""),
            "needs": iris_model.get("What I need from you", ""),
            "patterns": iris_model.get("Patterns I've noticed", ""),
        },
        "has_external_feedback": bool(iris_model),
        "ts": int(time.time() * 1000),
    }


def get_relational_state() -> dict:
    """Combined model: Josh's estimated state + Iris's state + relationship dynamics."""
    josh = get_josh_model()
    iris = get_iris_model()

    return {
        "josh_state": josh,
        "iris_external_view": iris,
        "relationship": {
            "bidirectional": bool(josh and iris),
            "josh_model_populated": bool(josh),
            "iris_model_populated": bool(iris),
        },
        "ts": int(time.time() * 1000),
    }


def load_models():
    """Public: load state (for startup)."""
    return _load_state()
