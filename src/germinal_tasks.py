"""GERMINAL TASKS — Generative Task Synthesis.

When all drives are high but the work queue is empty (everything blocked on
external deps), CORTEX closes without doing anything. GERMINAL TASKS fixes
this by synthesizing new actionable tasks from what Pulse already has:
current goals, recent memory/logs, HYPOTHALAMUS drives, THALAMUS broadcasts.

Works with zero configuration. Roadmap files (TIERS.md, ROADMAP.md, TODO.md)
are optional enhancements — not dependencies.

Design principle: GENERATE must ship to users who have none of these files.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger("pulse.germinal_tasks")

# ─── Done-for-now cooldown ────────────────────────────────────────────────────
# After GERMINAL generates a task in a category, suppress that category for
# CATEGORY_COOLDOWN_SECONDS. Forces genuine variety instead of cycling through
# the same buckets ("update docs", "review strategy", "manage queue").
CATEGORY_COOLDOWN_SECONDS = 4 * 3600  # 4 hours

_CATEGORY_STATE_FILE = Path.home() / ".pulse" / "state" / "germinal-category-cooldown.json"

# Coarse category keywords — if a task title contains one of these, it belongs
# to that category. Titles are lowercased before matching.
_CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "docs": ["doc", "documentation", "readme", "changelog", "comment"],
    "goals_queue": ["goals queue", "goal queue", "manage goal", "update goal", "review goal"],
    "polymarket": ["polymarket", "prediction market", "trading strategy", "market strateg"],
    "reflection": ["reflect", "review current state", "identify next", "review progress"],
    "x_twitter": ["tweet", "twitter", "x post", "x engag", "reply on x"],
    "pulse_review": ["pulse docs", "pulse codebase", "pulse test", "pulse module", "pulse system"],
    "journal": ["journal", "iamiris", "blog post", "blog entry"],
    "memory": ["memory", "hippocampus", "working memory"],
}


def _load_category_cooldowns() -> Dict[str, float]:
    """Return {category: expiry_timestamp} map."""
    if _CATEGORY_STATE_FILE.exists():
        try:
            return json.loads(_CATEGORY_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_category_cooldowns(cooldowns: Dict[str, float]):
    _CATEGORY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CATEGORY_STATE_FILE.write_text(json.dumps(cooldowns, indent=2))


def _classify_category(title: str) -> Optional[str]:
    """Return the coarse category for a task title, or None if uncategorized."""
    t = title.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in t for kw in keywords):
            return category
    return None


def _is_category_cooled_down(title: str, cooldowns: Dict[str, float]) -> bool:
    """Return True if this task's category is currently suppressed."""
    category = _classify_category(title)
    if category is None:
        return False  # Unknown category → always allow
    expiry = cooldowns.get(category, 0)
    return time.time() < expiry


def _record_category_used(titles: List[str]):
    """Mark all categories represented in the generated titles as cooling down."""
    cooldowns = _load_category_cooldowns()
    now = time.time()
    changed = False
    for title in titles:
        category = _classify_category(title)
        if category and cooldowns.get(category, 0) < now:
            cooldowns[category] = now + CATEGORY_COOLDOWN_SECONDS
            logger.debug(f"GENERATE: category '{category}' suppressed for {CATEGORY_COOLDOWN_SECONDS//3600}h")
            changed = True
    if changed:
        _save_category_cooldowns(cooldowns)

# Default reflection task when LLM fails or is unavailable
DEFAULT_REFLECTION_TASK = {
    "title": "Reflect on current state and identify next moves",
    "description": (
        "Review current goals, recent memory, and drive pressures. "
        "Identify one concrete action that can be completed right now "
        "without any external dependencies. Write findings to working memory."
    ),
    "rationale": "Fallback task: LLM unavailable, but drives are high and nothing is actionable. Reflection keeps momentum.",
    "drive": "growth",
    "effort": "low",
    "requires_external": False,
}

GENERATE_SYSTEM_PROMPT = """\
You are the task generator for an autonomous AI agent. The agent's work queue \
is empty — all existing tasks are blocked on external dependencies. But the \
agent's drives are still high, meaning it WANTS to work.

Your job: synthesize 1-3 NEW tasks the agent can do RIGHT NOW with NO external \
dependencies. These tasks should be:
- Completable immediately with tools the agent already has
- Relevant to the agent's current goals and drives
- NOT duplicates of existing goals
- NOT requiring human input, API responses, or waiting on anything

You will receive:
- Current goals (what the agent is working toward)
- Recent memory (what the agent has been doing/thinking)
- Drive pressures (what motivates the agent right now)
- Last 5 Agent Actions (what the agent JUST DID — do NOT repeat this work)
- Recently Generated Tasks (titles GERMINAL already synthesized — do NOT repeat)
- Recent broadcasts (what the nervous system is saying)
- Optionally: roadmap/TODO content from project files

Respond with ONLY valid JSON (no markdown, no explanation):
{
  "tasks": [
    {
      "title": "short action-oriented title",
      "description": "what to do and expected outcome (2-3 sentences)",
      "rationale": "why this task matters right now given drives and goals",
      "drive": "which drive this addresses (goals|curiosity|emotions|growth|unfinished)",
      "effort": "low|medium|high",
      "requires_external": false
    }
  ]
}

HARD RULES:
1. Every task MUST have requires_external: false. If it needs human input, API calls, \
or waiting — do NOT include it.
2. Tasks must be SPECIFIC and ACTIONABLE, not vague ("review things", "think about stuff").
3. Maximum 3 tasks. Quality over quantity.
4. Do NOT suggest tasks already in the goals list.
5. Prefer tasks that address the highest-pressure drives.
6. "effort" should reflect actual work: low = <30 min, medium = 30-120 min, high = 2+ hours.
7. CRITICAL — Anti-cascade rule: Do NOT repeat tasks from "Recently Generated Tasks" \
or "Last 5 Agent Actions" sections. If you see recent tasks there, your output MUST \
be meaningfully different. Vague documentation/queue/reflection tasks that keep \
recurring are a cascade anti-pattern — break the loop by finding genuinely new work. \
When blocked goals dominate, pivot entirely: write code, explore a curiosity, publish \
content, build a tool — anything that moves forward without external dependencies.
"""


async def generate_tasks(context: dict, config: dict) -> List[dict]:
    """Generate 1-3 actionable tasks from agent context.

    Args:
        context: Dict with keys:
            - goals (list): Current goal descriptions
            - recent_memory (str): ~1000 chars of recent memory/logs
            - drives (dict): name -> pressure mapping
            - thalamus_recent (list): Recent broadcast dicts
        config: Dict with keys from pulse.yaml generative section:
            - enabled (bool)
            - roadmap_files (list[str])
            - max_tasks (int)
            - model (dict): base_url, api_key, model, max_tokens, temperature, timeout_seconds

    Returns:
        List of task dicts, each with: title, description, rationale, drive, effort.
        Only tasks where requires_external=False are returned.
        Returns [DEFAULT_REFLECTION_TASK] on LLM failure.
    """
    if not config.get("enabled", True):
        return []

    max_tasks = config.get("max_tasks", 3)

    # Build prompt from context
    user_prompt = _build_prompt(context, config)

    # Try LLM call
    model_config = config.get("model", {})
    # Load current category cooldowns for done-for-now suppression
    category_cooldowns = _load_category_cooldowns()

    try:
        raw_tasks = await _call_llm(user_prompt, model_config)
        tasks = _parse_and_filter(
            raw_tasks,
            context.get("goals", []),
            max_tasks,
            recent_generated_titles=context.get("recent_generated_titles", []),
            category_cooldowns=category_cooldowns,
        )
        if tasks:
            logger.info(f"GENERATE: synthesized {len(tasks)} tasks")
            # Mark these categories as cooling down for next 4h
            _record_category_used([t["title"] for t in tasks])
            return tasks
        # LLM returned nothing usable (all filtered by cooldowns / dedup)
        logger.warning("GENERATE: LLM returned no non-cooled actionable tasks, using fallback")
        # Apply cooldown to the fallback task so consecutive LLM failures don't
        # cause infinite "Reflect on current state" cascade loops (Bug fix: #031).
        _record_category_used([DEFAULT_REFLECTION_TASK["title"]])
        return [DEFAULT_REFLECTION_TASK]
    except Exception as e:
        logger.warning(f"GENERATE: LLM call failed ({e}), using fallback")
        _record_category_used([DEFAULT_REFLECTION_TASK["title"]])
        return [DEFAULT_REFLECTION_TASK]


def _build_prompt(context: dict, config: dict) -> str:
    """Build the generation prompt from context and optional roadmap files."""
    parts = []

    # Goals
    goals = context.get("goals", [])
    parts.append("## Current Goals")
    if goals:
        for g in goals:
            parts.append(f"- {g}")
    else:
        parts.append("(no goals currently set)")
    parts.append("")

    # Drives
    drives = context.get("drives", {})
    parts.append("## Drive Pressures")
    for name, pressure in sorted(drives.items(), key=lambda x: x[1], reverse=True):
        bar = "#" * int(float(pressure) * 10)
        parts.append(f"- {name}: {float(pressure):.2f} [{bar}]")
    parts.append("")

    # Recently generated tasks — anti-cascade deduplication signal
    recent_generated_titles = context.get("recent_generated_titles", [])
    if recent_generated_titles:
        parts.append("## Recently Generated Tasks (DO NOT REPEAT THESE)")
        seen = set()
        for title in recent_generated_titles:
            if title.lower().strip() not in seen:
                seen.add(title.lower().strip())
                parts.append(f"- {title}")
        parts.append("")

    # Recent memory
    recent_memory = context.get("recent_memory", "")
    if recent_memory:
        parts.append("## Recent Memory")
        parts.append(recent_memory[:1000])
        parts.append("")

    # Recent agent turns — what the agent actually did last (richer than titles alone)
    recent_actions_log = context.get("recent_actions_log", [])
    if recent_actions_log:
        parts.append("## Last 5 Agent Actions (DO NOT REPEAT THIS WORK)")
        for action in recent_actions_log:
            import datetime as _dt
            ts = action.get("ts", 0)
            age_min = int((time.time() - ts) / 60) if ts else 0
            drive = action.get("top_drive", "?")
            snippet = action.get("snippet", "")[:100]
            parts.append(f"- [{age_min}m ago | drive:{drive}] {snippet}")
        parts.append("")

    # Thalamus broadcasts
    thalamus_recent = context.get("thalamus_recent", [])
    if thalamus_recent:
        parts.append("## Recent Nervous System Broadcasts")
        for broadcast in thalamus_recent[-5:]:
            source = broadcast.get("source", "?")
            btype = broadcast.get("type", "?")
            data = broadcast.get("data", {})
            parts.append(f"- [{source}] {btype}: {json.dumps(data, default=str)[:200]}")
        parts.append("")

    # Optional roadmap files
    roadmap_files = config.get("roadmap_files", [])
    workspace_root = config.get("workspace_root", "~/.openclaw/workspace")
    root = Path(workspace_root).expanduser()

    for roadmap_file in roadmap_files:
        filepath = root / roadmap_file
        if filepath.exists():
            try:
                content = filepath.read_text()[:2000]
                parts.append(f"## Roadmap: {roadmap_file}")
                parts.append(content)
                parts.append("")
            except OSError:
                pass

    return "\n".join(parts)


async def _call_llm(user_prompt: str, model_config: dict) -> list:
    """Call the LLM and return parsed task list."""
    base_url = model_config.get("base_url", "http://127.0.0.1:11434/v1")
    api_key = model_config.get("api_key", "ollama")
    model = model_config.get("model", "llama3.2:3b")
    max_tokens = model_config.get("max_tokens", 512)
    temperature = model_config.get("temperature", 0.3)
    timeout = model_config.get("timeout_seconds", 10)

    url = f"{base_url}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": GENERATE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "keep_alive": 0,  # Unload model immediately after call to prevent RAM pressure
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"LLM API returned {resp.status}: {body[:200]}")
            data = await resp.json()
            content = data["choices"][0]["message"]["content"]

    # Parse JSON from response
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    parsed = json.loads(cleaned)
    return parsed.get("tasks", [])


def _parse_and_filter(
    raw_tasks: list,
    existing_goals: list,
    max_tasks: int,
    recent_generated_titles: Optional[List[str]] = None,
    category_cooldowns: Optional[Dict[str, float]] = None,
) -> list:
    """Filter tasks: remove external deps, duplicates, cooled-down categories, and cap count."""
    required_fields = {"title", "description", "rationale", "drive", "effort"}
    valid_efforts = {"low", "medium", "high"}

    # Normalize existing goals for dedup
    goal_lower = {g.lower().strip() for g in existing_goals if isinstance(g, str)}

    # Normalize recently-generated titles for cascade dedup
    # Use fuzzy match: if a new task title contains the same key words as a
    # recent title, treat it as a repeat. This catches rephrasing like
    # "Update Goals Queue" vs "Update Goals Queue Manager Documentation".
    recent_lower: list = []
    if recent_generated_titles:
        recent_lower = [t.lower().strip() for t in recent_generated_titles if t]

    def _is_repeat(title: str) -> bool:
        """Return True if title is too similar to a recently generated task.

        Uses Jaccard similarity on word sets: overlap / union.
        Threshold 0.4 catches rephrasing like:
          'Update Goals Queue' vs 'Update Goals Queue with New Pulse Milestone'
          'Refactor Pulse Codebase' vs 'Refactor Pulse Codebase for Improved Readability'
        """
        t_lower = title.lower().strip()
        # Exact match
        if t_lower in recent_lower:
            return True
        t_words = set(t_lower.split())
        if len(t_words) < 2:
            return False
        for recent in recent_lower:
            r_words = set(recent.split())
            if not r_words:
                continue
            intersection = len(t_words & r_words)
            union = len(t_words | r_words)
            # Jaccard similarity: intersection / union
            if union > 0 and intersection / union >= 0.4:
                return True
            # Also check: if ≥75% of the shorter title's words appear in the longer
            shorter = t_words if len(t_words) <= len(r_words) else r_words
            if len(shorter) > 0 and intersection / len(shorter) >= 0.75:
                return True
        return False

    filtered = []
    for task in raw_tasks:
        if not isinstance(task, dict):
            continue

        # Must have all required fields
        if not required_fields.issubset(task.keys()):
            continue

        # Filter out tasks requiring external deps
        if task.get("requires_external", True):
            continue

        # Normalize effort
        if task["effort"] not in valid_efforts:
            task["effort"] = "medium"

        # Dedup: skip if title matches an existing goal
        if task["title"].lower().strip() in goal_lower:
            continue

        # Anti-cascade dedup: skip if too similar to recently generated tasks
        if _is_repeat(task["title"]):
            logger.debug(f"GENERATE: filtered repeat task '{task['title']}' (anti-cascade)")
            continue

        # Done-for-now cooldown: skip if this category was recently generated
        if category_cooldowns and _is_category_cooled_down(task["title"], category_cooldowns):
            cat = _classify_category(task["title"])
            logger.debug(f"GENERATE: filtered task '{task['title']}' (category '{cat}' cooling down)")
            continue

        # Remove the requires_external field from output (always False at this point)
        clean = {
            "title": task["title"],
            "description": task["description"],
            "rationale": task["rationale"],
            "drive": task["drive"],
            "effort": task["effort"],
        }
        filtered.append(clean)

        if len(filtered) >= max_tasks:
            break

    return filtered
