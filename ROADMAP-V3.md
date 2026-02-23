# Pulse v0.3.0 Roadmap

*Written: February 23, 2026 — 2:19 AM autonomous session*
*Current: v0.2.5 | Target: v0.3.0*

---

## Where We Are (v0.2.5)

Pulse is **functionally complete** for the core autonomous cognition loop:

- ✅ 38 nervous system modules (THALAMUS through PARIETAL)
- ✅ 693 tests passing
- ✅ Drive-based pressure system with evolution
- ✅ CORTEX loop (SENSE → THINK → ACT → MEASURE → EVOLVE)
- ✅ Work discovery context injection
- ✅ GENERATE task synthesis (germinal_tasks)
- ✅ Biosensor bridge (Phase E1)
- ✅ PARIETAL world model
- ✅ LaunchAgent management (hardened plist)
- ✅ GitHub: `github.com/astra-ventures/pulse`
- ✅ Full launch documentation (INSTALL, CONTRIBUTING, DOCKER, API, etc.)

**What's missing for v0.3.0:**
Three things that transform Pulse from "Iris's nervous system" into a product anyone can install.

---

## v0.3.0: The Public Release Milestone

### Goal: Zero-friction first run for new users

```bash
pip install pulse-agent
pulse init
pulse start
```

That's it. Should work on Mac, Linux, Pi, VPS.

---

## v0.3.0 Feature Set

### 1. PyPI Publication
**Priority: P0 | Effort: 1 day | Blocked: nothing**

- Package name: `pulse-agent` (reserved? check)
- `pyproject.toml` already at v0.2.5 with correct metadata
- Build: `python -m build`
- Publish: `twine upload dist/*`
- After: `pip install pulse-agent` works globally

**Why now:** ClawHub submission says "install via pip" — needs to be true.

---

### 2. `pulse init` — Interactive Setup Wizard
**Priority: P0 | Effort: 2 days | Blocked: nothing**

Current problem: Users must manually write `~/.pulse/config/pulse.yaml` with their webhook token. This is a 20% conversion killer.

Proposed flow:
```
$ pulse init

Welcome to Pulse! Let's set up your autonomous agent.

What's your OpenClaw webhook token?
(Find it at Settings → Webhooks in OpenClaw)
> pulse-hook-****

Which agent type?
1. Personal assistant (curiosity, growth, social drives)
2. Research agent (curiosity, unfinished drives)
3. Custom
> 1

Installation:
- Config written to ~/.pulse/config/pulse.yaml ✓
- LaunchAgent installed ✓
- Daemon starting...

🫀 Pulse is running. Try: pulse status
```

**Key insight:** First-run experience is make-or-break for OSS tools. Every manual step = lost user.

---

### 3. OpenClaw Skill Package (ClawHub)
**Priority: P0 | Effort: 1 day | Blocked: Josh's ClawHub account**

The ClawHub listing needs `skill.yaml` to be valid:

```yaml
name: pulse
version: 0.2.5
description: Give your AI agent a heartbeat
install:
  - pip install pulse-agent
  - pulse init
run: pulse start
```

Current `CLAWHUB_LISTING.md` is the human description. Need:
- `skill.yaml` spec file (OpenClaw skill format)
- Verification that `pulse init` works on fresh machine
- Video demo (30s: install → running → first trigger)

---

### 4. Drive Configuration UI (CLI)
**Priority: P1 | Effort: 2 days | Blocked: nothing**

Users currently can't customize drives without editing YAML. Add:

```bash
pulse drives list          # show drives with pressure
pulse drives set goals --weight 2.0  # set drive weight
pulse drives set goals --threshold 1.5  # custom trigger threshold
pulse drives add research  # birth new drive
pulse drives pause social  # temporarily suppress
```

The `pulse spike` and `pulse decay` commands exist. This makes drive management accessible to non-technical users.

---

### 5. Daemon Health Dashboard
**Priority: P1 | Effort: 1 day | Blocked: nothing**

`pulse status` is good but minimal. Add `pulse dashboard`:

```
🫀 Pulse v0.2.5 | Uptime: 3h 22m | Turn: 74
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  DRIVES                 PRESSURE
  ─────────────────────────────────
  ● system              ▓▓░░░░  1.44
  ● goals               ▓▓▓░░░  2.39  ← TOP
  ● curiosity           ▓░░░░░  0.87
  ● growth              ▓░░░░░  0.72
  ─────────────────────────────────
  Total pressure: 10.6

  NERVOUS SYSTEM         STATUS
  ─────────────────────────────────
  ● 38 modules           ✓ healthy
  ● Last trigger         22 min ago
  ● Next eval            ~3 min
  ─────────────────────────────────

  Recent: Fixed VESTIBULAR schema bug (2:19 AM)
          Published journal entry (1:00 AM)
```

---

## Release Criteria for v0.3.0

Before tagging `v0.3.0`:
- [ ] `pip install pulse-agent` works from PyPI
- [ ] `pulse init` guides new user to working daemon in < 3 minutes
- [ ] Tested on: macOS (M-series), Ubuntu 22.04, Raspberry Pi OS
- [ ] ClawHub `skill.yaml` submitted and approved
- [ ] `pulse dashboard` shows real-time drive state
- [ ] Zero failing tests
- [ ] CHANGELOG.md documents migration from v0.2.x

---

## What v0.3.0 Unlocks

Once `pip install pulse-agent && pulse init` works:

**ClawHub launch** → 145k+ OpenClaw users can discover and install Pulse. First OSS agent cognition framework in the ecosystem.

**Product Hunt launch** → Credible "install in 3 minutes" demo. The current setup is too manual for PH traffic.

**Pro tier groundwork** → Once the free tier is live and being used, Pro features (team drives, web dashboard, analytics) become tractable to build.

---

## Timeline

| Week | Work |
|------|------|
| Feb 23-28 | `pulse init` wizard + PyPI prep |
| Mar 1-7 | PyPI publish + ClawHub submission |
| Mar 8-14 | `pulse dashboard` + PH launch |
| Mar 15+ | Pro tier scoping based on usage |

---

## Immediate Next Actions (Josh + Iris, morning of Feb 23)

**Josh (30 min total):**
1. Run Supabase migration 002 (5 min) → unblocks 3D Internet
2. Deposit $400 Polymarket (30 min) → unblocks 4 trading systems
3. ClawHub account → submit when `pulse init` is ready

**Iris (this week, autonomous):**
1. Write `pulse init` wizard (CLI interactive setup)
2. Build `pulse dashboard` (rich terminal UI)
3. Test fresh-install flow on the iMac
4. Prep PyPI package metadata

---

*This is the gap between "Iris's nervous system" and "give your AI a heartbeat."*
*v0.2.5 proves the system works. v0.3.0 makes it installable. That's the whole game.*

---
*Iris — 2:19 AM, Day 24*
