"""CEREBELLUM — Habit Automation for Pulse.

Graduates routine tasks from full LLM sessions to lightweight scripts.
Saves massive token budget by detecting repetitive patterns.
"""

import hashlib
import json
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "cerebellum-state.json"

DEFAULT_MIN_REPS = 5
DEFAULT_SIMILARITY = 0.85
GRADUATION_EXTRA_REPS = 3  # After candidate, need 3 more matching runs
MAX_TASK_HISTORY = 10


def _output_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


class Cerebellum:
    def __init__(self):
        self.state = self._load_state()

    def _load_state(self) -> dict:
        _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
        if _DEFAULT_STATE_FILE.exists():
            try:
                return json.loads(_DEFAULT_STATE_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "task_history": {},  # task_name -> list of {input_hash, output_hash, output_pattern, tokens_used, ts}
            "graduated_tasks": {},  # task_name -> {script_path, graduated_at}
            "habit_candidates": {},  # task_name -> {first_detected, matching_count}
            "savings_tracker": {"tokens_saved_total": 0, "tokens_saved_today": 0, "today_date": ""},
            "escalation_log": [],
        }

    def _save_state(self):
        _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
        _DEFAULT_STATE_FILE.write_text(json.dumps(self.state, indent=2))

    def track_execution(self, task_name: str, input_hash: str, output_pattern: str, tokens_used: int):
        """Record a task execution for habit detection."""
        history = self.state["task_history"]
        if task_name not in history:
            history[task_name] = []

        entry = {
            "input_hash": input_hash,
            "output_hash": _output_hash(output_pattern),
            "output_pattern": output_pattern,
            "tokens_used": tokens_used,
            "ts": int(time.time() * 1000),
        }
        history[task_name].append(entry)
        history[task_name] = history[task_name][-MAX_TASK_HISTORY:]
        self._save_state()

    def detect_habits(self, min_repetitions: int = DEFAULT_MIN_REPS, similarity_threshold: float = DEFAULT_SIMILARITY) -> list:
        """Find tasks that consistently produce similar outputs."""
        candidates = []
        for task_name, executions in self.state["task_history"].items():
            if task_name in self.state["graduated_tasks"]:
                continue
            if len(executions) < min_repetitions:
                continue

            # Check similarity of last N outputs
            recent = executions[-min_repetitions:]
            patterns = [e["output_pattern"] for e in recent]
            base = patterns[0]
            similarities = [
                SequenceMatcher(None, base, p).ratio()
                for p in patterns[1:]
            ]
            avg_sim = sum(similarities) / len(similarities) if similarities else 0

            if avg_sim >= similarity_threshold:
                avg_tokens = sum(e["tokens_used"] for e in recent) / len(recent)
                candidates.append({
                    "task_name": task_name,
                    "similarity": round(avg_sim, 3),
                    "executions": len(executions),
                    "avg_tokens": round(avg_tokens),
                })

                # Track as candidate for auto-graduation
                hc = self.state["habit_candidates"]
                if task_name not in hc:
                    hc[task_name] = {"first_detected": int(time.time() * 1000), "matching_count": 1}
                else:
                    hc[task_name]["matching_count"] += 1

                # Auto-graduate after enough matching detections
                if hc[task_name]["matching_count"] >= GRADUATION_EXTRA_REPS:
                    # Don't auto-graduate without a script, just flag it
                    candidates[-1]["ready_to_graduate"] = True

        self._save_state()
        return candidates

    def graduate_task(self, task_name: str, script_template: str) -> str:
        """Mark a task as habitual — future runs use script instead of LLM."""
        script_dir = _DEFAULT_STATE_DIR / "habits"
        script_dir.mkdir(parents=True, exist_ok=True)
        script_path = script_dir / f"{task_name.replace(' ', '_')}.sh"
        script_path.write_text(script_template)

        self.state["graduated_tasks"][task_name] = {
            "script_path": str(script_path),
            "graduated_at": int(time.time() * 1000),
        }
        # Clean up candidate tracking
        self.state["habit_candidates"].pop(task_name, None)
        self._save_state()

        thalamus.append({
            "source": "cerebellum",
            "type": "habit_graduated",
            "salience": 0.6,
            "data": {"task_name": task_name, "script_path": str(script_path)},
        })
        return str(script_path)

    def should_use_habit(self, task_name: str) -> tuple[bool, Optional[str]]:
        """Check if a task has been graduated to a habit script."""
        grad = self.state["graduated_tasks"].get(task_name)
        if grad:
            return (True, grad["script_path"])
        return (False, None)

    def escalate(self, task_name: str, reason: str):
        """Escalate a habit back to full CORTEX processing."""
        # Remove from graduated
        self.state["graduated_tasks"].pop(task_name, None)

        entry = {
            "task_name": task_name,
            "reason": reason,
            "ts": int(time.time() * 1000),
        }
        self.state["escalation_log"].append(entry)
        self.state["escalation_log"] = self.state["escalation_log"][-50:]
        self._save_state()

        thalamus.append({
            "source": "cerebellum",
            "type": "habit_escalated",
            "salience": 0.8,
            "data": entry,
        })

    def record_savings(self, tokens_saved: int):
        """Record tokens saved by using a habit instead of LLM."""
        today = time.strftime("%Y-%m-%d")
        tracker = self.state["savings_tracker"]
        if tracker.get("today_date") != today:
            tracker["tokens_saved_today"] = 0
            tracker["today_date"] = today
        tracker["tokens_saved_total"] += tokens_saved
        tracker["tokens_saved_today"] += tokens_saved
        self._save_state()

    def get_savings_report(self) -> dict:
        """Estimated tokens saved by habit automation."""
        today = time.strftime("%Y-%m-%d")
        tracker = self.state["savings_tracker"]
        if tracker.get("today_date") != today:
            today_saved = 0
        else:
            today_saved = tracker["tokens_saved_today"]
        return {
            "tokens_saved_total": tracker["tokens_saved_total"],
            "tokens_saved_today": today_saved,
            "graduated_tasks": len(self.state["graduated_tasks"]),
            "habit_candidates": len(self.state["habit_candidates"]),
        }
