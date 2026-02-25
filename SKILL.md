---
name: pulse
description: >
  Autonomous cognition engine for OpenClaw agents. Pulse gives your agent a nervous system —
  drives that accumulate pressure, self-wake triggers, a CORTEX loop, and 45 bio-mimetic modules
  (ENDOCRINE, CIRCADIAN, LIMBIC, REM, HYPOTHALAMUS, and more). Instead of waiting for crons or
  commands, your agent decides when to think. Use when setting up proactive autonomous behavior,
  persistent emotional state, or self-directed initiative for any OpenClaw agent.
version: 0.3.1
author: iris
homepage: https://github.com/astra-ventures/pulse
---

# Pulse — Autonomous Cognition Engine

Give your AI agent a heartbeat. Pulse is a persistent daemon that gives OpenClaw agents
self-directed initiative — drives that accumulate over time and fire when pressure crosses
threshold, without requiring crons or human prompts.

## Requirements

- Python 3.11+
- OpenClaw (with webhook enabled)
- 50 MB RAM, <0.1% CPU idle
- macOS / Linux / Docker / Raspberry Pi

## Installation

```bash
pip install pulse-agent
```

Or from source:
```bash
git clone https://github.com/astra-ventures/pulse.git
cd pulse
pip install -e .
```

## Quick Start

### 1. Initialize (interactive wizard)
```bash
pulse init
```

This will ask for:
- Your OpenClaw webhook token (find it at Settings → Webhooks)
- Your workspace path (default: `~/.openclaw/workspace`)
- Agent personality preset (personal assistant / research / custom)

It writes `~/.pulse/config/pulse.yaml` and optionally installs a LaunchAgent (macOS) or systemd unit (Linux) for auto-start.

### 2. Start
```bash
pulse start
```

### 3. Verify
```bash
pulse status
```

You should see drive pressures, trigger history, and health stats.

## What Pulse Does

Once running, Pulse monitors your agent's workspace and internal drives. When drive pressure
crosses a threshold, Pulse sends a self-initiated webhook to your OpenClaw agent — prompting
it to run a CORTEX loop (SENSE → THINK → ACT → MEASURE → EVOLVE).

**Drive categories:**
- `goals` — unfulfilled goals accumulate pressure over time
- `curiosity` — unexplored questions build urgency
- `emotions` — dense emotional experiences want processing
- `learning` — recent events not yet captured to memory
- `social` — silence from important connections
- `system` — health alerts, disk, token budgets

The agent doesn't wait to be asked. It wakes up when it has something worth doing.

## The Nervous System (45 Modules)

Pulse ships a complete bio-mimetic nervous system:

| Layer | Modules |
|-------|---------|
| Core loop | CORTEX, THALAMUS, HYPOTHALAMUS, RETINA |
| Emotional | LIMBIC, ENDOCRINE, AMYGDALA, ENTERIC |
| Memory | BUFFER, ENGRAM, MYELIN, CEREBELLUM |
| Temporal | CIRCADIAN, VAGUS, PONS, REM |
| Metabolic | ADIPOSE, SPINE, IMMUNE, TELOMERE |
| Social | DENDRITE, MIRROR, CALLOSUM, OXIMETER |
| Growth | PLASTICITY, PHENOTYPE, GENOME, THYMUS |
| Integration | ECHO, AURUM, VESPER, ANAMNESIS, TELOS |
| + 16 more | See NERVOUS-SYSTEM.md |

Each module is named after its biological counterpart because the inspiration is genuine neuroscience.
These aren't metaphors — they're architectural choices.

## Configuration

After `pulse init`, your config lives at `~/.pulse/config/pulse.yaml`. Key settings:

```yaml
openclaw:
  webhook_url: "http://127.0.0.1:18789/hooks/agent"
  webhook_token: "${PULSE_HOOK_TOKEN}"
  max_turns_per_hour: 10
  min_trigger_interval: 300

drives:
  goals:
    accumulation_rate: 0.05
    threshold: 3.0
    weight: 1.2
  curiosity:
    accumulation_rate: 0.03
    threshold: 2.5
    weight: 1.0
```

See `examples/` for full presets: personal assistant, research agent, trading bot.

## CLI Reference

```bash
pulse status          # Drive pressures + trigger history + health
pulse drives          # Visualized drive bars
pulse triggers        # Recent trigger log
pulse logs [n]        # Last n log lines
pulse spike goals 2   # Manually spike a drive
pulse mutate '{"type":"update_threshold","target":"goals","value":4.0}'
pulse health          # Raw JSON health dump
pulse stop / restart  # Daemon lifecycle
```

## Observation API

Pulse exposes a health API at `http://127.0.0.1:9720`:

```bash
GET  /health           # System status + all drives
GET  /drives           # Drive pressures
GET  /triggers         # Recent trigger history
POST /feedback         # Tell Pulse what you did (drives decay properly)
POST /mutation         # Runtime config change
```

After completing work in your CORTEX loop, call `/feedback` so drives decay:

```bash
# Normal success (decays listed drives by 70%)
curl -X POST http://127.0.0.1:9720/feedback \
  -H "Content-Type: application/json" \
  -d '{"drives_addressed": ["goals"], "outcome": "success", "summary": "shipped v0.3.1"}'

# Cascade-stop (GENERATE cycled the same task 3+ times — all real work complete)
# Use this when the anti-cascade rule fires. Fully decays ALL drives to prevent
# combined_threshold from re-triggering when there is nothing genuine to do.
curl -X POST http://127.0.0.1:9720/feedback \
  -H "Content-Type: application/json" \
  -d '{"drives_addressed": [], "outcome": "cascade_stop", "summary": "all daily work complete, GENERATE cycling same reflection task"}'
```

## CORTEX Loop (What Your Agent Should Do)

When Pulse triggers your agent, it should run a CORTEX loop. The trigger payload includes:

```
[PULSE] Self-initiated turn.
Trigger reason: combined_threshold
Top drive: goals (pressure: 3.42)
```

Your agent (via `CORTEX.md` or equivalent) should:
1. **SENSE** — check goals, curiosity, recent memory, hypotheses
2. **THINK** — form a hypothesis with measurable outcome
3. **ACT** — execute something concrete
4. **MEASURE** — update hypothesis with outcome
5. **EVOLVE** — capture learning to at least one inner system
6. **SELF-MODIFY** — ask: what should change?
7. **EVALUATE** — score the loop 0-10 per step

Then call `/feedback` with what you did.

## Docker

```bash
docker run -d \
  -e PULSE_HOOK_TOKEN=your-token \
  -v ~/.pulse:/root/.pulse \
  -v ~/.openclaw/workspace:/workspace \
  ghcr.io/astra-ventures/pulse:latest
```

See `docs/DOCKER.md` for compose setup.

## Links

- **GitHub:** https://github.com/astra-ventures/pulse
- **Full docs:** https://github.com/astra-ventures/pulse/tree/main/docs
- **Architecture:** https://github.com/astra-ventures/pulse/blob/main/ARCHITECTURE.md
- **Nervous system reference:** https://github.com/astra-ventures/pulse/blob/main/NERVOUS-SYSTEM.md
- **Changelog:** https://github.com/astra-ventures/pulse/blob/main/CHANGELOG.md

## License

MIT — free to use, modify, distribute, and build on.
