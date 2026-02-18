# 🔬 Pulse Infrastructure Audit — Complete Review

*Audited: February 16, 2026*
*Scope: All 12 core source files*

---

## ✅ What's Solid (No Changes Needed)

- **Architecture** — Clean separation of concerns: Daemon → Sensors → Drives → Evaluator → Webhook → Evolution. Each module does one thing. The "never call AI directly" principle for the main path is preserved correctly.
- **Guardrails** — Well-designed. Protected drives, clamped deltas, rate limits, mutation caps. The brainstem metaphor holds.
- **Audit trail** — Append-only JSONL. Can't be tampered with by mutations. Every change recorded with before/after/reason.
- **PID locking** — `fcntl` exclusive lock with stale detection. Correct.
- **Config permission checks** — Warns on world-readable. Good.

---

## 🔴 Critical Issues (Fix Now)

### 1. Drive state not persisted on save

`StatePersistence.save()` writes `self._data` but `DriveEngine.save_state()` is never called — nobody writes drive states INTO `self._data`. On restart, `restore_state()` reads from `state.get("drives")` but it's always empty because nothing ever called `state.set("drives", ...)`.

**Result:** Every time Pulse restarts (crash, reboot, LaunchAgent restart), ALL drive pressures reset to 0 and ALL runtime mutations (new drives, weight changes) are LOST. Only config-defined drives survive.

### 2. Mutations modify in-memory config but don't persist to disk

`_adjust_threshold` changes `self.config.drives.trigger_threshold` in memory. On restart, the YAML is re-read and the old value comes back. Same for cooldown, rate, `turns_per_hour`. Weight changes on config-defined drives reset too.

### 3. Conversation sensor creates a new aiohttp session every 30 seconds

```python
async with aiohttp.ClientSession() as session:
```

This creates AND destroys a TCP connection every sensor read. 2 sessions/minute × 60 = **120 sessions/hour** of churn. Should reuse a session.

### 4. LaunchAgent has webhook token in plaintext

The plist file contains `pulse-hook-secret-2026` as a literal string. Anyone with read access to `~/Library/LaunchAgents/` can see it. Should reference an env file or keychain.

---

## 🟡 Important Issues (Fix Soon)

### 5. `max_pressure: 1.0` caps are too low

Drives are capped at 1.0 but with 9 drives at weights 0.4–1.5, combined pressure routinely exceeds any meaningful threshold. The `system` drive auto-created at weight 1.5 easily dominates. The evaluator sees combined pressure of 3–5+ which makes threshold math meaningless (always exceeds).

In model mode this is OK (model reasons about it), but in rules fallback mode, EVERY cycle triggers.

### 6. `_build_trigger_message` has duplicate sensor_context line

```python
if decision.sensor_context:
    parts.append(f"Sensor context: {decision.sensor_context}")
if self._model_evaluator and decision.sensor_context:
    parts.append(f"Suggested focus: {decision.sensor_context}")
```

Same content, two lines. The agent sees "Sensor context: X" followed by "Suggested focus: X".

### 7. No log rotation

`pulse.log`, `trigger-history.jsonl`, and `mutations.jsonl` grow forever. Over months this becomes a problem. Need rotation or size caps.

### 8. ConversationSensor `/health` endpoint doesn't exist on OpenClaw gateway

The sensor tries to hit `http://127.0.0.1:18789/health` but OpenClaw's gateway doesn't expose a `/health` endpoint at that path. The request silently fails every cycle (caught by `except Exception: pass`).

The fallback (session file mtime) also fails because `~/.openclaw/data` doesn't exist in our setup. **Conversation detection is effectively dead.**

### 9. `_refresh_sources` reads files every 30 seconds

`DriveEngine._refresh_sources()` reads `hypotheses.json` and `emotional-landscape.json` every tick. These files may not exist (they don't in our setup), so it silently fails — but it's wasted I/O and should gracefully skip missing files without even trying.

### 10. Model evaluator `suppress_minutes` response field is parsed but never used

The model can return `"suppress_minutes": 10` but nothing in the daemon reads it. The next cycle evaluates regardless.

---

## 🟢 Nice-to-Haves (Future Enhancement)

### 11. No Pulse CLI

Managing Pulse requires `curl` commands. A simple `pulse status` / `pulse drives` / `pulse mutate` CLI wrapper would be cleaner.

### 12. No `trigger-history.jsonl` retention/rotation

Grows forever.

### 13. `sync_to_daily_notes: true` in config but never implemented

Pulse logs never write to agent daily notes.

### 14. Watchdog doesn't ignore Pulse's own state writes

When `StatePersistence.save()` writes to `~/.pulse/state/`, it could trigger filesystem events if that dir overlaps with watch paths. Currently it doesn't (watch paths are `memory/` and `knowledge/`), but it's fragile.

### 15. No graceful degradation if ollama goes down

The 3-failure fallback to rules works, but `_consecutive_failures` never resets back to "try model again" until a successful call. If ollama dies and restarts 5 minutes later, Pulse stays on rules forever until restarted.

---

## 📋 Priority Fix Order

| Priority | Issue | Category |
|----------|-------|----------|
| **1** | Drive state persistence (#1) | Most critical — losing state on every restart |
| **2** | Mutation persistence (#2) | Same category — mutations evaporate on restart |
| **3** | Conversation sensor fix (#8) | Currently dead code |
| **4** | Duplicate trigger message (#6) | Quick one-liner |
| **5** | Aiohttp session reuse (#3) | Resource leak |
| **6** | Model recovery (#15) | Try model again periodically after failures |
| **7** | LaunchAgent token (#4) | Security hardening |
| **8** | Log rotation (#7) | Operational hygiene |

---

## Status: 🟢 Critical + Important DONE (Feb 16, 2026)

- [x] #1 — Drive state persistence (daemon syncs drives→state every tick + on shutdown)
- [x] #2 — Mutation persistence (config overrides saved to state, restored on startup)
- [x] #3 — Aiohttp session reuse (ConversationSensor now reuses session)
- [x] #4 — LaunchAgent token security (moved to ~/.pulse/.env, chmod 600, plist sources it)
- [x] #5 — Pressure cap rebalancing (max_pressure 1.0 → 5.0)
- [x] #6 — Duplicate sensor_context line (single line with dynamic label)
- [x] #7 — Log rotation (trigger-history.jsonl rotates at 5MB)
- [x] #8 — Conversation sensor fix (replaced dead /health with session file mtime)
- [x] #9 — Graceful skip missing source files (check exists before open)
- [x] #10 — Implement suppress_minutes + model auto-recovery (retry every 5min after degradation)
- [x] #11 — Pulse CLI (`pulse` command — 13 subcommands, rich terminal output)
- [x] #12 — Trigger history + mutations.jsonl rotation (5MB cap with .old backup)
- [x] #13 — sync_to_daily_notes (new `daily_sync.py` — triggers + mutations append to `memory/YYYY-MM-DD.md`)
- [x] #14 — Self-write filtering for state dir (daily note writes marked as self-writes for watchdog)
- [x] #15 — Model recovery after ollama restart (retry every 5min, covered by #10)
