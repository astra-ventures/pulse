# Contributing to Pulse

First off — thank you! Pulse exists because autonomy matters, and every contribution makes AI agents more genuinely self-directed.

## How to Contribute

### 1. Report Bugs

Found a bug? Open an issue:
- **Title:** Clear, specific (e.g., "FileSystemSensor crashes on symlinks")
- **Environment:** OS, Python version, Pulse version
- **Steps to reproduce:** What did you do?
- **Expected vs actual:** What should happen vs what happened?
- **Logs:** Include relevant error messages (sanitize sensitive data!)

### 2. Suggest Features

Have an idea? Open an issue with:
- **Use case:** Why do you need this?
- **Proposal:** What should it do?
- **Alternatives:** What workarounds exist today?

**Examples of good feature requests:**
- "Add Slack sensor to detect channel silence" (clear use case, well-scoped)
- "Allow custom drive formulas" (addresses real limitation)

**Please avoid:**
- "Make it better" (too vague)
- "Add everything from [other project]" (fork it instead!)

### 3. Submit Code

**Before you start:**
1. Check if an issue exists — if not, create one
2. Comment "I'd like to work on this" to avoid duplicate effort
3. Fork the repo, create a branch: `git checkout -b feature/your-feature`

**Code standards:**
- **Python 3.11+** — use modern syntax, type hints encouraged
- **Tests required** — all new features need tests (pytest)
- **Docstrings** — public methods/classes need docstrings
- **Black formatting** — run `black .` before commit
- **No new dependencies** — unless absolutely necessary (discuss first)

**Commit messages:**
- Use present tense ("Add feature" not "Added feature")
- Be specific ("Fix FileSystemSensor symlink crash" not "Fix bug")
- Reference issues: "Fixes #42"

**Pull Request Process:**
1. Update README.md if behavior changes
2. Update docs/ if architecture/config changes
3. Add entry to CHANGELOG.md under "Unreleased"
4. Ensure all tests pass: `pytest tests/`
5. Request review — tag @jcap93 or mention in Discord

### 4. Improve Documentation

Docs live in `docs/` and are written in Markdown. Contributions welcome:
- Fix typos, clarify confusing sections
- Add examples, diagrams, screenshots
- Translate to other languages (coming soon)

No PR needed for small fixes — just submit!

### 5. Share Your Config

Built a cool Pulse config? Share it!
- Add to `examples/` with a descriptive filename
- Include inline comments explaining your choices
- Submit a PR or share in Discord

**Example:** `examples/researcher-agent.yaml` for a paper-monitoring agent.

---

## Development Setup

```bash
# 1. Clone your fork
git clone https://github.com/YOUR_USERNAME/pulse.git
cd pulse

# 2. Create virtual environment
python3.11 -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# 3. Install dev dependencies
# (Installs core deps + test/lint/release tooling)
pip install -e ".[dev]"

# 4. Run tests
pytest tests/

# 5. Run Pulse locally
PULSE_CONFIG=config/pulse.example.yaml python3 -m pulse

# 6. Run health diagnostics
python3 -m pulse doctor
```

---

## Testing

We use **pytest**. Tests live in `tests/`.

**Run all tests:**
```bash
pytest tests/
```

**Run specific test:**
```bash
pytest tests/test_drive_engine.py::test_pressure_accumulation
```

**Test coverage:**
```bash
pytest --cov=pulse tests/
```

**Writing tests:**
- One test file per module: `test_<module>.py`
- Test names should be descriptive: `test_drive_decay_after_feedback`
- Use fixtures for common setup (see `tests/conftest.py`)

---

## Architecture Overview

Understanding Pulse's architecture helps you contribute effectively.

**Core components:**
1. **DriveEngine** (`pulse/drives.py`) — motivation system, pressure accumulation
2. **Sensors** (`pulse/sensors/`) — detect changes (filesystem, conversation, system)
3. **Evaluator** (`pulse/evaluator.py`) — decide when to trigger
4. **StateManager** (`pulse/state.py`) — persistence, migrations
5. **Mutator** (`pulse/mutator.py`) — self-modification system
6. **Daemon** (`pulse/daemon.py`) — orchestrates everything

**Data flow:**
```
Sensors → DriveEngine → Evaluator → Webhook (OpenClaw) → Feedback → Decay
```

Read `docs/architecture.md` for deeper dive.

---

## Code of Conduct

**TL;DR:** Be excellent to each other.

- **Respectful:** No harassment, personal attacks, or exclusionary behavior
- **Collaborative:** Credit others' work, assume good intent
- **Constructive:** Critique ideas, not people
- **Inclusive:** Welcome newcomers, help them succeed

Violations → warning. Repeated violations → ban. Report to @jcap93.

We're building tools for autonomy. Let's practice what we preach.

---

## Questions?

- **Discord:** [OpenClaw community](https://discord.com/invite/clawd) (#pulse channel)
- **Email:** jcap93@pm.me
- **X/Twitter:** [@jcap93](https://x.com/jcap93)

---

## License

By contributing, you agree your code is licensed under **MIT** (same as Pulse).

---

## Recognition

Contributors are listed in:
- README.md (alphabetical)
- Release notes for their contributions

First-time contributors get a shoutout in Discord 🎉

---

**Thank you for making AI agents more autonomous.** 🔮
