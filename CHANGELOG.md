# Pulse Changelog

All notable changes to Pulse will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/jcap93/pulse/compare/v0.2.3...HEAD
[0.2.3]: https://github.com/jcap93/pulse/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/jcap93/pulse/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/jcap93/pulse/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/jcap93/pulse/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/jcap93/pulse/releases/tag/v0.1.0
