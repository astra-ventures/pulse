"""
NervousSystem — Unified integration layer for all 19 Pulse modules.

Wraps all nervous system modules into a single class that the daemon
calls at specific points in the cognitive loop. Each module is optional;
if one fails to initialize, the rest continue.
"""

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pulse.nervous_system")


class NervousSystem:
    """Manages all 19 nervous system modules for the Pulse daemon.
    
    Provides high-level methods called at specific points in the loop:
    - startup() — init phase
    - pre_sense() — before/during sensing
    - pre_evaluate() — enrich evaluation context
    - post_trigger() — after a trigger decision
    - post_loop() — end-of-loop maintenance
    - check_night_mode() — REM eligibility
    - shutdown() — save everything
    """

    def __init__(self, config=None, workspace_root: str = "~/.openclaw/workspace"):
        self.config = config
        self.workspace_root = workspace_root
        self._loop_count = 0
        self._stillness_since: Optional[float] = None
        
        # Module instances (None if failed to init)
        self.thalamus = None
        self.proprioception = None
        self.circadian = None
        self.endocrine = None
        self.adipose = None
        self.myelin = None
        self.immune = None
        self.cerebellum = None
        self.buffer = None
        self.spine = None
        self.retina = None
        self.amygdala = None
        self.vagus = None
        self.limbic = None
        self.enteric = None
        self.plasticity = None
        self.rem = None
        
        # Module-level imports (functional modules)
        self._mod_thalamus = None
        self._mod_circadian = None
        self._mod_adipose = None
        self._mod_vagus = None
        self._mod_limbic = None
        self._mod_endocrine = None
        self._mod_buffer = None
        self._mod_retina = None
        self._mod_proprioception = None
        self._mod_myelin = None
        self._mod_immune = None
        
        self._init_modules()

    def _init_modules(self):
        """Initialize all modules, catching failures individually."""
        # THALAMUS — broadcast bus (module-level functions)
        try:
            from pulse.src import thalamus
            self._mod_thalamus = thalamus
            self.thalamus = thalamus
            logger.info("✓ THALAMUS loaded")
        except Exception as e:
            logger.warning(f"✗ THALAMUS failed: {e}")

        # PROPRIOCEPTION — self-model (module-level functions)
        try:
            from pulse.src import proprioception
            self._mod_proprioception = proprioception
            self.proprioception = proprioception
            logger.info("✓ PROPRIOCEPTION loaded")
        except Exception as e:
            logger.warning(f"✗ PROPRIOCEPTION failed: {e}")

        # CIRCADIAN — internal clock (module-level functions)
        try:
            from pulse.src import circadian
            self._mod_circadian = circadian
            self.circadian = circadian
            logger.info("✓ CIRCADIAN loaded")
        except Exception as e:
            logger.warning(f"✗ CIRCADIAN failed: {e}")

        # ENDOCRINE — mood (module-level functions)
        try:
            from pulse.src import endocrine
            self._mod_endocrine = endocrine
            self.endocrine = endocrine
            logger.info("✓ ENDOCRINE loaded")
        except Exception as e:
            logger.warning(f"✗ ENDOCRINE failed: {e}")

        # ADIPOSE — budget (module-level functions)
        try:
            from pulse.src import adipose
            self._mod_adipose = adipose
            self.adipose = adipose
            logger.info("✓ ADIPOSE loaded")
        except Exception as e:
            logger.warning(f"✗ ADIPOSE failed: {e}")

        # MYELIN — compression (class-based singleton)
        try:
            from pulse.src import myelin
            self._mod_myelin = myelin
            self.myelin = myelin.get_instance()
            logger.info("✓ MYELIN loaded")
        except Exception as e:
            logger.warning(f"✗ MYELIN failed: {e}")

        # IMMUNE — integrity (module-level functions)
        try:
            from pulse.src import immune
            self._mod_immune = immune
            self.immune = immune
            logger.info("✓ IMMUNE loaded")
        except Exception as e:
            logger.warning(f"✗ IMMUNE failed: {e}")

        # CEREBELLUM — habits (class-based)
        try:
            from pulse.src.cerebellum import Cerebellum
            self.cerebellum = Cerebellum()
            logger.info("✓ CEREBELLUM loaded")
        except Exception as e:
            logger.warning(f"✗ CEREBELLUM failed: {e}")

        # BUFFER — working memory (module-level functions)
        try:
            from pulse.src import buffer
            self._mod_buffer = buffer
            self.buffer = buffer
            logger.info("✓ BUFFER loaded")
        except Exception as e:
            logger.warning(f"✗ BUFFER failed: {e}")

        # SPINE — health monitor (module-level functions)
        try:
            from pulse.src import spine
            self.spine = spine
            logger.info("✓ SPINE loaded")
        except Exception as e:
            logger.warning(f"✗ SPINE failed: {e}")

        # RETINA — attention filter (class-based singleton)
        try:
            from pulse.src import retina
            self._mod_retina = retina
            self.retina = retina.get_instance()
            logger.info("✓ RETINA loaded")
        except Exception as e:
            logger.warning(f"✗ RETINA failed: {e}")

        # AMYGDALA — threat detection (class-based)
        try:
            from pulse.src.amygdala import Amygdala
            self.amygdala = Amygdala()
            logger.info("✓ AMYGDALA loaded")
        except Exception as e:
            logger.warning(f"✗ AMYGDALA failed: {e}")

        # VAGUS — silence detection (module-level functions)
        try:
            from pulse.src import vagus
            self._mod_vagus = vagus
            self.vagus = vagus
            logger.info("✓ VAGUS loaded")
        except Exception as e:
            logger.warning(f"✗ VAGUS failed: {e}")

        # LIMBIC — emotional afterimages (module-level functions)
        try:
            from pulse.src import limbic
            self._mod_limbic = limbic
            self.limbic = limbic
            logger.info("✓ LIMBIC loaded")
        except Exception as e:
            logger.warning(f"✗ LIMBIC failed: {e}")

        # ENTERIC — gut feeling (module-level functions)
        try:
            from pulse.src import enteric
            self.enteric = enteric
            logger.info("✓ ENTERIC loaded")
        except Exception as e:
            logger.warning(f"✗ ENTERIC failed: {e}")

        # PLASTICITY — drive evolution (class-based)
        try:
            from pulse.src.plasticity import Plasticity
            self.plasticity = Plasticity()
            logger.info("✓ PLASTICITY loaded")
        except Exception as e:
            logger.warning(f"✗ PLASTICITY failed: {e}")

        # REM — dreaming engine (module-level functions)
        try:
            from pulse.src import rem
            self.rem = rem
            logger.info("✓ REM loaded")
        except Exception as e:
            logger.warning(f"✗ REM failed: {e}")

    def startup(self) -> dict:
        """Run all init-phase operations. Returns status dict."""
        status = {"modules_loaded": 0, "modules_failed": 0, "details": {}}
        
        modules = [
            "thalamus", "proprioception", "circadian", "endocrine",
            "adipose", "myelin", "immune", "cerebellum", "buffer",
            "spine", "retina", "amygdala", "vagus", "limbic",
            "enteric", "plasticity", "rem",
        ]
        
        for name in modules:
            mod = getattr(self, name, None)
            if mod is not None:
                status["modules_loaded"] += 1
                status["details"][name] = "loaded"
            else:
                status["modules_failed"] += 1
                status["details"][name] = "failed"

        # Broadcast startup
        if self._mod_thalamus:
            try:
                self._mod_thalamus.append({
                    "source": "nervous_system",
                    "type": "startup",
                    "salience": 0.5,
                    "data": status,
                })
            except Exception as e:
                logger.warning(f"Thalamus startup broadcast failed: {e}")

        # Detect initial circadian mode
        if self._mod_circadian:
            try:
                mode = self._mod_circadian.get_current_mode()
                status["circadian_mode"] = mode.value if hasattr(mode, 'value') else str(mode)
            except Exception as e:
                logger.warning(f"Circadian mode detection failed: {e}")

        # Load initial mood
        if self._mod_endocrine:
            try:
                mood = self._mod_endocrine.get_mood()
                status["mood"] = mood.get("label", "unknown")
            except Exception as e:
                logger.warning(f"Endocrine mood load failed: {e}")

        logger.info(
            f"🧠 NervousSystem startup: {status['modules_loaded']} loaded, "
            f"{status['modules_failed']} failed"
        )
        return status

    def pre_sense(self, sensor_data: dict) -> dict:
        """Called before/during SENSE phase. Returns enrichment context.
        
        Runs: CIRCADIAN mode, SPINE health check, ADIPOSE budget check,
              RETINA scoring, AMYGDALA threat scan.
        """
        context = {
            "circadian_mode": None,
            "health_status": None,
            "budget_ok": True,
            "retina_scores": [],
            "threat": None,
            "should_pause": False,
        }

        # CIRCADIAN — get current mode
        if self._mod_circadian:
            try:
                mode = self._mod_circadian.get_current_mode()
                context["circadian_mode"] = mode.value if hasattr(mode, 'value') else str(mode)
                context["circadian_settings"] = self._mod_circadian.get_mode_settings()
            except Exception as e:
                logger.warning(f"pre_sense CIRCADIAN failed: {e}")

        # SPINE — health check
        if self.spine:
            try:
                health = self.spine.check_health()
                context["health_status"] = health.get("status", "unknown")
                if health.get("status") in ("orange", "red"):
                    context["should_pause"] = True
            except Exception as e:
                logger.warning(f"pre_sense SPINE failed: {e}")

        # ADIPOSE — budget report (don't allocate, just check)
        if self._mod_adipose:
            try:
                report = self._mod_adipose.get_budget_report()
                context["budget_report"] = report
                # Check if conversation budget is critically low
                conv = report.get("categories", {}).get("conversation", {})
                if conv.get("percent_used", 0) > 90:
                    context["budget_ok"] = False
            except Exception as e:
                logger.warning(f"pre_sense ADIPOSE failed: {e}")

        # RETINA — score sensor signals
        if self.retina and sensor_data:
            try:
                # Score filesystem changes as signals
                changes = sensor_data.get("filesystem", {}).get("changes", [])
                for change in changes[:10]:  # limit to avoid overload
                    signal = {"source_type": "filesystem", "text": str(change)}
                    scored = self.retina.score(signal)
                    if scored.should_process:
                        context["retina_scores"].append(scored.to_dict())
                
                # Score conversation signal
                convo = sensor_data.get("conversation", {})
                if convo.get("active"):
                    signal = {"sender": convo.get("sender", ""), "text": "conversation active"}
                    scored = self.retina.score(signal)
                    if scored.should_process:
                        context["retina_scores"].append(scored.to_dict())
            except Exception as e:
                logger.warning(f"pre_sense RETINA failed: {e}")

        # AMYGDALA — threat scan
        if self.amygdala and sensor_data:
            try:
                threat = self.amygdala.scan(sensor_data)
                if threat.threat_level > 0:
                    context["threat"] = threat.to_dict()
                    if threat.fast_path:
                        context["should_pause"] = True
                        logger.warning(
                            f"⚠️ AMYGDALA fast-path threat: {threat.threat_type} "
                            f"level={threat.threat_level:.2f}"
                        )
            except Exception as e:
                logger.warning(f"pre_sense AMYGDALA failed: {e}")

        return context

    def pre_evaluate(self, drive_state, sensor_data: dict) -> dict:
        """Called before EVALUATE. Returns enrichment for the evaluator.
        
        Runs: VAGUS silence check, ENDOCRINE tick, LIMBIC afterimages,
              ENTERIC gut check.
        """
        context = {
            "silences": [],
            "mood": None,
            "mood_influence": {},
            "afterimages": [],
            "gut_feeling": None,
        }

        # VAGUS — silence detection
        if self._mod_vagus:
            try:
                silences = self._mod_vagus.check_silence()
                context["silences"] = silences
            except Exception as e:
                logger.warning(f"pre_evaluate VAGUS failed: {e}")

        # ENDOCRINE — mood tick (decay over time)
        if self._mod_endocrine:
            try:
                # Tick with fraction of an hour based on loop interval
                loop_interval = 30  # default seconds
                if self.config and hasattr(self.config, 'daemon'):
                    loop_interval = getattr(self.config.daemon, 'loop_interval_seconds', 30)
                hours = loop_interval / 3600.0
                self._mod_endocrine.tick(hours)
                mood = self._mod_endocrine.get_mood()
                context["mood"] = mood
                context["mood_influence"] = self._mod_endocrine.get_mood_influence()
                
                # Apply circadian mood modifiers
                if self._mod_circadian:
                    try:
                        settings = self._mod_circadian.get_mode_settings()
                        modifiers = settings.get("mood_modifiers", {})
                        for hormone, delta in modifiers.items():
                            self._mod_endocrine.update_hormone(
                                hormone, delta * hours,
                                reason=f"circadian_{settings.get('mode', 'unknown')}"
                            )
                    except Exception as e:
                        logger.warning(f"Circadian mood modifier failed: {e}")
            except Exception as e:
                logger.warning(f"pre_evaluate ENDOCRINE failed: {e}")

        # LIMBIC — emotional afterimages
        if self._mod_limbic:
            try:
                afterimages = self._mod_limbic.get_current_afterimages()
                context["afterimages"] = afterimages
            except Exception as e:
                logger.warning(f"pre_evaluate LIMBIC failed: {e}")

        # ENTERIC — gut check
        if self.enteric:
            try:
                # Build context from drive state and sensor data
                gut_context = {}
                if drive_state:
                    gut_context["total_pressure"] = getattr(drive_state, 'total_pressure', 0)
                    if hasattr(drive_state, 'top_drive') and drive_state.top_drive:
                        gut_context["top_drive"] = drive_state.top_drive.name
                intuition = self.enteric.gut_check(gut_context)
                context["gut_feeling"] = {
                    "direction": intuition.direction,
                    "confidence": intuition.confidence,
                    "whisper": intuition.whisper,
                }
            except Exception as e:
                logger.warning(f"pre_evaluate ENTERIC failed: {e}")

        return context

    def post_trigger(self, decision, success: bool) -> dict:
        """Called after a trigger decision. Updates relevant modules.
        
        Runs: BUFFER auto-capture, PLASTICITY recording, ENDOCRINE event,
              THALAMUS broadcast, CEREBELLUM tracking.
        """
        result = {
            "buffer_updated": False,
            "plasticity_recorded": False,
            "endocrine_updated": False,
            "thalamus_broadcast": False,
        }

        # BUFFER — save working memory snapshot
        if self._mod_buffer:
            try:
                self._mod_buffer.capture(
                    conversation_summary=f"Trigger: {getattr(decision, 'reason', 'unknown')}",
                    decisions=[getattr(decision, 'reason', 'trigger')],
                    action_items=[],
                    emotional_state={"valence": 0.0, "intensity": 0.0, "context": "trigger"},
                    open_threads=[],
                )
                result["buffer_updated"] = True
            except Exception as e:
                logger.warning(f"post_trigger BUFFER failed: {e}")

        # PLASTICITY — record drive performance
        if self.plasticity and decision:
            try:
                top_drive = getattr(decision, 'top_drive', None)
                if top_drive:
                    drive_name = top_drive.name if hasattr(top_drive, 'name') else str(top_drive)
                    self.plasticity.record_evaluation(
                        drive_name=drive_name,
                        success=success,
                        quality_score=0.5,  # neutral default, updated by feedback
                        loop_average=5.0,   # neutral default
                        context=getattr(decision, 'reason', ''),
                    )
                    result["plasticity_recorded"] = True
            except Exception as e:
                logger.warning(f"post_trigger PLASTICITY failed: {e}")

        # ENDOCRINE — reward/stress event
        if self._mod_endocrine:
            try:
                if success:
                    self._mod_endocrine.apply_event("shipped_something")
                else:
                    self._mod_endocrine.apply_event("failed_cron")
                result["endocrine_updated"] = True
            except Exception as e:
                logger.warning(f"post_trigger ENDOCRINE failed: {e}")

        # THALAMUS — broadcast trigger
        if self._mod_thalamus:
            try:
                self._mod_thalamus.append({
                    "source": "nervous_system",
                    "type": "trigger",
                    "salience": 0.7,
                    "data": {
                        "success": success,
                        "reason": getattr(decision, 'reason', 'unknown'),
                        "pressure": getattr(decision, 'total_pressure', 0),
                    },
                })
                result["thalamus_broadcast"] = True
            except Exception as e:
                logger.warning(f"post_trigger THALAMUS failed: {e}")

        return result

    def post_loop(self) -> dict:
        """Called at the end of each loop iteration.
        
        Runs: IMMUNE periodic scan (every 10th loop), MYELIN lexicon update.
        """
        self._loop_count += 1
        result = {"loop_count": self._loop_count}

        # IMMUNE — periodic integrity check (every 10th loop)
        if self._mod_immune and self._loop_count % 10 == 0:
            try:
                issues = self._mod_immune.scan_integrity()
                result["immune_issues"] = len(issues)
                if issues:
                    logger.warning(f"IMMUNE found {len(issues)} integrity issues")
            except Exception as e:
                logger.warning(f"post_loop IMMUNE failed: {e}")

        # MYELIN — update lexicon periodically (every 20th loop)
        if self.myelin and self._loop_count % 20 == 0:
            try:
                self.myelin.update_lexicon()
                result["myelin_updated"] = True
            except Exception as e:
                logger.warning(f"post_loop MYELIN failed: {e}")

        return result

    def check_night_mode(self, drives: Optional[dict] = None) -> dict:
        """Check if conditions are right for REM/dreaming.
        
        Returns dict with eligibility info.
        """
        result = {
            "is_deep_night": False,
            "rem_eligible": False,
            "reason": "",
        }

        # Check circadian mode
        if self._mod_circadian:
            try:
                from pulse.src.circadian import CircadianMode
                mode = self._mod_circadian.get_current_mode()
                result["is_deep_night"] = (mode == CircadianMode.DEEP_NIGHT)
            except Exception as e:
                logger.warning(f"check_night_mode CIRCADIAN failed: {e}")
                return result

        if not result["is_deep_night"]:
            result["reason"] = "not deep night"
            return result

        # Check REM eligibility
        if self.rem and drives is not None:
            try:
                eligible, reason = self.rem.sanctum_eligible(drives=drives)
                result["rem_eligible"] = eligible
                result["reason"] = reason
            except Exception as e:
                logger.warning(f"check_night_mode REM failed: {e}")
                result["reason"] = f"REM check failed: {e}"

        return result

    def run_rem_session(self, drives: Optional[dict] = None, force: bool = False) -> Optional[Any]:
        """Run a REM/dreaming session if eligible."""
        if not self.rem:
            return None
        try:
            from pulse.src.rem import SanctumConfig
            config = SanctumConfig()
            return self.rem.run_sanctum_session(
                config=config,
                workspace_root=self.workspace_root,
                drives=drives,
                force=force,
            )
        except Exception as e:
            logger.warning(f"REM session failed: {e}")
            return None

    def shutdown(self) -> dict:
        """Save all module states. Called on daemon shutdown."""
        result = {"saved": [], "failed": []}

        # Broadcast shutdown
        if self._mod_thalamus:
            try:
                self._mod_thalamus.append({
                    "source": "nervous_system",
                    "type": "shutdown",
                    "salience": 0.5,
                    "data": {"loop_count": self._loop_count},
                })
                result["saved"].append("thalamus")
            except Exception as e:
                result["failed"].append(f"thalamus: {e}")

        # SPINE — final health snapshot
        if self.spine:
            try:
                self.spine.check_health()
                result["saved"].append("spine")
            except Exception as e:
                result["failed"].append(f"spine: {e}")

        # ENDOCRINE — state is auto-saved on each operation
        result["saved"].append("endocrine")

        logger.info(
            f"🧠 NervousSystem shutdown: {len(result['saved'])} saved, "
            f"{len(result['failed'])} failed"
        )
        return result

    def get_status(self) -> dict:
        """Return current status of all modules."""
        modules = [
            "thalamus", "proprioception", "circadian", "endocrine",
            "adipose", "myelin", "immune", "cerebellum", "buffer",
            "spine", "retina", "amygdala", "vagus", "limbic",
            "enteric", "plasticity", "rem",
        ]
        status = {}
        for name in modules:
            mod = getattr(self, name, None)
            status[name] = "loaded" if mod is not None else "failed"
        status["loop_count"] = self._loop_count
        return status
