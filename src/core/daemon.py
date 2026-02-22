"""
Pulse Daemon — The persistent cognitive loop.

This is the heartbeat of Pulse. It runs continuously, evaluating drives
against sensor input, and triggering OpenClaw agent turns when the agent
should think.
"""

import asyncio
import fcntl
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pulse.src.core.config import PulseConfig
from pulse.src.drives.engine import DriveEngine
from pulse.src.sensors.manager import SensorManager
from pulse.src.evaluator.priority import PriorityEvaluator, TriggerDecision
from pulse.src.evaluator.model import ModelEvaluator, ModelConfig
from pulse.src.evolution.mutator import Mutator
from pulse.src.state.persistence import StatePersistence
from pulse.src.core.health import HealthServer
from pulse.src.core.webhook import OpenClawWebhook
from pulse.src.core.daily_sync import DailyNoteSync
from pulse.src.core.events import EventBus, TRIGGER_SUCCESS, TRIGGER_FAILURE, MUTATION_APPLIED
from pulse.src.integrations import Integration
from pulse.src.nervous_system import NervousSystem
from pulse.src.germinal_tasks import generate_tasks as germinal_generate

logger = logging.getLogger("pulse")


def _load_integration(name: str) -> Integration:
    """Load an integration by name or module path."""
    if name == "iris":
        from pulse.src.integrations.iris import IrisIntegration
        return IrisIntegration()
    elif name == "default":
        from pulse.src.integrations.default import DefaultIntegration
        return DefaultIntegration()
    else:
        # Try importing as a module path (e.g. "mypackage.integrations.custom")
        try:
            import importlib
            module = importlib.import_module(name)
            # Look for a class that subclasses Integration
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and issubclass(attr, Integration) 
                    and attr is not Integration):
                    return attr()
            raise ImportError(f"No Integration subclass found in {name}")
        except ImportError as e:
            logger.warning(f"Could not load integration '{name}': {e}. Using default.")
            from pulse.src.integrations.default import DefaultIntegration
            return DefaultIntegration()


class PulseDaemon:
    """Main daemon process — the nervous system."""

    def __init__(self, config: Optional[PulseConfig] = None, config_path: Optional[str] = None):
        self.config = config or PulseConfig.load(config_path)
        self.running = False
        self.start_time: Optional[float] = None
        self.turn_count = 0
        self.last_trigger_time = 0.0
        self._turn_timestamps: list = []  # sliding window for rate limiting
        self._pid_fd = None  # file descriptor for PID lock
        self._last_generate_time: float = 0.0  # track GENERATE step timing

        # Core components
        self.state = StatePersistence(self.config)
        self.drives = DriveEngine(self.config, self.state)
        self.sensors = SensorManager(self.config)
        self.webhook = OpenClawWebhook(self.config)
        self.health = HealthServer(self, port=self.config.daemon.health_port)
        self.mutator = Mutator(self.config, self.drives, state=self.state)
        self.integration = _load_integration(self.config.daemon.integration)

        # Event bus for decoupled side effects
        self.bus = EventBus()
        
        # Daily note sync (if enabled)
        self.daily_sync = DailyNoteSync(self.config) if self.config.logging.sync_to_daily_notes else None
        
        # Wire up event handlers
        if self.daily_sync:
            self.bus.on(TRIGGER_SUCCESS, self._on_trigger_daily_sync)
            self.bus.on(TRIGGER_FAILURE, self._on_trigger_daily_sync)
            self.bus.on(MUTATION_APPLIED, self._on_mutation_daily_sync)

        # Nervous system — all 19 modules
        try:
            workspace = str(self.config.workspace.root) if hasattr(self.config, 'workspace') and hasattr(self.config.workspace, 'root') else "~/.openclaw/workspace"
            self.nervous_system = NervousSystem(config=self.config, workspace_root=workspace)
        except Exception as e:
            logger.warning(f"NervousSystem init failed (continuing without): {e}")
            self.nervous_system = None

        # Evaluator — rules (Phase 1-2) or model (Phase 3+)
        if self.config.evaluator.mode == "model":
            mc = self.config.evaluator.model
            model_config = ModelConfig(
                base_url=mc.base_url,
                api_key=mc.api_key,
                model=mc.model,
                max_tokens=mc.max_tokens,
                temperature=mc.temperature,
                timeout_seconds=mc.timeout_seconds,
            )
            self.evaluator = ModelEvaluator(self.config, model_config)
            self._model_evaluator = True
        else:
            self.evaluator = PriorityEvaluator(self.config)
            self._model_evaluator = False

    def run(self):
        """Start the daemon. Blocks until shutdown."""
        self._write_pid()
        self.running = True
        self.start_time = time.time()

        logger.info("🫀 Pulse starting — daemon online")
        logger.info(f"   Webhook: {self.config.openclaw.webhook_url}")
        logger.info(f"   Loop interval: {self.config.daemon.loop_interval_seconds}s")
        logger.info(f"   Trigger threshold: {self.config.drives.trigger_threshold}")
        logger.info(f"   Integration: {self.integration.name}")
        if self._model_evaluator:
            mc = self.config.evaluator.model
            logger.info(f"   Evaluator: MODEL ({mc.model} via {mc.base_url})")
        else:
            logger.info(f"   Evaluator: RULES")

        try:
            asyncio.run(self._main_loop())
        except KeyboardInterrupt:
            logger.info("Pulse interrupted — shutting down")
        finally:
            self._cleanup_sync()

    async def _main_loop(self):
        """The core cognitive loop. SENSE → EVALUATE → ACT."""
        # Install signal handlers via asyncio (C6 fix)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._handle_shutdown)

        # Initialize subsystems
        await self.sensors.start()
        await self.health.start()

        # Load persisted state
        self.state.load()
        self.drives.restore_state()

        # Start nervous system
        if self.nervous_system:
            try:
                ns_status = self.nervous_system.startup()
                logger.info(f"NervousSystem: {ns_status.get('modules_loaded', 0)} modules loaded")
                # Warm up all modules — ensures state files exist for health dashboard
                warmup = self.nervous_system.warm_up()
                logger.info(f"NervousSystem warm-up: {len(warmup.get('warmed', []))} modules warmed")
            except Exception as e:
                logger.warning(f"NervousSystem startup failed: {e}")

        # Restore config overrides from mutations
        overrides = self.state.get("config_overrides", {})
        if overrides:
            if "trigger_threshold" in overrides:
                self.config.drives.trigger_threshold = overrides["trigger_threshold"]
            if "pressure_rate" in overrides:
                self.config.drives.pressure_rate = overrides["pressure_rate"]
            if "min_trigger_interval" in overrides:
                self.config.openclaw.min_trigger_interval = overrides["min_trigger_interval"]
            if "max_turns_per_hour" in overrides:
                self.config.openclaw.max_turns_per_hour = overrides["max_turns_per_hour"]
            logger.info(f"Restored config overrides: {overrides}")

        try:
          logger.info("Entering main loop...")
          while self.running:
            loop_start = time.time()

            try:
                logger.debug(f"Loop tick — uptime {time.time() - self.start_time:.0f}s")

                # SENSE — gather sensor readings
                logger.debug("SENSE: reading sensors...")
                sensor_data = await self.sensors.read()
                logger.debug(f"SENSE: done. Changes: {sensor_data.get('filesystem', {}).get('changes', [])}")

                # NERVOUS SYSTEM — pre-sense enrichment
                ns_context = {}
                if self.nervous_system:
                    try:
                        ns_context = self.nervous_system.pre_sense(sensor_data)
                        if ns_context.get("should_pause"):
                            logger.info("NervousSystem advises pause (threat/health)")
                    except Exception as e:
                        logger.warning(f"NervousSystem pre_sense failed: {e}")

                # DRIVE — update drive pressures based on sensors + time
                self.drives.refresh_sources()  # I/O: read workspace files (cached)
                drive_state = self.drives.tick(sensor_data)  # Pure state transition
                convo_info = sensor_data.get("conversation", {})
                logger.info(f"DRIVE: pressure={drive_state.total_pressure:.3f} | convo_active={convo_info.get('active')} since={convo_info.get('seconds_since')}s")

                # NERVOUS SYSTEM — pre-evaluate enrichment
                ns_eval_context = {}
                if self.nervous_system:
                    try:
                        ns_eval_context = self.nervous_system.pre_evaluate(drive_state, sensor_data)
                    except Exception as e:
                        logger.warning(f"NervousSystem pre_evaluate failed: {e}")

                # EVALUATE — should we trigger an agent turn?
                if self._model_evaluator:
                    working_memory = self._load_working_memory()
                    decision = await self.evaluator.evaluate(
                        drive_state, sensor_data, working_memory
                    )
                else:
                    decision = self.evaluator.evaluate(drive_state, sensor_data)
                logger.info(f"EVAL: trigger={decision.should_trigger}, reason={decision.reason[:80]}")

                # Hard HIGH-PRESSURE override (model can't suppress this)
                # If pressure is extremely high and we haven't triggered in a long time,
                # the agent MUST wake up regardless of what the model says.
                # Requires at least one individual drive above threshold to avoid
                # firing on ambient noise from many low-pressure drives.
                if not decision.should_trigger and drive_state.total_pressure > 10.0:
                    max_individual = max((d.weighted_pressure for d in drive_state.drives), default=0.0)
                    time_since_trigger = time.time() - self.last_trigger_time
                    if time_since_trigger > 1800 and max_individual > self.config.drives.override_min_individual_pressure:
                        logger.info(
                            f"🔥 HIGH-PRESSURE OVERRIDE — pressure={drive_state.total_pressure:.1f}, "
                            f"max_individual={max_individual:.2f}, "
                            f"last_trigger={time_since_trigger:.0f}s ago. Forcing trigger."
                        )
                        decision.should_trigger = True
                        decision.reason = (
                            f"high_pressure_override: pressure={drive_state.total_pressure:.1f}, "
                            f"max_individual={max_individual:.2f}, idle={time_since_trigger:.0f}s"
                        )

                # Hard conversation suppression (model can't override this)
                convo = sensor_data.get("conversation", {})
                if convo.get("active") and decision.should_trigger:
                    logger.info(
                        f"Trigger SUPPRESSED — human conversation active "
                        f"(last activity {convo.get('seconds_since', '?')}s ago)"
                    )
                    decision.should_trigger = False

                if decision.should_trigger:
                    if self._can_trigger():
                        await self._trigger_turn(decision)
                    else:
                        logger.debug(
                            f"Trigger suppressed (rate limit/cooldown). "
                            f"Drive pressure: {decision.total_pressure:.2f}"
                        )

                # GENERATE — synthesize new tasks when blocked but drives are high
                if (
                    not decision.should_trigger
                    and decision.recommend_generate
                    and self.config.generative.enabled
                ):
                    await self._maybe_generate(drive_state, sensor_data)

                # FEEDBACK — check for turn results from the agent
                self._process_feedback_file()

                # EVOLVE — process any pending self-modifications
                mutation_results = self.mutator.process_queue()
                if mutation_results:
                    logger.info(f"Evolution: {len(mutation_results)} mutations processed")
                    for r in mutation_results:
                        if r.get("status") == "applied":
                            self.bus.emit(MUTATION_APPLIED, result=r)
                    # Persist config overrides so mutations survive restarts
                    self.state.set("config_overrides", {
                        "trigger_threshold": self.config.drives.trigger_threshold,
                        "pressure_rate": self.config.drives.pressure_rate,
                        "min_trigger_interval": self.config.openclaw.min_trigger_interval,
                        "max_turns_per_hour": self.config.openclaw.max_turns_per_hour,
                    })
                    self.state.set("drives", self.drives.save_state())
                    self.state.save()

                # NERVOUS SYSTEM — post-loop maintenance
                if self.nervous_system:
                    try:
                        self.nervous_system.post_loop()
                    except Exception as e:
                        logger.warning(f"NervousSystem post_loop failed: {e}")

                    # Night mode check
                    try:
                        night = self.nervous_system.check_night_mode(
                            drives={n: d for n, d in self.drives.drives.items()} if hasattr(self.drives, 'drives') else None
                        )
                        if night.get("rem_eligible"):
                            logger.info("🌙 REM eligible — starting dream session")
                            self.nervous_system.run_rem_session(
                                drives={n: d for n, d in self.drives.drives.items()} if hasattr(self.drives, 'drives') else None
                            )
                    except Exception as e:
                        logger.warning(f"NervousSystem night mode check failed: {e}")

                # PERSIST — sync drives to state and save periodically
                self.state.set("drives", self.drives.save_state())
                self.state.maybe_save()

            except Exception as e:
                logger.error(f"Loop error: {e}", exc_info=True)

            # Sleep until next loop
            elapsed = time.time() - loop_start
            sleep_time = max(0, self.config.daemon.loop_interval_seconds - elapsed)
            await asyncio.sleep(sleep_time)
        finally:
            # Async cleanup INSIDE the event loop (C2 fix)
            logger.info("Shutting down async resources...")
            await self.sensors.stop()
            await self.webhook.close()
            await self.health.stop()
            if self._model_evaluator and hasattr(self.evaluator, 'close'):
                await self.evaluator.close()

    async def _trigger_turn(self, decision):
        """Trigger an OpenClaw agent turn via webhook."""
        self.last_trigger_time = time.time()
        self.turn_count += 1
        self._turn_timestamps.append(self.last_trigger_time)

        # Build the message from the decision context
        message = self._build_trigger_message(decision)

        # NERVOUS SYSTEM — pre-respond (PHENOTYPE tone shaping)
        if self.nervous_system:
            try:
                respond_ctx = self.nervous_system.pre_respond()
                phenotype = respond_ctx.get("phenotype")
                if phenotype:
                    # Inject phenotype context into the trigger message
                    tone_hint = f"\n\n[PHENOTYPE: tone={phenotype.get('tone','neutral')}, intensity={phenotype.get('intensity',0.5):.1f}, humor={phenotype.get('humor',0.3):.1f}, vulnerability={phenotype.get('vulnerability',0.2):.1f}]"
                    message += tone_hint
            except Exception as e:
                logger.warning(f"NervousSystem pre_respond failed: {e}")

        logger.info(
            f"🫀 PULSE TRIGGER #{self.turn_count} — "
            f"reason: {decision.reason}, "
            f"pressure: {decision.total_pressure:.2f}",
            extra={
                "event": "trigger",
                "turn": self.turn_count,
                "reason": decision.reason,
                "pressure": round(decision.total_pressure, 4),
                "top_drive": decision.top_drive.name if decision.top_drive else None,
            },
        )

        # Fire webhook
        success = await self.webhook.trigger(message)

        if success:
            self.drives.on_trigger_success(decision)
            self.state.log_trigger(decision, success=True)
            self.bus.emit(TRIGGER_SUCCESS, decision=decision, success=True, turn=self.turn_count)
        else:
            self.drives.on_trigger_failure(decision)
            self.state.log_trigger(decision, success=False)
            self.bus.emit(TRIGGER_FAILURE, decision=decision, success=False, turn=self.turn_count)

        # NERVOUS SYSTEM — post-trigger
        if self.nervous_system:
            try:
                self.nervous_system.post_trigger(decision, success)
            except Exception as e:
                logger.warning(f"NervousSystem post_trigger failed: {e}")

        # Feed outcome back to model evaluator for history context
        if self._model_evaluator and hasattr(self.evaluator, 'record_trigger'):
            self.evaluator.record_trigger(decision, success)

    def _on_trigger_daily_sync(self, decision, success, turn, **kwargs):
        """Event handler: log triggers to daily notes."""
        daily_path = str(self.daily_sync._get_file())
        self._mark_self_write(daily_path)
        self.daily_sync.log_trigger(
            turn=turn,
            reason=decision.reason,
            top_drive=decision.top_drive.name if decision.top_drive else "none",
            pressure=decision.total_pressure,
            success=success,
        )

    def _on_mutation_daily_sync(self, result, **kwargs):
        """Event handler: log mutations to daily notes."""
        self._mark_self_write(str(self.daily_sync._get_file()))
        self.daily_sync.log_mutation(result)

    def _mark_self_write(self, path: str):
        """Mark a path as a Pulse self-write so the filesystem sensor ignores it."""
        for sensor in self.sensors.sensors:
            if hasattr(sensor, 'mark_self_write'):
                sensor.mark_self_write(path)

    def _load_working_memory(self) -> Optional[dict]:
        """Load the agent's working memory for model evaluator context."""
        try:
            wm_path = self.config.workspace.resolve_path("working_memory")
            if wm_path.exists():
                return json.loads(wm_path.read_text())
        except Exception as e:
            logger.debug(f"Could not load working memory: {e}")
        return None

    def _process_feedback_file(self):
        """Check for turn_result.json feedback file from the agent."""
        feedback_path = Path(self.config.state.dir).expanduser() / "turn_result.json"
        if not feedback_path.exists():
            return

        try:
            data = json.loads(feedback_path.read_text())
            feedback_path.unlink()  # consume it

            drives_addressed = data.get("drives_addressed", [])
            outcome = data.get("outcome", "success")
            summary = data.get("summary", "")
            decay_overrides = data.get("decay_overrides", {})

            now = time.time()
            for drive_name in drives_addressed:
                if drive_name in self.drives.drives:
                    drive = self.drives.drives[drive_name]
                    if drive_name in decay_overrides:
                        decay_amount = float(decay_overrides[drive_name])
                    elif outcome == "success":
                        decay_amount = min(drive.pressure, drive.pressure * 0.7)
                    elif outcome == "partial":
                        decay_amount = min(drive.pressure, drive.pressure * 0.4)
                    else:
                        decay_amount = 0.0

                    drive.decay(decay_amount)
                    drive.last_addressed = now

            logger.info(f"Feedback file processed: {outcome} — {drives_addressed} — {summary[:60]}")

        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to process feedback file: {e}")
            try:
                feedback_path.unlink()
            except OSError:
                pass

    async def _maybe_generate(self, drive_state, sensor_data):
        """Run GENERATE step if enough idle time has passed."""
        now = time.time()
        min_idle = self.config.generative.min_idle_minutes * 60
        if now - self._last_generate_time < min_idle:
            return

        try:
            # Build context from what Pulse already has
            goals = self._load_goals_list()
            working_memory = self._load_working_memory()
            recent_memory = json.dumps(working_memory, default=str)[:1000] if working_memory else ""

            drives_dict = {}
            if hasattr(drive_state, 'drives'):
                for d in drive_state.drives:
                    drives_dict[d.name] = d.pressure

            thalamus_recent = []
            try:
                from pulse.src import thalamus
                thalamus_recent = thalamus.read_recent(5)
            except Exception:
                pass

            context = {
                "goals": goals,
                "recent_memory": recent_memory,
                "drives": drives_dict,
                "thalamus_recent": thalamus_recent,
            }

            # Build config dict for germinal_tasks
            mc = self.config.evaluator.model
            gen_config = {
                "enabled": self.config.generative.enabled,
                "roadmap_files": self.config.generative.roadmap_files,
                "max_tasks": self.config.generative.max_tasks,
                "workspace_root": self.config.workspace.root,
                "model": {
                    "base_url": mc.base_url,
                    "api_key": mc.api_key,
                    "model": mc.model,
                    "max_tokens": mc.max_tokens,
                    "temperature": mc.temperature,
                    "timeout_seconds": mc.timeout_seconds,
                },
            }

            tasks = await germinal_generate(context, gen_config)
            self._last_generate_time = now

            if tasks:
                logger.info(f"GENERATE: {len(tasks)} tasks synthesized")
                for t in tasks:
                    logger.info(f"  → [{t['effort']}] {t['title']}")

                # Log to daily notes
                if self.daily_sync:
                    try:
                        path = self.daily_sync._get_file()
                        self._mark_self_write(str(path))
                        path.parent.mkdir(parents=True, exist_ok=True)
                        now_str = datetime.now().strftime("%H:%M")
                        with open(path, "a") as f:
                            self.daily_sync._ensure_header(f)
                            f.write(f"- {now_str} 🌱 GENERATE: {len(tasks)} tasks synthesized\n")
                            for t in tasks:
                                f.write(f"  - [{t['effort']}] {t['title']}\n")
                    except OSError as e:
                        logger.warning(f"Failed to sync GENERATE to daily notes: {e}")

                # Store generated tasks in state for next CORTEX prompt
                self.state.set("generated_tasks", tasks)

                # Broadcast to thalamus
                try:
                    from pulse.src import thalamus
                    thalamus.append({
                        "source": "germinal_tasks",
                        "type": "tasks_generated",
                        "salience": 0.7,
                        "data": {"count": len(tasks), "titles": [t["title"] for t in tasks]},
                    })
                except Exception:
                    pass

        except Exception as e:
            logger.warning(f"GENERATE step failed: {e}")

    def _load_goals_list(self) -> list:
        """Load current goals as a simple string list."""
        try:
            goals_path = self.config.workspace.resolve_path("goals")
            if goals_path.exists():
                content = goals_path.read_text()
                # Extract goal-like lines (lines with meaningful content)
                lines = [
                    line.strip().lstrip("- ").strip()
                    for line in content.splitlines()
                    if line.strip() and not line.strip().startswith("#") and not line.strip().startswith("\"\"\"")
                ]
                return [l for l in lines if len(l) > 5][:20]
        except Exception as e:
            logger.debug(f"Could not load goals list: {e}")
        return []

    def _build_trigger_message(self, decision) -> str:
        """Build the agent prompt via the active integration."""
        return self.integration.build_trigger_message(decision, self.config)

    def _can_trigger(self) -> bool:
        """Check rate limits and cooldowns."""
        now = time.time()

        # Cooldown check
        elapsed = now - self.last_trigger_time
        if elapsed < self.config.openclaw.min_trigger_interval:
            return False

        # Sliding window rate limit (turns per hour)
        one_hour_ago = now - 3600
        self._turn_timestamps = [t for t in self._turn_timestamps if t > one_hour_ago]
        if len(self._turn_timestamps) >= self.config.openclaw.max_turns_per_hour:
            logger.warning(
                f"Rate limit hit: {len(self._turn_timestamps)} turns in last hour "
                f"(max {self.config.openclaw.max_turns_per_hour})"
            )
            return False

        return True

    def _handle_shutdown(self):
        """Handle shutdown signal from asyncio loop."""
        logger.info("Received shutdown signal — initiating shutdown")
        self.running = False

    def _write_pid(self):
        """Write PID file with exclusive lock to prevent double-start."""
        pid_path = Path(self.config.daemon.pid_file).expanduser()
        pid_path.parent.mkdir(parents=True, exist_ok=True)

        # Check for stale PID
        if pid_path.exists():
            try:
                old_pid = int(pid_path.read_text().strip())
                os.kill(old_pid, 0)  # signal 0 = check if alive
                logger.error(f"Another Pulse instance is running (PID {old_pid}). Exiting.")
                sys.exit(1)
            except (ValueError, ProcessLookupError, PermissionError):
                logger.info("Removing stale PID file")
                pid_path.unlink(missing_ok=True)

        # Open with exclusive lock (held for daemon lifetime)
        self._pid_fd = open(pid_path, "w")
        try:
            fcntl.flock(self._pid_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.error("Could not acquire PID lock — another instance running?")
            self._pid_fd.close()
            sys.exit(1)

        self._pid_fd.write(str(os.getpid()))
        self._pid_fd.flush()

    def _cleanup_sync(self):
        """Sync-only cleanup after event loop is closed."""
        # Shutdown nervous system
        if self.nervous_system:
            try:
                self.nervous_system.shutdown()
            except Exception as e:
                logger.warning(f"NervousSystem shutdown failed: {e}")

        # Save final state
        self.state.set("drives", self.drives.save_state())
        self.state.save()

        # Release PID lock and remove file
        pid_path = Path(self.config.daemon.pid_file).expanduser()
        if self._pid_fd:
            try:
                fcntl.flock(self._pid_fd, fcntl.LOCK_UN)
                self._pid_fd.close()
            except Exception:
                pass
        pid_path.unlink(missing_ok=True)
        logger.info("🫀 Pulse stopped — daemon offline")
