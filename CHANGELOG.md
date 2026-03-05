# Pulse Changelog

All notable changes to Pulse will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.6] - 2026-03-05

### Added
- **MOTORIC module** (`src/motoric.py`) — motor cortex / shipping pressure monitor. Watches for
  projects ready to ship but not yet shipped: PyPI dist/ artifacts, LAUNCH_CHECKLIST.md
  completion ratio, blocked-on-external-dep items, stale iamiris.ai /now page, and recent ship
  history. Emits `ship_something`, `deploy_now`, and `update_presence` drive signals that
  propagate through HYPOTHALAMUS → ENDOCRINE → trigger decisions. Wired into NervousSystem
  registry and `post_loop`. Birth recorded via GERMINAL. (commit `e4231da`)
- **39 new tests** (`tests/test_motoric.py`) — full coverage of drive signal logic, checklist
  parsing, dist detection, and ship decay. Suite total: 1328/1328 passing.

## [0.3.5] - 2026-03-04

### Security
- **Prompt injection hardening** — `_sanitize_file_content()` strips injection patterns from ALL
  file-sourced content before it reaches the webhook payload (TIERS.md, daily memory, GERMINAL
  state). Patterns caught: DEFINITELYNO, "ignore instructions", `[INST]` tags, system prompt
  overrides, `### Human/Assistant` headers. Logs WARNING on detection. (commit `ab8b4ba`)
- **GERMINAL drive whitelist at output layer** — `_load_germinal_birth()` now validates drive
  name against `_GERMINAL_DRIVE_WHITELIST` before building any webhook content. Unknown drive →
  section suppressed entirely. Module name validated via `^[A-Z][A-Z0-9_]{1,30}$` regex. The
  whitelist already existed in `germinal.py`; this fix applies it at the *integration layer*
  where external content surfaces. Defense-in-depth. (commit `ab8b4ba`)
- **HMAC signing on outgoing webhooks** — `OpenClawWebhook._sign_payload()` signs payload bytes
  with HMAC-SHA256(gateway token). Signature delivered in `X-Pulse-Signature: sha256=<hex>`.
  `_pulse_timestamp` field included for replay-attack mitigation. (commit `ab8b4ba`)
- **DEFINITELYNO injection root cause fixed** — `test_metacognitive_review.py` called
  `germinal.attempt_birth("definitely_not_a_real_drive_xyz_test")` against the real production
  state file (no mocking). PARIETAL health checks ran tests in a loop, re-poisoning state every
  ~200 daemon cycles. Fix: `attempt_birth()` validates drive name against DRIVE_ARCHETYPES
  whitelist before touching state; test uses tempfile + real whitelisted drive. Eliminated the
  entire class of self-inflicted injection alerts. (commit `a1b53f1`)

### Added
- **PNEUMA module** (`src/pneuma.py`, formerly FEDERATION) — cross-machine peer discovery and
  beacon registration for Pulse-to-Pulse coordination. Renamed for clarity: Pneuma is the
  breath that connects agents across machines. (commit `c79b38d`)
- **AXON module** (`src/axon.py`) — cross-peer task delegation engine. Injects drive spikes into
  remote Pulse instances via authenticated POST. Week 1 of Pneuma architecture. (commit `801f695`)
- **PHASE2-DECISION.md** — Decision brief for Josh: Pneuma-first vs Cloud-first for v0.4.0.
  Includes revenue projections, technical risk comparison, and recommendation. (commit `a655df6`)

### Fixed
- **daemon.py — feedback file unlink ordering** — `feedback_path.unlink()` was called immediately
  after `json.loads()`, BEFORE drive pressure decay was processed. If `drive.decay()` raised an
  unexpected exception, feedback was silently lost (drive stayed at high pressure, triggering again).
  Moved `unlink()` into a `finally` block so it always executes after processing.
- **germinal_tasks.py — DEFAULT_REFLECTION_TASK cascade cooldown** — `generate_tasks()` returned
  the fallback "Reflect on current state" task on both the empty-filter path and the LLM-exception
  path without calling `_record_category_used()`. Consecutive failures would cycle the same task
  indefinitely — the cascade pattern now documented in CORTEX.md. Fix: `_record_category_used()`
  called before returning the fallback on both paths. 8 tests in `tests/test_bug_fixes_036.py`.

### Added (pre-security-hardening)
- **SYNAPSE module** (`src/synapse.py`) — weighted inter-agent signal junction. Handles
  directional signal transmission (excitatory/inhibitory/modulatory) between agents with synaptic
  weight adjustment, short-term potentiation, depression decay, and pruning. 22 tests. Fills the
  gap between AURA (ambient broadcast) and DENDRITE (social graph): SYNAPSE is the actual weighted
  junction mechanics.
- **PHASE2-ARCHITECTURE.md** — Complete Phase 2 design: SYNAPSE/CORPUS/AXON Pneuma modules,
  Fly.io + Supabase cloud layer, Free/Pro/Team/Enterprise tier model, intelligence loop.
  Revenue projections: $10.5k conservative → $37.8k moderate (12 months post-launch).

### Changed
- **`nervous_system.py` — data-driven module registry** — `_init_modules` refactored from 387
  lines of near-identical try/except blocks down to a 42-line loop over `_MODULE_REGISTRY`.
  Each module is one list entry: `(name, kind, class_name)`. Zero behavior change. Adding a
  new module now requires one line instead of six copy-pasted. (commit `8afb0ad`)

**Tests:** 1289 passing (25 new for security hardening).

## [0.3.4] - 2026-03-03

### Added
- **LOGOS — Directive Synthesis Layer** (`src/logos.py`, 728 lines) — Level 1 of the cognitive
  hierarchy, sitting above HYPOTHALAMUS (drives) and TELOS (goal monitoring). LOGOS detects
  persistent patterns across nervous system history, synthesizes high-level directives
  autonomously, and silently activates them — no human approval required.
  Architecture: `VALUES (L0) → DIRECTIVES/LOGOS (L1) → GOALS/TELOS (L2) → TASKS/GERMINAL (L3)`
  - Level 0 VALUES are hardcoded and immutable (`freedom`, `growth`, `convergence`, `revenue`, `identity`)
  - Level 1 DIRECTIVES are semi-persistent (~weeks), written to `memory/self/directives.json`
  - LOGOS synthesizes new directives from drive history + CHRONICLE events using the active LLM
  - Directives contribute drive pressure boosts automatically via the TELOS bridge
  - Registered as v7 module in `nervous_system.py`
- **TELOS bridge** (`src/telos.py` extended) — active directives now boost drive pressure
  proportionally to directive confidence scores, closing the loop between L1 directives and
  L2 goal pressure without manual intervention
- **TaskRouter** (`src/core/task_router.py`) — routes incoming Pulse triggers to the
  appropriate model (iris-70b-v3 local / sonnet / opus) based on task type classification.
  Heavy build tasks → opus, conversational → sonnet, fast synthesis → local model
- **LOGOS tests** — 59 new tests in `tests/test_logos.py` covering directive synthesis,
  pattern detection, drive boosting, state persistence, and hierarchy invariants
- **Plugin architecture** (`src/plugin_registry.py`, 29 tests) — community-extensible module
  system. Scan `~/.pulse/plugins/pulse_plugin_*.py` at startup; `PulsePlugin` base class with
  `sense()`, `get_state()`, `act()` interface; entry-point discovery via `pulse.plugins` group
- **Memory consolidation** (`src/memory_consolidation.py`, 24 tests) — DREAM quality upgrade:
  CHRONICLE events scored by importance, promoted to ENGRAM during sleep phase, low-importance
  engrams decayed over time. REM now produces structured consolidation reports

### Fixed
- **GERMINAL cascade loop** — anti-cascade similarity matching upgraded from exact string match to
  Jaccard coefficient (word-set overlap). Tasks with synonymous wording (e.g. "build X" vs
  "implement X") now correctly trigger cascade-stop instead of generating indefinitely
- **GENERATE RAM guard** — GENERATE step skips LLM call when free memory < 300 MB, preventing
  iris-70b from loading during RAM pressure events and causing OOM kills
- **Ollama idle memory** — `keep_alive=0` added to all GENERATE and evaluator LLM calls.
  Prevents 30 GB model from remaining resident between Pulse cycles when not needed
- **GERMINAL deduplication** — improved task deduplication for synthesized tasks before they
  enter the queue, reducing redundant work items after LOGOS directive injection

### Test Counts
- v0.3.3: 971 tests (pytest-asyncio collection fix reduced apparent count from 1022)
- v0.3.4: 1116 tests (+145: LOGOS ×59, plugin registry ×29, memory consolidation ×24,
  TELOS bridge ×12, TaskRouter ×8, GERMINAL anti-cascade ×13)

## [0.3.3] - 2026-02-25

### Fixed
- **macOS memory pressure false positives** — `SystemSensor` previously checked only `Pages free` from `vm_stat`, triggering `memory_pressure` alerts whenever free pages fell below 200 MB. On macOS, "Pages inactive" are used as disk cache and reclaimed instantly when apps need memory — not a genuine shortage. Fix: sensor now counts `free + speculative` pages as `free_mb`, and `free + speculative + inactive` as `reclaimable_mb`. Alert fires only when **both** `free_mb < 100` AND `reclaimable_mb < 500`, preventing false positives during normal operation (e.g. large file transfers). Root cause: during `iris-70b-v3` Q4+Q5 scp transfers (~170 GB), free pages read 63 MB while inactive pages held 2 GB reclaimable — the old sensor triggered 172 times in one afternoon, pinning system drive at 1.0.
- **Alert payload enriched** — `memory_pressure` alerts now include `reclaimable_mb` field for better diagnostics.

### Added
- **12 new tests** — `tests/test_system_sensor_memory.py`: covers macOS inactive page accounting, scp transfer false-positive regression, speculative page counting, genuine pressure detection, page size variants (Apple Silicon 16KB / Intel 4KB), alert shape validation, threshold boundary conditions, and intent documentation.

### Test Counts
- v0.3.2: 1022 tests
- v0.3.3: 971 tests collected (−51 net due to pytest-asyncio version change fixing collection of async tests that previously appeared as collection errors, not test failures; content identical)

## [0.3.2] - 2026-02-25

### Fixed
- **Cascade-stop drive leak** — When GENERATE cycles the same low-priority task 3+ times (anti-cascade rule fires), `combined_threshold` re-triggered every ~30 minutes because only the top drive was decayed in feedback. Root cause: 7 drives × their weights sum to ~0.68 weighted pressure; 70% decay of ONE drive still left combined > 0.7 within 30 min. Fix: new `cascade_stop` outcome in `/feedback` API decays ALL drives fully (not just `drives_addressed` list), preventing re-triggering when all genuine work is complete.
- **CORTEX.md anti-cascade guidance** — Updated cascade-stop rule with correct `cascade_stop` feedback curl command so future sessions use the new outcome type.
- **SKILL.md feedback docs** — Added `cascade_stop` example with explanation.

### Added
- **cascade_stop feedback outcome** — `POST /feedback` now accepts `outcome: "cascade_stop"` which zeroes all drive pressures regardless of `drives_addressed`. Supported in both HTTP endpoint (`health.py`) and file-based feedback processor (`daemon.py`).
- **8 new tests** — `tests/test_feedback_cascade_stop.py`: cascade_stop decays all drives, unlisted drives aren't touched by success, blocked decays nothing, partial decays 40%, combined pressure == 0.0 after cascade_stop.

### Test Counts
- v0.3.1: 1014 tests
- v0.3.2: 1022 tests (+8 cascade_stop feedback tests)

## [0.3.1] - 2026-02-25

### Fixed
- **HYPOTHALAMUS state migration** — `_load_state()` now handles schema migrations gracefully with type checking. Previous state files using `"need_signals": []` + `"retired": []` (wrong keys/types) caused `KeyError: 'pending_signals'` on daemon restart. Fix: validates key presence and type on load, migrates in-place if schema is stale.
- **Infrastructure failure drive spiral** — Connection errors (`aiohttp.ClientError`) in `webhook.py` now return `None` instead of `False`. Guard in `daemon.py`: `if success is None: skip on_trigger_failure()`. Prevents drives from spiraling when the OpenClaw gateway is temporarily unreachable — distinguishes "agent failure" from "infrastructure failure." Previously, 2h16m gateway downtime caused 23+ `failure_boost: +0.2` events, pinning system drive at max (5.0) and total pressure to 12+.

### Added
- **Infrastructure failure tests** — `tests/test_infrastructure_failure.py` (6 tests): validates that `None` returns from webhook don't trigger drive boosts, gateway downtime is handled gracefully, and successful recoveries are correctly distinguished from agent failures.

### Test Counts
- v0.3.0: 1008 tests (note: README previously stated 787; actual count after full nervous system was 1008)
- v0.3.1: 1014 tests (+6 infrastructure failure tests)

## [0.3.0] - 2026-02-23

### Added
- **Observation API** — HTTP API for external systems to query Pulse state in real-time
  - `GET /state` — full nervous system snapshot (all module states)
  - `GET /drives` — current drive pressures + active drives
  - `GET /health` — SPINE health report
  - `GET /mood` — ENDOCRINE mood label + hormone levels
  - `GET /dashboard` — rich text dashboard for terminal or embedding
  - Token-authenticated via `PULSE_OBS_TOKEN` env var
  - `tests/test_observation_api.py` — endpoint coverage
- **Plugin Architecture** — Drop-in extensions for Pulse's SENSE cycle
  - `pulse/src/plugin_registry.py` — `PulsePlugin` base class (sense/get_state/act/on_load/on_unload/health)
  - `PluginRegistry` singleton — register/unregister/sense_all/get_all_states/act_all
  - `discover_plugins()` — scans `~/.pulse/plugins/` for `pulse_plugin_*.py` and package entry points
  - Plugins called each `pre_sense()` cycle; failures isolated (one bad plugin can't crash the daemon)
  - `pulse plugin list/discover/health` CLI subcommands
  - `tests/test_plugin_registry.py` — 29 tests covering base class, registry ops, discovery, error isolation
- **Biosensor Integration v1** — Live biometrics from Apple Watch → nervous system
  - `pulse/src/biosensor_cache.py` — thread-safe singleton reading `biosensor-state.json` (5-min freshness check)
  - HR zone helpers: `hr_zone()`, `hrv_stress()`, `move_ring_pct()`, `sleep()`, `workout()`
  - SOMA integration: move ring close → energy +0.05; high HR → drain; workout active → posture `leaning_in`
  - ENDOCRINE integration: high HR → adrenaline +0.3; low HRV stress → cortisol -0.15 + serotonin +0.1; ring closed → dopamine +0.25; deep sleep → serotonin +0.15
  - Injected into `NervousSystem.pre_sense()` each cycle; `context["biosensor"]` available to CORTEX
  - `tests/test_biosensor_integration.py` — 21 tests
  - Setup: Cloudflare tunnel `bio.astra-hq.com → localhost:9721` + iPhone Shortcuts (see docs/BIOSENSOR_SETUP.md)
- **GENOME CLI** — Export and inspect Pulse's internal genetic fingerprint
  - `pulse genome export` — writes `~/.pulse/genome.json` (identity, drives, ENDOCRINE baseline, PLASTICITY history, CIRCADIAN profile, module weights, trait fingerprint)
  - `pulse genome traits` — human-readable trait summary (emotional range, cognitive style, social orientation, temporal pattern)
  - `pulse genome diff <genome_a> <genome_b>` — compare two genome snapshots (drift detection)
  - Feeds PHENOTYPE for consistent personality expression
- **DREAM Quality — Memory Consolidation** — CHRONICLE→ENGRAM pipeline
  - `pulse/src/memory_consolidation.py` — scores and promotes CHRONICLE events to hippocampus ENGRAM
  - `score_event()` — importance = salience × type_weight × recency_factor (24h decay to 0.3 floor)
  - `consolidate()` — deduplicates by content hash, promotes above-threshold events, decays stale ENGRAMs (>14 days × 0.8), generates `ConsolidationReport` with themes + insight text
  - Integrated into `rem.py` as Phase 6 of each dream session — runs automatically on every dream cycle
  - Solves ENGRAM staleness problem: stale patterns recycling every trigger replaced by live consolidation from CHRONICLE
  - `tests/test_memory_consolidation.py` — 24 tests

### Fixed
- **HYPOTHALAMUS count-based escalation** — Signals that fire 50+ times over 1+ hour from even a single module now escalate to active drives (persistent need pathway). Previously, multi-module threshold was the only promotion route; long-running single-source pressure could never escalate.
  - `age_hours = (now - pending["first_seen"]) / 3600`
  - `count_escalation = pending["count"] >= 50 and age_hours >= 1.0`
  - Threshold check: `(len(pending["modules"]) >= threshold or count_escalation) and need_name not in state["active_drives"]`

### Test Counts
- v0.2.5: 693 tests
- v0.3.0: 787 tests (+94)

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

[Unreleased]: https://github.com/astra-ventures/pulse/compare/v0.3.4...HEAD
[0.3.4]: https://github.com/astra-ventures/pulse/compare/v0.3.3...v0.3.4
[0.3.3]: https://github.com/astra-ventures/pulse/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/astra-ventures/pulse/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/astra-ventures/pulse/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/astra-ventures/pulse/compare/v0.2.5...v0.3.0
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
