# Pulse v0.1.0 — Comprehensive Audit Report

**Auditor:** Iris (automated deep review)  
**Date:** 2026-02-16  
**Scope:** All 17 source + config files  
**Verdict:** Solid design, several critical bugs that need immediate attention before running in production.

---

## Table of Contents

1. [🔴 Critical — Fix Now](#-critical--fix-now)
2. [🟡 Important — Fix Soon](#-important--fix-soon)
3. [🟢 Nice-to-Have — Future](#-nice-to-have--future)
4. [🚀 Performance Improvements](#-performance-improvements)
5. [🏗️ Architecture Recommendations](#️-architecture-recommendations)

---

## 🔴 Critical — Fix Now

### C1. Pressure Rate Is Per-Second, Config Comments Say Per-Minute

**File:** `src/drives/engine.py` line ~100, `config/pulse.yaml` line ~40  
**What:** `Drive.tick()` does `self.pressure += rate * dt * weight` where `dt` is in **seconds** (from `time.time()` delta). But `pulse.yaml` documents `pressure_rate` as "per minute."  
**Why it matters:** With `rate=0.01`, `weight=1.0`, and a 30s loop, each tick adds `0.01 × 30 × 1.0 = 0.3` pressure. A drive goes from 0 → 0.7 (trigger threshold) in ~70 seconds. This is 60× faster than the config comment implies. The daemon will trigger far more aggressively than intended.  
**Fix:** Either divide by 60 in the tick, or fix the comment. Dividing is safer since the config value was chosen with "per minute" semantics:

```python
# In Drive.tick():
def tick(self, dt: float, rate: float, max_pressure: float):
    """Accumulate pressure over time. Rate is per-minute."""
    self.pressure = min(max_pressure, self.pressure + (rate * (dt / 60.0) * self.weight))
```

---

### C2. Async Cleanup Fails — Event Loop Already Closed

**File:** `src/core/daemon.py` lines ~211–225 (`_cleanup`)  
**What:** After `asyncio.run(self._main_loop())` returns, the event loop is **closed**. The `_cleanup` method then calls `asyncio.get_event_loop()` + `loop.run_until_complete()`, which will raise `RuntimeError: Event loop is closed`.  
**Why it matters:** The webhook `aiohttp.ClientSession`, health server, and model evaluator session are **never properly closed**. This causes ResourceWarning on every shutdown and could leak TCP connections.  
**Fix:** Move async cleanup inside the main loop's shutdown path:

```python
async def _main_loop(self):
    await self.sensors.start()
    await self.health.start()
    self.state.load()
    self.drives.restore_state()
    # ... restore overrides ...

    try:
        while self.running:
            # ... loop body ...
    finally:
        # Cleanup async resources INSIDE the loop
        await self.webhook.close()
        await self.health.stop()
        if self._model_evaluator and hasattr(self.evaluator, 'close'):
            await self.evaluator.close()
        # Stop watchdog observer
        for sensor in self.sensors.sensors:
            if hasattr(sensor, '_observer') and sensor._observer:
                sensor._observer.stop()

def _cleanup(self):
    """Cleanup on shutdown — sync-only tasks."""
    self.state.set("drives", self.drives.save_state())
    self.state.save()
    # Release PID lock...
```

---

### C3. Mutation Queue TOCTOU Race — Mutations Lost or Duplicated

**File:** `src/evolution/mutator.py` lines ~68–80 (`process_queue`)  
**What:** The mutator reads `mutations.json`, then immediately writes `"[]"` to clear it. Meanwhile, the CLI (or agent) can write to the same file. Three failure modes:
1. **Lost mutation:** Agent writes between daemon's read and clear → write is overwritten by `"[]"`
2. **Duplicate mutation:** CLI reads queue, daemon reads+clears, CLI writes back old+new → old mutations re-processed
3. **Corrupt file:** Concurrent writes produce invalid JSON  

**Why it matters:** This is a data loss bug in the core self-modification pipeline. Mutations are the agent's primary means of evolution — losing them silently is unacceptable.  
**Fix:** Use `fcntl.flock()` for file locking, matching the PID file pattern:

```python
import fcntl

def process_queue(self) -> List[dict]:
    if not self.queue_file.exists():
        return []

    try:
        with open(self.queue_file, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                raw = f.read().strip()
                if not raw:
                    return []
                mutations = json.loads(raw)
                if not isinstance(mutations, list):
                    mutations = [mutations]
                # Clear queue while holding lock
                f.seek(0)
                f.write("[]")
                f.truncate()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Invalid mutation queue: {e}")
        return []
    # ... process mutations ...
```

And the same lock must be used in the CLI's `cmd_mutate`/`cmd_spike`/`cmd_decay`.

---

### C4. State File Non-Atomic Write — Corruption on Crash

**File:** `src/state/persistence.py` lines ~52–60 (`save`)  
**What:** `self.state_file.write_text(...)` is not atomic. If the daemon crashes mid-write (OOM, SIGKILL, power loss), the state file will be truncated or contain partial JSON, and all drive state is lost.  
**Why it matters:** This is the daemon's only persistence mechanism. Losing state means losing drive pressures, trigger history, config overrides from mutations — everything the agent has learned about itself.  
**Fix:** Write to a temp file, then atomic rename:

```python
import tempfile

def save(self):
    self._data["_saved_at"] = time.time()
    self._data["_version"] = "0.1.0"
    
    try:
        content = json.dumps(self._data, indent=2, default=str)
        # Atomic write: temp file → rename
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.state_dir), suffix=".tmp"
        )
        try:
            os.write(fd, content.encode())
            os.fsync(fd)
            os.close(fd)
            os.rename(tmp_path, str(self.state_file))
        except Exception:
            os.close(fd)
            os.unlink(tmp_path)
            raise
        self._dirty = False
        self._last_save = time.time()
    except OSError as e:
        logger.error(f"Failed to save state: {e}")
```

---

### C5. CLI Status Uses Wrong Key Names — Display Always Empty

**File:** `src/cli.py` lines ~157–195 (`cmd_status`)  
**What:** The CLI reads from the health API but uses different key names than what the health server returns:

| CLI accesses | Health server returns |
|---|---|
| `status_data["rate_limits"]` | `status_data["rate_limit"]` |
| `status_data["evaluator"]` | *(not returned)* |
| `status_data["last_trigger"]` | *(nested in `triggers`)* |
| `status_data["trigger_stats"]` | `status_data["triggers"]` |

**Why it matters:** The CLI is the primary user interface. With these mismatches, `pulse status` shows empty/missing data for rate limits, evaluator mode, last trigger, and trigger stats — making it look like nothing is happening.  
**Fix:** Align the CLI to match the actual health server response schema:

```python
# In cmd_status:
rl = status_data.get("rate_limit", {})  # not "rate_limits"
table.add_row(
    "Rate",
    f"{rl.get('turns_last_hour', 0)}/{rl.get('max_per_hour', 10)} turns/hr · "
    f"cooldown {rl.get('cooldown_remaining', 0)}s"
)

ts = status_data.get("triggers", {})  # not "trigger_stats"
```

Or better: add the missing fields to the health server's `/status` endpoint.

---

### C6. Signal Handler Conflicts With asyncio Event Loop

**File:** `src/core/daemon.py` lines ~196–202 (`_setup_signals`, `_handle_signal`)  
**What:** `signal.signal()` is called in `run()` before `asyncio.run()`. When asyncio starts, it may install its own signal handlers. The `_handle_signal` sets `self.running = False` from a signal context, which works due to the GIL but is not the sanctioned asyncio pattern.  
**Why it matters:** On some platforms, signal delivery during `asyncio.sleep()` can cause `InterruptedError`. The `running` flag is checked after the sleep, so the daemon may do one more full loop iteration after SIGTERM before noticing.  
**Fix:** Use asyncio's signal handling:

```python
async def _main_loop(self):
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, self._handle_shutdown)
    # ... rest of main loop ...

def _handle_shutdown(self):
    logger.info("Received shutdown signal")
    self.running = False
```

---

## 🟡 Important — Fix Soon

### I1. ConversationSensor Creates Unused aiohttp Session (Resource Leak)

**File:** `src/sensors/manager.py` lines ~170–178 (`ConversationSensor.initialize`)  
**What:** Creates `self._session = aiohttp.ClientSession()` in `initialize()` but never uses it — `read()` only checks file mtimes. The session is never closed.  
**Why it matters:** Leaked aiohttp session → unclosed TCP connector → ResourceWarning on every run.  
**Fix:** Remove the session creation (it's not needed) or close it in shutdown:

```python
async def initialize(self):
    # Remove: self._session = aiohttp.ClientSession()
    session_dir = self._session_dir()
    if session_dir and session_dir.exists():
        logger.info(f"Conversation sensor watching: {session_dir}")
```

---

### I2. No Watchdog Observer Shutdown

**File:** `src/sensors/manager.py` (FileSystemSensor), `src/core/daemon.py` (`_cleanup`)  
**What:** The watchdog `Observer` thread is started in `FileSystemSensor.initialize()` but never stopped on daemon shutdown. `_cleanup()` only closes the webhook and health server.  
**Why it matters:** The watchdog thread continues running in the background after the daemon's main loop exits, preventing clean process termination. This can cause the process to hang.  
**Fix:** Add a `stop()` method to `SensorManager` and call it during cleanup:

```python
# In SensorManager:
async def stop(self):
    for sensor in self.sensors:
        if hasattr(sensor, 'stop'):
            await sensor.stop()

# In FileSystemSensor:
async def stop(self):
    if self._observer:
        self._observer.stop()
        self._observer.join(timeout=5)
```

---

### I3. Guardrail Rate Limit Resets on Restart

**File:** `src/evolution/guardrails.py` lines ~96–110 (`check_mutation_rate`)  
**What:** `Guardrails._mutation_timestamps` is in-memory only. On daemon restart, the mutation rate limit resets to zero.  
**Why it matters:** An agent that wants to bypass the "max 10 mutations per hour" guardrail could write a mutation that causes a restart, then submit more mutations. This undermines the safety invariant.  
**Fix:** Persist mutation timestamps alongside state:

```python
# In Guardrails.__init__:
def __init__(self, limits=None, state=None):
    self.limits = limits or GuardrailLimits()
    self._state = state  # StatePersistence reference
    self._mutation_timestamps = self._load_timestamps()

def _load_timestamps(self):
    if self._state:
        saved = self._state.get("guardrail_mutation_timestamps", [])
        now = time.time()
        return [t for t in saved if now - t < 3600]
    return []
```

---

### I4. Discord Sensor Config Silently Dropped

**File:** `src/core/config.py` lines ~158–175 (sensors parsing in `_from_dict`)  
**What:** The `discord` section is parsed in the YAML but the config `_from_dict` method only handles `filesystem` and `system` — the `discord` config is silently ignored.  
**Why it matters:** When discord sensor support is implemented, users will wonder why their config isn't applied. No error, no warning — just silently defaults.  
**Fix:** Add discord parsing:

```python
disc = s.get("discord", {})
config.sensors.discord = DiscordSensorConfig(
    enabled=disc.get("enabled", config.sensors.discord.enabled),
    channels=disc.get("channels", config.sensors.discord.channels),
    silence_threshold_minutes=disc.get("silence_threshold_minutes",
        config.sensors.discord.silence_threshold_minutes),
)
```

---

### I5. webhook_token `required=True` Is Misleading — Token Can Be Empty

**File:** `src/core/config.py` line ~130  
**What:** `_resolve_env(oc.get("webhook_token", ...), required=True)` only raises if the value contains an unresolved `${VAR}` pattern. If the yaml omits `webhook_token` entirely, the default empty string `""` passes through, and the webhook fires with no authentication.  
**Why it matters:** An unauthenticated webhook means any local process can trigger agent turns. With the mutation system, this is a privilege escalation path.  
**Fix:** Validate token presence explicitly:

```python
# After building openclaw config:
if not config.openclaw.webhook_token:
    logging.getLogger("pulse.config").warning(
        "No webhook_token set — webhook calls will be unauthenticated. "
        "Set PULSE_HOOK_TOKEN or add webhook_token to pulse.yaml."
    )
```

---

### I6. `_build_trigger_message` Crashes If `top_drive` Is None

**File:** `src/core/daemon.py` lines ~155–170 (`_build_trigger_message`)  
**What:** Accesses `decision.top_drive.name` and `decision.top_drive.pressure` without a None check. `DriveState.top_drive` is None when the drives list is empty.  
**Why it matters:** If all drives are removed via mutation (protected drives prevent removing "goals" and "growth", but could be zero-pressure), or if drives dict is somehow empty, this crashes the trigger path.  
**Fix:**

```python
parts = [
    f"{prefix} Self-initiated turn.",
    f"Trigger reason: {decision.reason}",
]
if decision.top_drive:
    parts.append(f"Top drive: {decision.top_drive.name} (pressure: {decision.top_drive.pressure:.2f})")
else:
    parts.append(f"Total pressure: {decision.total_pressure:.2f}")
```

---

### I7. `max_pressure` Default Mismatch — 1.0 (Code) vs 5.0 (YAML)

**File:** `src/core/config.py` line ~47, `config/pulse.yaml` line ~46  
**What:** `DrivesConfig.max_pressure` defaults to `1.0` in the dataclass, but `pulse.yaml` sets it to `5.0`. If someone runs without a config file (or with a partial one missing `max_pressure`), drives cap at 1.0 instead of 5.0 — radically different behavior.  
**Why it matters:** Combined with the pressure rate bug (C1), this means in default mode drives hit max in ~3 seconds. The system will trigger constantly.  
**Fix:** Align the dataclass default with the intended value:

```python
@dataclass
class DrivesConfig:
    pressure_rate: float = 0.01
    trigger_threshold: float = 0.7
    max_pressure: float = 5.0  # Match yaml default
```

---

### I8. Webhook `wake()` URL Construction Is Fragile

**File:** `src/core/webhook.py` line ~71  
**What:** `wake_url = self.url.replace("/hooks/agent", "/hooks/wake")` — if the base URL doesn't end with `/hooks/agent` (e.g., custom endpoint, trailing slash), the replacement silently fails and POSTs to the wrong URL.  
**Why it matters:** Silent misdirection of webhook calls. The wake will either fail or hit an unintended endpoint.  
**Fix:** Construct the URL from the base instead:

```python
from urllib.parse import urljoin, urlparse

async def wake(self, text: str) -> bool:
    parsed = urlparse(self.url)
    wake_url = f"{parsed.scheme}://{parsed.netloc}/hooks/wake"
    # ... rest of method
```

---

### I9. Health Endpoint Query Parameter Injection

**File:** `src/core/health.py` line ~89 (`_handle_mutations`)  
**What:** `n = int(request.query.get("n", "20"))` — if `n` is not a valid integer (e.g., `?n=abc` or `?n=-1`), this raises an unhandled `ValueError` that returns a 500 error. A very large `n` (e.g., `?n=999999999`) could also cause the audit log to load excessive data.  
**Fix:**

```python
try:
    n = min(max(int(request.query.get("n", "20")), 1), 1000)
except (ValueError, TypeError):
    n = 20
```

---

### I10. Daily Notes Header Written Multiple Times

**File:** `src/core/daily_sync.py` lines ~20–30 (`__init__`, `_ensure_header`)  
**What:** `_header_written` starts as `False` in `__init__` and resets on date change. If the daemon restarts on the same day, it appends another `### 🫀 Pulse Activity` header to the daily note.  
**Why it matters:** Multiple headers in daily notes look messy and confuse the agent when reviewing its day.  
**Fix:** Check if the header already exists in the file:

```python
def _ensure_header(self, f):
    if not self._header_written:
        # Check if header already present (from previous run today)
        path = self._get_file()
        try:
            if path.exists() and "### 🫀 Pulse Activity" in path.read_text():
                self._header_written = True
                return
        except OSError:
            pass
        f.write("\n### 🫀 Pulse Activity\n")
        self._header_written = True
```

---

### I11. Self-Write Path Tracking Uses Exact String Match

**File:** `src/sensors/manager.py` lines ~100–105 (`_WatchdogHandler._should_ignore`)  
**What:** `path in self.self_write_paths` uses exact string equality. If the watchdog reports a resolved symlink, normalized path, or different casing, the self-write won't be recognized and Pulse will trigger on its own writes.  
**Why it matters:** Self-triggering creates a feedback loop: Pulse writes daily notes → filesystem sensor detects change → drives spike → Pulse triggers → Pulse writes again.  
**Fix:** Normalize paths before comparison:

```python
def mark_self_write(self, path: str):
    if self._handler:
        self._handler.self_write_paths.add(str(Path(path).resolve()))

def _should_ignore(self, path: str) -> bool:
    resolved = str(Path(path).resolve())
    # ... existing pattern checks ...
    if self._ignore_self_writes and resolved in self.self_write_paths:
        self.self_write_paths.discard(resolved)
        return True
```

---

### I12. Missing Mutation JSON Schema Validation

**File:** `src/evolution/mutator.py` lines ~93–100 (`_apply_mutation`)  
**What:** Mutation handlers access required keys with `mutation["drive"]`, `mutation["value"]`, etc. without validation. A malformed mutation (missing keys) causes `KeyError` that's caught as a generic `Exception`.  
**Why it matters:** The error message is unhelpful (`KeyError: 'drive'`), and the audit log doesn't record the malformed attempt.  
**Fix:** Validate before processing:

```python
def _apply_mutation(self, mutation: dict) -> dict:
    mut_type = mutation.get("type", "")
    if not mut_type:
        raise ValueError("Mutation missing 'type' field")
    
    # Validate required fields per type
    required_fields = {
        "adjust_weight": ["drive", "value"],
        "adjust_threshold": ["value"],
        "adjust_rate": ["value"],
        "add_drive": ["name"],
        "remove_drive": ["drive"],
        "spike_drive": ["drive"],
        "decay_drive": ["drive"],
    }
    for field in required_fields.get(mut_type, []):
        if field not in mutation:
            raise ValueError(f"Mutation type '{mut_type}' requires field '{field}'")
    # ... rest of method
```

---

### I13. `on_trigger_success` Only Decays Top Drive

**File:** `src/drives/engine.py` lines ~137–145 (`on_trigger_success`)  
**What:** After a successful agent turn, only the single top drive's pressure is decayed. All other contributing drives continue accumulating.  
**Why it matters:** If combined threshold (0.7) triggers with 5 drives each at 0.14, success decays one drive to ~0.0 but the others remain at 0.14. Next tick, the combined pressure is still ~0.56 and rapidly re-triggers.  
**Fix (option A):** Decay all drives proportionally:

```python
def on_trigger_success(self, decision):
    decay = self.config.drives.success_decay
    for drive in self.drives.values():
        if drive.pressure > 0:
            # Proportional decay based on each drive's contribution
            proportion = drive.weighted_pressure / decision.total_pressure if decision.total_pressure > 0 else 0
            drive.decay(decay * proportion * 2)  # Scale factor
    if decision.top_drive and decision.top_drive.name in self.drives:
        self.drives[decision.top_drive.name].last_addressed = time.time()
```

---

## 🟢 Nice-to-Have — Future

### N1. `history_retention_days` Config Not Implemented

**File:** `src/core/config.py` line ~99, `src/state/persistence.py`  
**What:** `StateConfig.history_retention_days = 30` is defined in config but never used. Old trigger history is never pruned by age — only by file size (5MB rotation).  
**Fix:** Add periodic history cleanup based on timestamp, e.g., in `maybe_save()`.

---

### N2. DailyNoteSync Doesn't Create Missing Directory

**File:** `src/core/daily_sync.py` line ~38 (`log_trigger`)  
**What:** If the `memory/` directory doesn't exist, `open(path, "a")` will raise `FileNotFoundError`.  
**Fix:** `path.parent.mkdir(parents=True, exist_ok=True)` before opening.

---

### N3. Web and Git Sensor Configs in YAML but No Implementation

**File:** `config/pulse.yaml` lines ~82–99  
**What:** `web` and `git` sensor sections are documented in config but have no corresponding sensor classes. Comment says "Phase 3" but there's no tracking.  
**Fix:** Either add stub classes or remove from config (or add TODO comments in SensorManager).

---

### N4. `recent()` and `summary()` in AuditLog Read Entire File

**File:** `src/evolution/audit.py` lines ~55–65, ~78–95  
**What:** Both methods read the entire JSONL file (up to 5MB) into a list. For `recent(n=10)`, only the last 10 entries are needed.  
**Fix:** Use `collections.deque(maxlen=n)` or read from the end of the file.

---

### N5. Hardcoded Version String in Multiple Places

**Files:** `src/__init__.py`, `src/core/health.py` lines ~54, ~72, `src/state/persistence.py` line ~55  
**What:** Version `"0.1.0"` is hardcoded in health responses and state files instead of referencing `pulse.src.__version__`.  
**Fix:**

```python
from pulse.src import __version__
# Use __version__ everywhere
```

---

### N6. CLI `_pressure_bar` Max Pressure Hardcoded to 5.0

**File:** `src/cli.py` line ~75 (`_pressure_bar`)  
**What:** `max_p` defaults to `5.0` regardless of the configured `max_pressure`. If max_pressure changes, the bar visualization will be wrong.  
**Fix:** Pass the actual config value from the API response.

---

### N7. `_refresh_sources` Comment/Variable Name Mismatch

**File:** `src/drives/engine.py` line ~128  
**What:** Comment says "Goals — check for stale/blocked goals" but the code reads `workspace.resolve_path("hypotheses")` and spikes the `"unfinished"` drive. The variable is named `goals_path`.  
**Fix:** Rename variable and fix comment:

```python
# Hypotheses — check for untested hypotheses (unfinished business)
hypotheses_path = workspace.resolve_path("hypotheses")
```

---

### N8. No Structured Logging

**Files:** All  
**What:** Logging uses string formatting everywhere. No structured fields for machine parsing.  
**Fix (future):** Consider `structlog` or at least JSON-formatted log entries for the trigger/mutation events that matter most.

---

### N9. CLI `cmd_mutate` Interactive Mode Doesn't Validate Drive Exists

**File:** `src/cli.py` lines ~270–295  
**What:** Interactive mode accepts any drive name without checking if it exists. The error only surfaces when the daemon processes the queue.  
**Fix:** Query the health API for valid drive names and validate interactively.

---

### N10. No Graceful Handling of Disk Full

**Files:** `src/state/persistence.py`, `src/evolution/audit.py`, `src/core/daily_sync.py`  
**What:** All file writes catch `OSError` and log a warning, but there's no escalation. If the disk is full, the daemon silently loses state, audit entries, and daily notes.  
**Fix:** Track consecutive write failures and spike a "system" drive or send an alert.

---

## 🚀 Performance Improvements

### P1. Blocking Subprocess Calls in Async Context

**File:** `src/sensors/manager.py` lines ~208–240 (`SystemSensor.read`)  
**What:** `subprocess.run(["vm_stat"], ...)` and `subprocess.run(["pgrep", ...], ...)` are synchronous blocking calls inside an `async read()` method. Each can take up to 5 seconds (timeout). With multiple watched processes, this serializes and blocks the entire event loop.  
**Fix:** Use `asyncio.create_subprocess_exec()`:

```python
async def read(self) -> dict:
    alerts = []
    try:
        proc = await asyncio.create_subprocess_exec(
            "vm_stat",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        # ... parse stdout.decode() ...
    except (asyncio.TimeoutError, OSError):
        pass
```

---

### P2. Synchronous File I/O in Async Drive Tick

**File:** `src/drives/engine.py` lines ~117–145 (`_refresh_sources`)  
**What:** `_refresh_sources` reads multiple JSON files synchronously (`Path.read_text()` + `json.loads()`) inside the async main loop. If these files are on a slow filesystem (NFS, FUSE), this blocks the event loop.  
**Why it matters:** Each loop iteration calls this. With a 30s loop, a 1s file read means the event loop is blocked for 1s every 30s.  
**Fix:** Use `asyncio.to_thread()` (Python 3.9+):

```python
async def tick_async(self, sensor_data: dict) -> DriveState:
    # ... time-based accumulation (fast, keep sync) ...
    await asyncio.to_thread(self._refresh_sources)
    # ... build state ...
```

Or cache file contents and only re-read on mtime change.

---

### P3. AuditLog `summary()` Rereads Entire File Every Call

**File:** `src/evolution/audit.py` lines ~78–95 (`summary`)  
**What:** Every call to the `/mutations` health endpoint reads and parses the entire mutations.jsonl file. With frequent health checks, this is unnecessary I/O.  
**Fix:** Cache the summary and invalidate on write:

```python
def __init__(self, state_dir):
    # ...
    self._cached_summary = None

def record(self, mutation):
    # ...
    self._cached_summary = None  # Invalidate

def summary(self):
    if self._cached_summary is None:
        self._cached_summary = self._compute_summary()
    return self._cached_summary
```

---

### P4. ConversationSensor Scans All Session Files Every Tick

**File:** `src/sensors/manager.py` lines ~189–205 (`ConversationSensor.read`)  
**What:** Every 30 seconds, iterates all files in `~/.openclaw/agents/main/sessions/` calling `stat()` on each. As session history grows, this gets slower.  
**Fix:** Use `watchdog` on the sessions directory too, or only check the most recent file by name pattern.

---

## 🏗️ Architecture Recommendations

### A1. Extract Sensor Cleanup into Lifecycle Protocol

**What:** Sensors have `initialize()` but no standardized `stop()`. The FileSystemSensor needs to stop its watchdog observer, the ConversationSensor needs to close its session (once it actually uses one).  
**Fix:** Add `stop()` to `BaseSensor` and call it from a `SensorManager.stop()`:

```python
class BaseSensor:
    async def initialize(self): pass
    async def read(self) -> dict: raise NotImplementedError
    async def stop(self): pass
```

---

### A2. Central Config Validation Layer

**What:** Config validation is scattered: `_check_config_permissions` for file perms, `_resolve_env` for env vars, but no validation of value ranges (e.g., negative pressure_rate, loop_interval_seconds=0, health_port > 65535).  
**Fix:** Add a `validate()` method to `PulseConfig` called after `load()`:

```python
def validate(self):
    errors = []
    if self.drives.pressure_rate <= 0:
        errors.append("drives.pressure_rate must be positive")
    if self.daemon.loop_interval_seconds < 1:
        errors.append("daemon.loop_interval_seconds must be >= 1")
    if not (1 <= self.daemon.health_port <= 65535):
        errors.append("daemon.health_port must be 1-65535")
    if errors:
        raise ValueError("Config validation errors:\n" + "\n".join(f"  - {e}" for e in errors))
```

---

### A3. Separate State From Side Effects in DriveEngine

**What:** `DriveEngine.tick()` does three things: accumulates pressure, applies sensor spikes, and reads source files. The source file reading (`_refresh_sources`) is doing I/O inside what should be a pure state-transition function.  
**Fix:** Make `tick()` pure (takes data in, returns state out) and move file reading to the main loop:

```python
# In daemon._main_loop:
source_data = await asyncio.to_thread(self.drives.read_sources)
drive_state = self.drives.tick(sensor_data, source_data)
```

---

### A4. Consider a Message Bus for Internal Events

**What:** The daemon manually coordinates triggers → drive decay → state save → daily notes → mark self-writes → evaluator history. Adding new side effects means modifying `_trigger_turn`.  
**Fix (future):** Use a simple observer/event pattern:

```python
class EventBus:
    def emit(self, event_type: str, data: dict): ...
    def on(self, event_type: str, handler: Callable): ...

# In daemon init:
self.bus = EventBus()
self.bus.on("trigger_success", self.drives.on_trigger_success)
self.bus.on("trigger_success", self.daily_sync.log_trigger)
self.bus.on("trigger_success", self.state.log_trigger)
```

---

### A5. CLI and Daemon Share No Schema Definition

**What:** The CLI hardcodes health API response keys, the health server hardcodes response shapes, and there's no shared schema or type definition. This caused bug C5 (mismatched keys).  
**Fix:** Define response types as dataclasses or TypedDicts shared between health.py and cli.py.

---

### A6. Evolution Audit Trail Is Append-Only But Not Tamper-Resistant

**What:** The audit log is JSONL that anyone with file access can edit. The docstring says "The agent cannot delete or modify past entries" but there's no cryptographic integrity check.  
**Fix (future):** Add a hash chain:

```python
def record(self, mutation):
    entry = asdict(mutation)
    entry["prev_hash"] = self._last_hash
    entry["hash"] = hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()
    self._last_hash = entry["hash"]
    # ... write ...
```

---

### A7. Type Hints Are Incomplete

**What:** Several methods use `dict` where more specific types would help:
- `sensor_data: dict` everywhere — should be a typed `SensorReading` dataclass
- `mutation: dict` — should be a typed `MutationCommand` union type
- Health endpoint responses — no type safety

**Fix:** Define proper types for the data flowing through the system.

---

## Summary

| Severity | Count | Key Themes |
|----------|-------|------------|
| 🔴 Critical | 6 | Pressure math wrong, async cleanup broken, data loss races, CLI display broken |
| 🟡 Important | 13 | Resource leaks, security gaps, path handling, config mismatches |
| 🟢 Nice-to-have | 10 | Missing features, code hygiene, hardcoded values |
| 🚀 Performance | 4 | Blocking I/O in async, unnecessary file reads |
| 🏗️ Architecture | 7 | Missing abstractions, coupled side effects, no shared schemas |

## ✅ ALL 40 ISSUES RESOLVED (Feb 16, 2026)

All 6 critical, 13 important, 10 nice-to-have, 4 performance, and 7 architecture items have been addressed.

The architecture is sound — the SENSE → EVALUATE → ACT → EVOLVE loop is clean, guardrails are well-designed, and the separation between Pulse and the agent (via webhook) is the right call. Now the implementation matches the design quality.
