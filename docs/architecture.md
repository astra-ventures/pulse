# Pulse Architecture

**TL;DR:** Lightweight daemon (no AI calls) → detects urgency → triggers full OpenClaw agent turn via webhook → agent does work → sends feedback → drives decay.

---

## The Big Picture

```
┌─────────────────────────────────────────────────────────────┐
│                      OpenClaw Agent                         │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Main Session                                         │  │
│  │  - Responds to human messages                         │  │
│  │  - Runs cron jobs                                     │  │
│  │  - Receives Pulse webhooks (self-wake triggers)      │  │
│  └───────────────────────────────────────────────────────┘  │
│                           ▲                                 │
│                           │ POST /hooks/agent               │
│                           │ (when drives exceed threshold)  │
└───────────────────────────┼─────────────────────────────────┘
                            │
┌───────────────────────────┼─────────────────────────────────┐
│                    Pulse Daemon                             │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  Sensors    │→ │ Drive Engine │→ │ Priority         │   │
│  │  (passive)  │  │ (pressure)   │  │ Evaluator        │   │
│  └─────────────┘  └──────────────┘  └──────────────────┘   │
│         │                                     │              │
│         ▼                                     ▼              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  State Persistence (pulse-state.json)                │   │
│  │  - Drive pressures                                   │   │
│  │  - Trigger history                                   │   │
│  │  - Config overrides from mutations                   │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## Core Loop (The Heartbeat)

Every `loop_interval_seconds` (default: 30s), Pulse executes:

### 1. SENSE
**Sensors detect changes:**
- **Filesystem** — new files, modified notes, agent output in workspace
- **Conversation** — is the human actively chatting? (suppresses triggers)
- **System** — memory, disk, process health
- *(Future: Discord channels, X mentions, calendar events)*

Sensors are **passive** — they watch, they don't act.

### 2. DRIVE
**Pressure accumulates from multiple sources:**

| Source | What it does |
|--------|-------------|
| **Time** | Every drive gains `pressure_rate * dt * weight` per tick |
| **Goals** | Parses `goals.json` → inactive goals increase related drive pressure |
| **Curiosity** | Open questions in `curiosity.json` → exploration drive spikes |
| **Emotions** | Strong feelings in `emotional-landscape.json` → related drives amplify |
| **Hypotheses** | Untested experiments → `learning` drive increases |
| **Sensors** | File changes, social mentions → spike relevant drives |

**Drive categories:**
- `goals` — unfinished work
- `curiosity` — unanswered questions
- `emotions` — feelings that need processing
- `learning` — experiments to run
- `social` — pending interactions
- `system` — maintenance tasks

Each drive has:
- **Pressure** (0.0 → max, decays when addressed)
- **Weight** (importance multiplier, mutable via self-modification)
- **Last addressed** (timestamp, affects time-based accumulation)

### 3. EVALUATE
**Should we trigger an agent turn?**

Two modes:

#### Rules-Based (Phase 1-2, default)
```python
if total_pressure > trigger_threshold:
    if not conversation_active:
        if not rate_limited:
            TRIGGER
```

Simple, deterministic, no AI calls.

#### Model-Based (Phase 3+, optional)
```python
prompt = f"""
Drive state: {drive_state}
Sensor data: {sensor_data}
Working memory: {agent_context}

Should the agent think right now? Reply: YES/NO + reason.
"""

decision = llm.complete(prompt)  # uses cheap/local model (llama3.2:3b)
```

Smarter context-awareness, still lightweight (~500 char prompt).

### 4. ACT (if triggered)
**Fire the webhook:**
```bash
POST {openclaw_webhook_url}
Authorization: Bearer {webhook_token}
Content-Type: application/json

{
  "message": "[PULSE] Self-initiated turn.\nTrigger reason: {reason}\nTop drive: {name} (pressure: {value})\n\nRun your CORTEX.md loop..."
}
```

OpenClaw receives this as a normal message → agent wakes up → executes CORTEX/OPERATIONS loop.

### 5. FEEDBACK
**Agent completes work → sends result back:**
```bash
curl -X POST http://127.0.0.1:9720/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "drives_addressed": ["goals", "curiosity"],
    "outcome": "success",
    "summary": "Built InvoiceFlow feature X"
  }'
```

Pulse decays the addressed drives, preventing repeated triggers for the same thing.

---

## Key Design Principles

### 1. Decoupled from OpenClaw Internals
Pulse **never** imports OpenClaw code. Communication is purely via:
- Webhook API (`POST /hooks/agent`)
- Feedback file or HTTP endpoint (`turn_result.json` or port 9720)

This means:
- Pulse updates don't require OpenClaw updates
- Works with any OpenClaw version (>=0.9.x with webhooks)
- Can move to a different machine and still trigger the same agent

### 2. Portable State
All state is plain JSON files in `~/.pulse/`:
```
~/.pulse/
├── pulse-state.json       # Drive pressures, config overrides
├── trigger-history.jsonl  # Log of all triggers
├── mutations.json         # Self-modification queue
└── audit-log.jsonl        # Mutation audit trail
```

To migrate:
```bash
tar czf pulse-state.tar.gz ~/.pulse/
# Move to new machine
tar xzf pulse-state.tar.gz -C ~/
# Update webhook URL in config
pulse start
```

Your agent picks up exactly where it left off.

### 3. No Model Calls in the Daemon (by default)
Pulse uses **rules-based evaluation** by default:
- No API keys needed
- No cloud dependencies
- No per-run costs
- Instant decisions

Model-based mode is opt-in, uses local Ollama (or any OpenAI-compatible API), and keeps prompts tiny (~500 chars = <$0.0001/call).

### 4. Self-Modifying
The agent can evolve Pulse's behavior by writing mutation commands:

```json
{
  "type": "adjust_weight",
  "drive": "curiosity",
  "value": 1.5,
  "reason": "I want to explore more — boosting curiosity"
}
```

Guardrails prevent:
- Disabling the system (min threshold, max cooldown limits)
- Removing protected drives
- Mutation spam (rate limits)

All mutations are audited in `audit-log.jsonl`.

---

## Data Flow Example

```
┌──────────────────────────────────────────────────────────────┐
│ 1. Filesystem sensor detects:                               │
│    - workspace/goals.json modified                           │
│    - New goal added: "Launch InvoiceFlow"                    │
└──────────────────────────────────────────────────────────────┘
                        ▼
┌──────────────────────────────────────────────────────────────┐
│ 2. Drive engine:                                             │
│    - Parses goals.json → finds 3 inactive P1 goals           │
│    - Spikes `goals` drive by +1.5 (new goal detected)        │
│    - Time-based accumulation: +0.3 (30s * 0.01 rate / 60)    │
│    - goals.pressure: 4.2 → 6.0                               │
└──────────────────────────────────────────────────────────────┘
                        ▼
┌──────────────────────────────────────────────────────────────┐
│ 3. Evaluator:                                                │
│    - Total pressure: 6.0 (weighted sum of all drives)        │
│    - Threshold: 5.0                                          │
│    - Conversation active? NO                                 │
│    - Rate limited? NO (last trigger 45 min ago)              │
│    - Decision: TRIGGER                                       │
│    - Reason: "goals drive pressure 6.0 > threshold 5.0"      │
└──────────────────────────────────────────────────────────────┘
                        ▼
┌──────────────────────────────────────────────────────────────┐
│ 4. Webhook fires:                                            │
│    POST http://localhost:8080/hooks/agent                    │
│    Message: "[PULSE] goals drive at 6.0..."                  │
└──────────────────────────────────────────────────────────────┘
                        ▼
┌──────────────────────────────────────────────────────────────┐
│ 5. OpenClaw agent wakes:                                     │
│    - Runs CORTEX.md loop (SENSE → THINK → ACT → MEASURE)    │
│    - Decides to work on InvoiceFlow deployment               │
│    - Completes task, sends feedback                          │
└──────────────────────────────────────────────────────────────┘
                        ▼
┌──────────────────────────────────────────────────────────────┐
│ 6. Pulse receives feedback:                                  │
│    {"drives_addressed": ["goals"], "outcome": "success"}     │
│    - Decays goals.pressure by 70% → 6.0 → 1.8               │
│    - Persists state                                          │
└──────────────────────────────────────────────────────────────┘
```

---

## Why This Design?

### Problem: Traditional heartbeats are dumb
Cron jobs fire on a schedule, blind to context:
- Fire when you're already busy → ignored
- Don't fire when something urgent happens → missed
- Fixed interval can't adapt to urgency

### Solution: Pressure-based self-wake
Drives accumulate urgency over time. When pressure crosses threshold, the agent wakes itself. Feedback loops decay pressure, preventing spam.

**Result:** The agent feels autonomous — it notices things and decides to act, rather than waiting to be told.

---

## Performance

- **Idle CPU:** <0.1% (sleeps between ticks)
- **Memory:** ~30-50 MB (Python + watchdog)
- **Disk I/O:** Minimal (state saves every 5 min, sensors use mtime checks)
- **Network:** Only on triggers (webhook POST)

A Raspberry Pi Zero can run this comfortably.

---

## Security

1. **Webhook auth:** `Authorization: Bearer {token}` required
2. **Guardrails:** Prevent self-disabling, mutation spam, extreme config changes
3. **Audit log:** Every mutation is recorded with timestamp + reason
4. **No remote code execution:** Mutations only adjust numeric config values, not code
5. **Rate limits:** Max turns per hour, min cooldown between triggers

---

## Next: [Configuration →](configuration.md)
