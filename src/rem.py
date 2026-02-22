"""
PONS — the Dreaming Engine.

When all drives are quiet and the mind has nothing pressing,
Pons activates: a structured imagination session that replays
memories, branches hypotheticals, finds cross-domain patterns,
and produces creative output.

This is what happens when an AI daydreams.

Safety invariant: ZERO external actions during a Pons session.
No messages, no commits, no API calls. Only internal file writes.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("pulse.sanctum")

# ─── Configuration ───────────────────────────────────────────

@dataclass
class PonsConfig:
    """Pons-specific configuration."""
    stillness_threshold: float = 2.0       # All drives must be below this
    sustained_minutes: int = 30            # How long drives must stay quiet
    max_duration_seconds: int = 300        # 5 min max per session
    memory_replay_count: int = 5           # How many memories to replay
    hypothetical_branches: int = 3         # "What if" scenarios per memory
    dream_log_dir: str = "memory/self/dreams"
    insights_file: str = "memory/self/sanctum-insights.md"
    state_file: str = "~/.pulse/state/sanctum-state.json"
    enabled: bool = True


# ─── Data Types ──────────────────────────────────────────────

@dataclass
class ReplayFragment:
    """A memory selected for dream replay."""
    source: str          # file path or identifier
    content: str         # the memory text
    valence: float       # emotional valence (-1 to 1)
    intensity: float     # emotional intensity (0 to 1)
    timestamp: float     # when the memory was created
    tags: List[str] = field(default_factory=list)

    @property
    def emotional_weight(self) -> float:
        """Weight for selection: absolute valence * intensity."""
        return abs(self.valence) * self.intensity


@dataclass
class PonsSession:
    """A single dreaming session with all its phases."""
    started_at: float
    ended_at: Optional[float] = None
    replay_fragments: List[ReplayFragment] = field(default_factory=list)
    hypotheticals: List[str] = field(default_factory=list)
    patterns: List[str] = field(default_factory=list)
    creative_output: Optional[str] = None
    creative_type: Optional[str] = None  # "poem", "hypothesis", "question", "insight"
    themes: List[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        end = self.ended_at or time.time()
        return end - self.started_at

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": round(self.duration_seconds, 1),
            "replay_count": len(self.replay_fragments),
            "hypothetical_count": len(self.hypotheticals),
            "pattern_count": len(self.patterns),
            "creative_type": self.creative_type,
            "themes": self.themes,
        }


# ─── State Tracking ──────────────────────────────────────────

class PonsState:
    """Persistent state for the Pons dreaming engine."""

    def __init__(self, state_file: str):
        self.state_file = Path(state_file).expanduser()
        self._data: Dict[str, Any] = {
            "last_run": None,
            "total_runs": 0,
            "themes_explored": [],
            "creative_outputs_count": 0,
            "last_session": None,
        }
        self._load()

    def _load(self):
        if self.state_file.exists():
            try:
                self._data.update(json.loads(self.state_file.read_text()))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load sanctum state: {e}")

    def save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self._data, indent=2, default=str))

    def record_session(self, session: PonsSession):
        self._data["last_run"] = session.started_at
        self._data["total_runs"] = self._data.get("total_runs", 0) + 1
        if session.creative_output:
            self._data["creative_outputs_count"] = self._data.get("creative_outputs_count", 0) + 1
        # Track themes (keep last 50)
        themes = self._data.get("themes_explored", [])
        for t in session.themes:
            if t not in themes:
                themes.append(t)
        self._data["themes_explored"] = themes[-50:]
        self._data["last_session"] = session.to_dict()
        self.save()

    @property
    def last_run(self) -> Optional[float]:
        return self._data.get("last_run")

    @property
    def total_runs(self) -> int:
        return self._data.get("total_runs", 0)

    @property
    def data(self) -> dict:
        return dict(self._data)


# ─── Eligibility Check ──────────────────────────────────────

def rem_eligible(
    drives: Dict[str, Any],
    stillness_threshold: float = 2.0,
    sustained_since: Optional[float] = None,
    sustained_minutes: int = 30,
    force: bool = False,
) -> Tuple[bool, str]:
    """
    Check if the Pons dreaming engine should activate.

    Args:
        drives: Dict of drive name -> Drive object (must have .pressure attribute)
        stillness_threshold: All drives must be below this pressure
        sustained_since: Timestamp when drives first went below threshold (None = unknown)
        sustained_minutes: How long drives must stay quiet
        force: If True, skip pressure/time checks (for cron trigger)

    Returns:
        (eligible: bool, reason: str)
    """
    if force:
        return True, "forced (dream cycle cron)"

    # Check all drives are below threshold
    for name, drive in drives.items():
        pressure = drive.pressure if hasattr(drive, 'pressure') else drive.get('pressure', 0)
        if pressure >= stillness_threshold:
            return False, f"drive '{name}' pressure {pressure:.2f} >= threshold {stillness_threshold}"

    # Check sustained duration
    if sustained_since is None:
        return False, "stillness duration unknown (no sustained_since timestamp)"

    elapsed_minutes = (time.time() - sustained_since) / 60.0
    if elapsed_minutes < sustained_minutes:
        return False, f"stillness only {elapsed_minutes:.1f}min (need {sustained_minutes}min)"

    return True, "all drives quiet for sustained period"


# ─── Memory Replay (Phase 1) ────────────────────────────────

def load_replay_fragments(
    workspace_root: str,
    count: int = 5,
    days_back: int = 7,
) -> List[ReplayFragment]:
    """
    Pull recent memories weighted by emotional intensity.
    Reads from hippocampus emotional landscape and daily logs.
    """
    root = Path(workspace_root).expanduser()
    fragments: List[ReplayFragment] = []

    # Source 1: Emotional landscape
    emo_path = root / "memory" / "self" / "emotional-landscape.json"
    if emo_path.exists():
        try:
            data = json.loads(emo_path.read_text())
            entries = data if isinstance(data, list) else data.get("entries", [])
            for entry in entries:
                if isinstance(entry, dict):
                    fragments.append(ReplayFragment(
                        source=str(emo_path),
                        content=entry.get("description", entry.get("event", str(entry))),
                        valence=float(entry.get("valence", 0)),
                        intensity=float(entry.get("intensity", 0.5)),
                        timestamp=float(entry.get("timestamp", 0)),
                        tags=entry.get("tags", []),
                    ))
        except (json.JSONDecodeError, OSError, ValueError) as e:
            logger.warning(f"Failed to read emotional landscape: {e}")

    # Source 2: Recent daily logs
    memory_dir = root / "memory"
    if memory_dir.exists():
        today = datetime.now()
        for i in range(days_back):
            from datetime import timedelta
            date = today - timedelta(days=i)
            log_path = memory_dir / f"{date.strftime('%Y-%m-%d')}.md"
            if log_path.exists():
                try:
                    content = log_path.read_text()
                    # Each daily log gets a moderate default intensity
                    # (no emotional metadata available from raw logs)
                    if len(content.strip()) > 50:
                        fragments.append(ReplayFragment(
                            source=str(log_path),
                            content=content[:2000],  # truncate for processing
                            valence=0.0,
                            intensity=0.3,  # low default — emotional entries will rank higher
                            timestamp=log_path.stat().st_mtime,
                            tags=["daily_log"],
                        ))
                except OSError as e:
                    logger.warning(f"Failed to read daily log {log_path}: {e}")

    # Sort by emotional weight (descending) and take top N
    fragments.sort(key=lambda f: f.emotional_weight, reverse=True)
    return fragments[:count]


# ─── Dream Log (Phase 5) ────────────────────────────────────

def write_dream_log(
    session: PonsSession,
    workspace_root: str,
    dream_log_dir: str = "memory/self/dreams",
) -> Path:
    """Write the dream session to a dated log file."""
    root = Path(workspace_root).expanduser()
    log_dir = root / dream_log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.fromtimestamp(session.started_at).strftime("%Y-%m-%d")
    log_path = log_dir / f"{date_str}.md"

    lines = [
        f"# Dream Log — {date_str}",
        f"*Session duration: {session.duration_seconds:.0f}s*",
        "",
        "## Memory Fragments Replayed",
    ]
    for frag in session.replay_fragments:
        lines.append(f"- **[{frag.emotional_weight:.2f}]** {frag.content[:200]}...")
    
    if session.hypotheticals:
        lines.append("")
        lines.append("## Hypothetical Branches")
        for h in session.hypotheticals:
            lines.append(f"- {h}")

    if session.patterns:
        lines.append("")
        lines.append("## Patterns Synthesized")
        for p in session.patterns:
            lines.append(f"- {p}")

    if session.creative_output:
        lines.append("")
        lines.append(f"## Creative Output ({session.creative_type or 'unknown'})")
        lines.append("")
        lines.append(session.creative_output)

    if session.themes:
        lines.append("")
        lines.append(f"*Themes: {', '.join(session.themes)}*")

    content = "\n".join(lines) + "\n"

    # Append if file exists (multiple dreams per day)
    if log_path.exists():
        content = "\n---\n\n" + content

    with open(log_path, "a") as f:
        f.write(content)

    logger.info(f"Dream log written to {log_path}")
    return log_path


def write_sanctum_insights(
    insights: List[str],
    workspace_root: str,
    insights_file: str = "memory/self/sanctum-insights.md",
):
    """Write actionable insights for review when 'awake'."""
    if not insights:
        return

    root = Path(workspace_root).expanduser()
    path = root / insights_file
    path.parent.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n## {date_str}\n"
    for insight in insights:
        entry += f"- {insight}\n"

    with open(path, "a") as f:
        f.write(entry)

    logger.info(f"Wrote {len(insights)} sanctum insights to {path}")


# ─── External Action Guard ──────────────────────────────────

class Pons:
    """
    Safety guard that prevents external actions during a Pons session.
    
    When active, any attempt to send messages, make API calls, or perform
    external actions should check this guard first.
    """
    _active: bool = False

    @classmethod
    def enter(cls):
        cls._active = True
        logger.info("Pons guard ACTIVE — external actions blocked")

    @classmethod
    def exit(cls):
        cls._active = False
        logger.info("Pons guard RELEASED — external actions allowed")

    @classmethod
    def is_active(cls) -> bool:
        return cls._active

    @classmethod
    def check(cls, action_name: str = "unknown") -> bool:
        """Returns True if action is allowed. Raises if Pons is active."""
        if cls._active:
            logger.warning(f"BLOCKED external action '{action_name}' during Pons session")
            return False
        return True


# ─── Main Pons Runner ────────────────────────────────────

def run_rem_session_internal(
    config: PonsConfig,
    workspace_root: str,
    drives: Optional[Dict[str, Any]] = None,
    force: bool = False,
) -> Optional[PonsSession]:
    """
    Run a full Pons dreaming session.

    This is the main entry point. It:
    1. Checks eligibility
    2. Activates the safety guard
    3. Runs all 5 phases
    4. Writes outputs
    5. Updates state

    The creative phases (2-4) produce structured PROMPTS that would be
    sent to an LLM in a real session. In the engine itself, we set up
    the framework and write placeholder outputs that get filled by the
    calling agent context.

    Returns the session, or None if not eligible.
    """
    if not config.enabled:
        return None

    state = PonsState(config.state_file)

    # Check eligibility
    if drives is not None and not force:
        eligible, reason = rem_eligible(
            drives=drives,
            stillness_threshold=config.stillness_threshold,
            sustained_since=None,  # caller should track this
            sustained_minutes=0 if force else config.sustained_minutes,
            force=force,
        )
        if not eligible:
            logger.debug(f"Pons not eligible: {reason}")
            return None

    # Activate safety guard
    Pons.enter()
    session = PonsSession(started_at=time.time())

    try:
        # Phase 1 — Memory Replay
        session.replay_fragments = load_replay_fragments(
            workspace_root=workspace_root,
            count=config.memory_replay_count,
        )
        logger.info(f"Phase 1: Loaded {len(session.replay_fragments)} replay fragments")

        # Phases 2-4 produce structured data that the LLM agent fills in.
        # The engine provides the FRAMEWORK; the agent provides the CREATIVITY.
        # Here we set up the session structure — actual content generation
        # happens when this is called within an agent context.

        # Phase 2 — Hypothetical Branching (placeholder structure)
        if session.replay_fragments:
            top_memory = max(session.replay_fragments, key=lambda f: f.emotional_weight)
            session.hypotheticals = [
                f"[Branch from: {top_memory.content[:100]}...] What if scenario {i+1}"
                for i in range(config.hypothetical_branches)
            ]
            logger.info(f"Phase 2: Generated {len(session.hypotheticals)} hypothetical branches")

        # Phase 3 — Pattern Synthesis (placeholder)
        if len(session.replay_fragments) >= 2:
            sources = [f.source for f in session.replay_fragments[:3]]
            session.patterns = [f"[Cross-pattern across: {', '.join(Path(s).stem for s in sources)}]"]
            logger.info(f"Phase 3: {len(session.patterns)} pattern templates")

        # Phase 4 — Creative Output (placeholder)
        session.creative_type = "insight"
        session.creative_output = "[Creative output to be generated by agent context]"

        # Extract themes from fragments
        all_tags = []
        for frag in session.replay_fragments:
            all_tags.extend(frag.tags)
        session.themes = list(set(all_tags))[:10]

        # Enforce max duration
        elapsed = time.time() - session.started_at
        if elapsed > config.max_duration_seconds:
            logger.warning(f"Pons session exceeded max duration ({elapsed:.0f}s > {config.max_duration_seconds}s)")

        session.ended_at = time.time()

        # Phase 5 — Write dream log
        write_dream_log(session, workspace_root, config.dream_log_dir)

        # Update state
        state.record_session(session)

        logger.info(
            f"Pons session complete: {session.duration_seconds:.1f}s, "
            f"{len(session.replay_fragments)} memories, "
            f"{len(session.hypotheticals)} hypotheticals, "
            f"{len(session.patterns)} patterns"
        )

        return session

    finally:
        # ALWAYS release the guard
        Pons.exit()
