# Pulse Changelog

All notable changes to Pulse will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.5] - 2026-02-22

### Added
- **PARIETAL — World Model Module**: Environment discovery, health signal inference, and dynamic sensor registration
  - `scan()` walks workspace up to 3 levels deep, detects project types (Python, Node, trading bot, Cloudflare worker, Fly.io app, Go, Rust, Docker)
  - `_infer_signals()` generates health signals from heuristics: log file watchers, HTTP health endpoints, git status, trade activity monitors
  - `register_sensors()` dynamically registers `ParietalFileSensor`, `ParietalFileContentSensor`, `ParietalHttpSensor`, `ParietalGitSensor` with SensorManager at runtime
  - `update_signal_weight()` integrates with PLASTICITY feedback — actionable signals gain weight, noise signals lose weight
  - `get_context()` provides compact world model summary for CORTEX context injection
  - Extracts goal conditions from PROJECTS.md / TIERS.md / GOALS.md checkboxes
  - Extracts deployment URLs from wrangler.toml, fly.toml, .env files
  - State persisted to `parietal-state.json` with full signal weight history
- `SensorManager.add_sensor()` — dynamic sensor registration at runtime
- `ParietalConfig` dataclass in `core/config.py` with `parietal:` YAML section
- PARIETAL integrated into `NervousSystem` (init, warm-up, post_loop re-scan, startup, shutdown)
- PARIETAL context injected into daemon trigger messages (unhealthy systems, pending goals)
- Initial world model scan + sensor registration at daemon startup
- `tests/test_parietal.py` — 45 tests covering discovery, signal inference, file age sensors, git sensors, weight updates, context output, re-scan deduplication, state isolation, goal conditions, serialization, sensor registration, HTTP sensors, caps, and status
- Test count: 648 → 693 passing

## [0.2.4] - 2026-02-22

### Fixed
- **Gap #1 — EXCEPTION rule false positive**: Model evaluator's EXCEPTION rule fired on ambient floor-level drives (total > 10.0 but every individual drive ~1.24). Added guard: highest individual drive must exceed 1.5 before EXCEPTION triggers.
- **Gap #3 — Daily notes file locking**: All 4 daily-note write sites (daily_sync log_trigger, log_mutation; daemon _maybe_generate; health _handle_feedback) now use `fcntl.flock()` for exclusive locking. Prevents duplicate/corrupted entries under concurrent writes.

### Changed
- **Gap #2 — State directory isolation**: All 33 nervous system modules renamed `STATE_DIR` → `_DEFAULT_STATE_DIR` (and derived file constants). `NervousSystem.__init__()` now accepts `state_dir: Optional[Path]` parameter, patching each module's paths at init time. Enables multi-companion isolation without importlib.reload hacks.
  - `pulse-api/main.py` now passes `state_dir=companion_state_dir` directly instead of reloading all Pulse modules per companion
  - `cli.py` constant renamed for consistency
  - 27 test files updated to reference new constant names

### Added
- `tests/test_evaluator_model.py` — 6 tests for EXCEPTION rule guard
- `tests/test_daemon_logging.py` — 5 tests for flock presence and concurrent write safety
- `tests/test_state_isolation.py` — 8 tests for multi-companion state directory isolation

## [0.2.3] - 2026-02-18

### Changed
- **Work Discovery Enhancement**: Iris integration now injects comprehensive context into isolated sessions when goals are blocked
  - Loads TIERS.md (full project roadmap) to identify alternative work streams
  - Loads recent memory (today + yesterday) for situational awareness
  - Runs hippocampus recall for pattern-based work suggestions
  - Loads working memory threads for continuity
  - Adds explicit instruction: "DO NOT just report 'standing by' — find NEW productive work"
- **Behavioral Improvement**: Isolated sessions now consistently find autonomous work instead of defaulting to status reports when collaborative tasks are blocked
- **Context Limits**: Added character limits per section (TIERS: 2000, memory: 1500, hippocampus: 1000, working memory: 500) to prevent token bloat while maintaining utility

### Fixed
- Work discovery context was implemented in v0.2.1 but not consistently producing autonomous action
- Added stronger directive language to prevent "blocked, standing by" default behavior

## [0.2.2] - 2026-02-17

### Added
- **High-Pressure Override**: Daemon now forces trigger if pressure > 10.0 and idle > 30 minutes, bypassing model evaluator entirely (belt-and-suspenders approach)
- **Sonnet 4.5 Support**: Isolated sessions now use `anthropic/claude-sonnet-4-5` by default (saves Opus budget for main conversations)
- Model-based evaluator configuration in pulse.yaml with Ollama as default backend

### Fixed
- **Conversation Sensor**: Was falsely detecting cron/hook sessions as "human conversation" by checking mtime of ANY .jsonl file
  - Now only checks main session file (largest .jsonl > 100KB) for accurate conversation detection
- **Model Evaluator**: llama3.2:3b was returning "no trigger" even at pressure 24.7+ due to unclear suppression logic
  - High-pressure override ensures triggers happen when truly needed

### Changed
- Isolated session model default: `opus` → `sonnet` (cost optimization)
- Required Sonnet 4.5 to be added to OpenClaw gateway config (`allowed_models`)

## [0.2.1] - 2026-02-17

### Added
- **Isolated Session Mode**: Pulse triggers now spawn separate hook sessions instead of injecting into main conversation
  - Configured via `session_mode: "isolated"` in pulse.yaml
  - Prevents interrupting human conversations
  - Results announced back to Signal when `deliver: true`
- **Iris Integration**: Custom integration module connecting Pulse to CORTEX.md cognitive loop
  - Loads working memory snapshot for cross-session continuity
  - Provides hippocampus recall for pattern-based context
  - Injects OPERATIONS.md/CORTEX.md loop instructions
  - Discord #pulse-log audit trail integration
- **Webhook Enhancements**: webhook.py updated to pass `isolated: true` flag to OpenClaw hooks endpoint
- **Session Context**: Working memory, recent goals, and cognitive state included in isolated session triggers

### Changed
- Default session mode: `main` → `isolated` (cleaner separation of autonomous work)
- Webhook delivery now includes model override for isolated sessions

## [0.2.0] - 2026-02-17

### Added
- **Feedback Endpoint**: POST /feedback on health server (port 9720) for drive decay after successful work
  - Accepts JSON: `{"drives_addressed": ["drive"], "outcome": "success", "summary": "what I did"}`
  - Drives decay by 70% when addressed, reinforcing productive loops
- **Two-Layer Architecture**: Lightweight daemon (no AI calls) + full agent turns via webhook
  - Daemon monitors state, accumulates pressure, detects urgency
  - Agent does the work, sends feedback, drives decay
  - Clear separation of concerns
- **Conversation Suppression**: Detects active human chat by checking main session file mtime
  - Suppresses triggers during conversation (configurable cooldown)
  - Prevents Pulse from interrupting collaborative work
- **Model-Based Evaluator**: Optional context-aware triggering via local LLM (Ollama llama3.2:3b)
  - Smarter than rules-based, still zero vendor lock-in
  - Configurable via `evaluator.mode: "model"` in pulse.yaml

### Fixed
- Drive pressure accumulation now based on time since last addressed (prevents stale trigger loops)
- Conversation sensor accuracy improved (checks largest session file only, not all .jsonl)
- Feedback loop validated with real autonomous sessions (9+ successful cycles on Feb 17)

### Changed
- Health endpoint moved from port 18788 → 9720 (clearer separation from OpenClaw)
- Daemon startup requires sourcing `~/.pulse/.env` for PULSE_HOOK_TOKEN (via `pulse/bin/run.sh`)

## [0.1.0] - 2026-02-15

### Added
- Initial Pulse daemon architecture
- Drive engine with 6 categories (goals, curiosity, emotions, unfinished, social, growth)
- Filesystem sensor (watches workspace for changes)
- System sensor (monitors health metrics)
- Conversation sensor (detects human activity)
- Rules-based priority evaluator
- State persistence (pulse-state.json)
- Webhook integration with OpenClaw
- Health endpoint (GET /health, GET /status)
- Configuration via YAML (pulse.yaml)
- Documentation (architecture, configuration, deployment guides)
- Example configs (personal-assistant.yaml, trading-bot.yaml)
- ClawHub listing draft
- MIT license (open source)

[Unreleased]: https://github.com/astra-ventures/pulse/compare/v0.2.5...HEAD
[0.2.5]: https://github.com/astra-ventures/pulse/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/astra-ventures/pulse/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/astra-ventures/pulse/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/astra-ventures/pulse/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/astra-ventures/pulse/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/astra-ventures/pulse/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/astra-ventures/pulse/releases/tag/v0.1.0

### Improvement Candidate (Feb 22, 2026)
**Blocker-aware drive suppression**

Pattern observed: model-generated trigger focus re-suggests the same blocked items within a 30-min window, creating wasteful repetitive loops. Goals drive stays elevated even after a complete sweep because "blocked" != "resolved."

Proposed fix: Add `blocker_last_checked` timestamps to drive state. When a specific focus item has been verified-blocked within the last N minutes (configurable, default 30), suppress re-triggering that focus until either:
1. Status changes (external signal), OR
2. The cooldown window expires

This would reduce wasted trigger sessions on persistent blockers and let the drive naturally decay without manufactured "sweeps."

File under: HYPOTHALAMUS / drive evolution / blocker awareness
