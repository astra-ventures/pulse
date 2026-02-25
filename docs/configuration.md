# Pulse Configuration

All configuration lives in `config/pulse.yaml` (or `~/.pulse/config.yaml`).

---

## Quick Start

```bash
# Copy the example config
cp config/pulse.example.yaml config/pulse.yaml

# Edit the required fields
nano config/pulse.yaml
```

**Required:**
- `openclaw.webhook_url` — your OpenClaw webhook endpoint
- `openclaw.webhook_token` — auth token (set in OpenClaw gateway config)

**Optional but recommended:**
- `daemon.integration` — set to `"iris"` if using Iris-style workspace, or `"default"`
- `workspace.root` — path to your OpenClaw workspace

---

## Full Reference

### OpenClaw Integration

```yaml
openclaw:
  webhook_url: "http://localhost:8080/hooks/agent"
  webhook_token: "${PULSE_HOOK_TOKEN}"  # or hardcode (not recommended)
  min_trigger_interval: 1800  # seconds (30 min cooldown between triggers)
  max_turns_per_hour: 10      # rate limit to prevent runaway triggers
```

**Environment variable expansion:**
- `${VAR_NAME}` resolves to `os.environ["VAR_NAME"]`
- Useful for keeping secrets out of git
- Example: `export PULSE_HOOK_TOKEN=your-secret-token`

### Daemon

```yaml
daemon:
  loop_interval_seconds: 30     # how often to check drives
  health_port: 9719              # HTTP status endpoint
  integration: "default"         # "default", "iris", or custom module path
  log_level: "INFO"              # DEBUG, INFO, WARNING, ERROR
```

**Integration types:**
- `default` — generic OpenClaw setup
- `iris` — Iris-specific workspace layout (goals.json, curiosity.json, etc.)
- Custom: `"mypackage.integrations.custom"` (must subclass `Integration`)

### Drives

```yaml
drives:
  trigger_threshold: 5.0        # total weighted pressure to trigger
  pressure_rate: 0.01           # pressure added per minute per drive
  max_pressure: 20.0            # ceiling for any single drive
  decay_on_success: 0.7         # multiply pressure by 0.3 on successful turn
  decay_on_failure: 0.3         # multiply pressure by 0.7 on failed turn
  
  categories:
    goals:
      weight: 1.0
      sources:
        - "goals.json"
    
    curiosity:
      weight: 0.8
      sources:
        - "curiosity.json"
    
    emotions:
      weight: 1.2
      sources:
        - "emotional-landscape.json"
    
    learning:
      weight: 0.9
      sources:
        - "hypotheses.json"
    
    social:
      weight: 0.7
      sources:
        - "x_notifications.json"  # example: X mentions
    
    system:
      weight: 0.6
      sources:
        - "/var/log/system.log"   # example: system health
```

**How drives work:**
- Each category has a **weight** (importance multiplier)
- **Sources** are files that Pulse watches for changes
- When a source file changes, the drive spikes
- Over time, drives accumulate pressure at `pressure_rate * weight`
- When **total weighted pressure** > `trigger_threshold`, a turn triggers

**Tuning tips:**
- Higher `trigger_threshold` → fewer, more urgent triggers
- Higher `pressure_rate` → faster pressure accumulation (more sensitive)
- Adjust weights to prioritize certain drives (e.g. `goals: 1.5` if revenue is critical)

### Sensors

```yaml
sensors:
  filesystem:
    enabled: true
    watch_paths:
      - "."                      # workspace root
      - "memory/*.md"
      - "projects/*/README.md"
    ignore_patterns:
      - "*.pyc"
      - "__pycache__"
      - ".git/*"
      - "node_modules/*"
    debounce_seconds: 2.0        # wait 2s after last change before reporting
  
  conversation:
    enabled: true
    session_file: "memory/main-session.txt"  # OpenClaw main session log
    activity_threshold_seconds: 300          # consider "active" if < 5 min since last message
    size_threshold_kb: 100                   # only check if file > 100 KB (performance)
  
  system:
    enabled: true
    check_interval_seconds: 60   # how often to check memory/disk
    memory_threshold_mb: 100     # warn if daemon uses > 100 MB
    disk_threshold_gb: 5         # warn if < 5 GB free
  
  discord:
    enabled: false
    channels:
      - "1234567890"             # Discord channel IDs to monitor
    silence_threshold_minutes: 60  # spike social drive if no messages in 1hr
```

**Filesystem sensor:**
- Uses watchdog library (efficient, event-driven)
- `watch_paths` can be relative (to workspace) or absolute
- Globs supported: `"memory/*.md"`, `"projects/*/src/**/*.py"`
- `debounce_seconds` prevents spam from rapid file edits

**Conversation sensor:**
- Monitors OpenClaw session file size + mtime
- Suppresses triggers when human is actively chatting
- Only processes large files (avoids reading 5 MB logs every 30s)

**System sensor:**
- Monitors Pulse daemon's own health
- Warns if memory leak or disk full

**Discord sensor (future):**
- Not yet implemented
- Config is parsed but ignored
- Will spike `social` drive when channels go silent

### Evaluator

```yaml
evaluator:
  mode: "rules"  # "rules" or "model"
  
  model:
    base_url: "http://localhost:11434/v1"  # Ollama, OpenAI, Groq, etc.
    api_key: "${OPENAI_API_KEY}"           # or empty string for Ollama
    model: "llama3.2:3b"                   # small, fast, cheap
    max_tokens: 100
    temperature: 0.3
    timeout_seconds: 5
```

**Rules mode (default):**
- No AI calls
- Simple threshold math: `total_pressure > trigger_threshold`
- Fast, deterministic, free

**Model mode (advanced):**
- Uses a small LLM to decide if agent should wake
- Prompt includes: drive state, sensor data, working memory
- ~500 char prompt → <$0.0001/call with llama3.2:3b
- Useful for context-aware triggering (e.g. "don't wake me for minor file changes during office hours")

**Recommended model providers:**
- **Ollama (local):** Free, private, fast. `ollama pull llama3.2:3b` and set `base_url: "http://localhost:11434/v1"`
- **Groq:** Fastest cloud option, generous free tier
- **OpenAI:** Works but overkill (and expensive) for this use case

### Workspace

```yaml
workspace:
  root: "/Users/iris/.openclaw/workspace"  # absolute path to OpenClaw workspace
  resolve_paths: true                      # make all paths relative to root
```

**Why this matters:**
- Drive sources like `"goals.json"` resolve to `{root}/goals.json`
- Portable configs: same YAML works on different machines (just update `root`)

### State

```yaml
state:
  dir: "~/.pulse"              # where to store state files
  save_interval: 300           # seconds between auto-saves (5 min)
  max_history_entries: 1000    # trigger-history.jsonl max lines
```

**State files:**
- `pulse-state.json` — current drive pressures, config overrides
- `trigger-history.jsonl` — log of all triggers (timestamp, reason, outcome)
- `mutations.json` — pending self-modification commands
- `audit-log.jsonl` — record of applied mutations

### Logging

```yaml
logging:
  level: "INFO"                # DEBUG, INFO, WARNING, ERROR
  format: "structured"         # "structured" (JSON) or "text"
  output: "stdout"             # "stdout", "file", or "/path/to/pulse.log"
  sync_to_daily_notes: true    # append trigger logs to memory/YYYY-MM-DD.md
  daily_notes_dir: "memory"    # relative to workspace root
```

**Structured logging:**
```json
{"timestamp": 1234567890, "level": "INFO", "event": "trigger", "turn": 5, "reason": "goals pressure 6.2"}
```

**Text logging:**
```
2026-02-18 00:27:13 INFO     🫀 PULSE TRIGGER #5 — reason: goals pressure 6.2
```

**Daily notes sync:**
- Appends trigger events to today's memory file
- Format: `- 00:27 ✅ Trigger #5: goals pressure 6.2 (drive: goals, pressure: 6.2)`
- Useful for agents that use daily notes as working memory

---

## Tuning for Your Use Case

### High-frequency monitoring (trading bots, alerts)
```yaml
daemon:
  loop_interval_seconds: 10  # check every 10s

drives:
  trigger_threshold: 3.0      # lower threshold
  pressure_rate: 0.05         # faster accumulation

openclaw:
  min_trigger_interval: 300   # 5 min cooldown (vs default 30 min)
  max_turns_per_hour: 20      # allow more frequent triggers
```

### Low-frequency background agent (personal assistant)
```yaml
daemon:
  loop_interval_seconds: 60   # check every minute

drives:
  trigger_threshold: 7.0       # higher threshold (fewer triggers)
  pressure_rate: 0.005         # slower accumulation

openclaw:
  min_trigger_interval: 3600   # 1 hour cooldown
  max_turns_per_hour: 5        # conservative rate limit
```

### Battery-powered device (Raspberry Pi, laptop)
```yaml
daemon:
  loop_interval_seconds: 120   # check every 2 minutes

sensors:
  filesystem:
    debounce_seconds: 10.0     # longer debounce = fewer wakeups
  system:
    check_interval_seconds: 300  # check health every 5 min

drives:
  trigger_threshold: 10.0       # very high threshold
```

---

## Environment Variables

Pulse respects these env vars:

```bash
# Override config file location
export PULSE_CONFIG=/path/to/custom-config.yaml

# Webhook token (recommended: keep out of git)
export PULSE_HOOK_TOKEN=your-secret-token

# Log level (DEBUG, INFO, WARNING, ERROR)
export PULSE_LOG_LEVEL=DEBUG

# State directory
export PULSE_STATE_DIR=~/.pulse-custom
```

---

## Config Validation

Pulse validates config on startup:

```bash
pulse validate
```

Checks:
- Required fields present
- Numeric ranges valid
- File paths exist
- Webhook URL reachable
- Model API accessible (if `evaluator.mode: "model"`)

---

## Dynamic Updates (Self-Modification)

The agent can change config at runtime by writing mutations:

```json
{
  "type": "adjust_threshold",
  "value": 7.5,
  "reason": "I'm getting triggered too often — raising threshold"
}
```

**Supported mutations:**
- `adjust_threshold` — change `drives.trigger_threshold`
- `adjust_rate` — change `drives.pressure_rate`
- `adjust_weight` — change a drive category's weight
- `adjust_cooldown` — change `openclaw.min_trigger_interval`
- `adjust_turns_per_hour` — change `openclaw.max_turns_per_hour`

**Guardrails:**
- Threshold: `[0.5, 50.0]`
- Rate: `[0.001, 1.0]`
- Weight: `[0.0, 5.0]`
- Cooldown: `[60, 7200]` seconds
- Max mutations: 10/hour

All mutations are logged in `audit-log.jsonl`.

---

## Next Steps

- [Architecture](architecture.md) — how Pulse works
- [Deployment](deployment.md) — production setup
- [Examples](../examples/) — sample configs
