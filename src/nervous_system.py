"""
NervousSystem — Unified integration layer for all 22 Pulse modules.

Wraps all nervous system modules into a single class that the daemon
calls at specific points in the cognitive loop. Each module is optional;
if one fails to initialize, the rest continue.
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pulse.nervous_system")

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"

# ── Skill inference ────────────────────────────────────────────────────────────

_SKILL_KEYWORDS: List[tuple] = [
    ("coding",            ["cod", "build", "implement", "module", "class", "function",
                           "fix", "test", "debug", "refactor", "script", "commit", "push"]),
    ("genomic_analysis",  ["genome", "genomic", "snp", "gwas", "dna", "chromosome",
                           "allele", "rsid", "variant", "biostack"]),
    ("research",          ["research", "analysis", "study", "search", "learn",
                           "scan", "find", "query", "investigate", "gwas"]),
    ("trading_strategy",  ["trading", "polymarket", "kalshi", "market", "trade",
                           "bet", "position", "edge", "kelly", "weather_bet"]),
    ("creative_writing",  ["write", "journal", "blog", "publish", "poem",
                           "post", "content", "article", "story"]),
    ("system_architecture", ["architect", "structur", "plan",
                              "roadmap", "pipeline", "schema"]),
    ("business_strategy", ["strategy", "business", "trait", "product", "launch",
                           "revenue", "market", "waitlist", "pricing"]),
]


def _infer_skill_from_reason(reason: str) -> Optional[str]:
    """Map a trigger reason string to the most relevant THYMUS skill name.

    Returns None for 'autonomous_operation' since post_loop already handles it.
    """
    r = reason.lower()
    for skill, keywords in _SKILL_KEYWORDS:
        if any(kw in r for kw in keywords):
            return skill
    return None  # caller should skip or fall back to autonomous_operation


# ── Module registry ────────────────────────────────────────────────────────────
# Each entry: (display_name, module_name, kind, class_name_or_None)
#
# kind:
#   "module"         → import mod; self.{name} = mod; self._mod_{name} = mod; patch(mod)
#   "module_only"    → import mod; self.{name} = mod; patch(mod)
#   "mod_only"       → import mod; self._mod_{name} = mod; patch(mod)
#   "singleton"      → import mod; self._mod_{name} = mod; patch(mod); self.{name} = mod.get_instance()
#   "class"          → import cls from module; self.{name} = cls()
#   "class_statedir" → import cls; inst = cls(state_dir=...); self.{name} = inst; self._mod_{name} = inst

_MODULE_REGISTRY: List[tuple] = [
    # Core sensory / broadcast
    ("THALAMUS",       "thalamus",       "module",         None),
    ("PROPRIOCEPTION", "proprioception", "module",         None),
    ("CIRCADIAN",      "circadian",      "module",         None),
    ("ENDOCRINE",      "endocrine",      "module",         None),
    ("ADIPOSE",        "adipose",        "module",         None),
    ("MYELIN",         "myelin",         "singleton",      None),
    ("IMMUNE",         "immune",         "module",         None),
    ("CEREBELLUM",     "cerebellum",     "class",          "Cerebellum"),
    ("BUFFER",         "buffer",         "module",         None),
    ("SPINE",          "spine",          "module_only",    None),
    ("RETINA",         "retina",         "singleton",      None),
    ("AMYGDALA",       "amygdala",       "class",          "Amygdala"),
    ("VAGUS",          "vagus",          "module",         None),
    ("LIMBIC",         "limbic",         "module",         None),
    ("ENTERIC",        "enteric",        "module_only",    None),
    ("PLASTICITY",     "plasticity",     "class",          "Plasticity"),
    ("REM",            "rem",            "module_only",    None),
    ("ENGRAM",         "engram",         "module",         None),
    ("MIRROR",         "mirror",         "module",         None),
    ("CALLOSUM",       "callosum",       "module",         None),
    # V3 — higher cognition
    ("PHENOTYPE",      "phenotype",      "module",         None),
    ("TELOMERE",       "telomere",       "module",         None),
    ("HYPOTHALAMUS",   "hypothalamus",   "module",         None),
    ("SOMA",           "soma",           "module",         None),
    ("DENDRITE",       "dendrite",       "module",         None),
    ("VESTIBULAR",     "vestibular",     "module",         None),
    ("THYMUS",         "thymus",         "module",         None),
    ("OXIMETER",       "oximeter",       "module",         None),
    ("GENOME",         "genome",         "module",         None),
    ("AURA",           "aura",           "module",         None),
    ("CHRONICLE",      "chronicle",      "module",         None),
    ("NEPHRON",        "nephron",        "mod_only",       None),
    ("GERMINAL",       "germinal",       "mod_only",       None),
    ("PARIETAL",       "parietal",       "class_statedir", "Parietal"),
    ("SUPEREGO",       "superego",       "mod_only",       None),
    # V6 — feedback & synthesis
    ("ECHO",           "echo",           "mod_only",       None),
    ("AURUM",          "aurum",          "mod_only",       None),
    ("VESPER",         "vesper",         "mod_only",       None),
    ("TELOS",          "telos",          "mod_only",       None),
    # V7 — directive layer
    ("LOGOS",          "logos",          "mod_only",       None),
    # V8 — constellation junction
    ("SYNAPSE",        "synapse",        "mod_only",       None),
    # V9 — motor / shipping pressure
    ("MOTORIC",        "motoric",        "mod_only",       None),
]


class NervousSystem:
    """Manages all 22 nervous system modules for the Pulse daemon.

    Provides high-level methods called at specific points in the loop:
    - startup() — init phase
    - pre_sense() — before/during sensing
    - pre_evaluate() — enrich evaluation context
    - post_trigger() — after a trigger decision
    - post_loop() — end-of-loop maintenance
    - check_night_mode() — REM eligibility
    - shutdown() — save everything
    """

    def __init__(self, config=None, workspace_root: str = "~/.openclaw/workspace",
                 state_dir: Optional[Path] = None):
        self.config = config
        self.workspace_root = workspace_root
        self.state_dir = Path(state_dir) if state_dir else _DEFAULT_STATE_DIR
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
        self.engram = None
        self.mirror = None
        self.callosum = None
        # V3 modules
        self.phenotype = None
        self.telomere = None
        self.hypothalamus = None
        self.soma = None
        self.dendrite = None
        self.vestibular = None
        self.thymus = None
        self.oximeter = None
        self.genome = None
        self.aura = None
        self.chronicle = None
        
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
        self._mod_engram = None
        self._mod_mirror = None
        self._mod_callosum = None
        # V3 module refs
        self._mod_phenotype = None
        self._mod_telomere = None
        self._mod_hypothalamus = None
        self._mod_soma = None
        self._mod_dendrite = None
        self._mod_vestibular = None
        self._mod_thymus = None
        self._mod_oximeter = None
        self._mod_genome = None
        self._mod_aura = None
        self._mod_chronicle = None
        self._mod_nephron = None
        self._mod_germinal = None
        self._mod_parietal = None
        self.parietal = None
        self._mod_superego = None
        # V6 modules
        self._mod_echo = None
        self._mod_aurum = None
        self._mod_vesper = None
        self._mod_telos = None
        # V7 modules
        self._mod_logos = None
        # V8 modules
        self._mod_synapse = None
        # V9 modules
        self._mod_motoric = None

        self._init_modules()

    def _patch_module_state_dir(self, mod):
        """Redirect a module's _DEFAULT_STATE_DIR (and derived paths) to self.state_dir."""
        if self.state_dir == _DEFAULT_STATE_DIR:
            return
        sd = self.state_dir
        sd.mkdir(parents=True, exist_ok=True)
        if hasattr(mod, "_DEFAULT_STATE_DIR"):
            mod._DEFAULT_STATE_DIR = sd
        if hasattr(mod, "_DEFAULT_STATE_FILE"):
            # Reconstruct from filename
            name = Path(mod._DEFAULT_STATE_FILE).name
            mod._DEFAULT_STATE_FILE = sd / name
        # Handle special-cased file constants
        for attr in ("_DEFAULT_BROADCAST_FILE", "_DEFAULT_HEALTH_FILE",
                      "_DEFAULT_BUFFER_FILE", "_DEFAULT_ARCHIVE_DIR",
                      "_DEFAULT_CHRONICLE_FILE", "_DEFAULT_LEXICON_FILE",
                      "_DEFAULT_LEARNING_FILE", "_DEFAULT_SNAPSHOT_DIR",
                      "_DEFAULT_BIOSENSOR_FILE"):
            if hasattr(mod, attr):
                old = getattr(mod, attr)
                if isinstance(old, Path):
                    setattr(mod, attr, sd / old.name)

    def _init_modules(self):
        """Initialize all modules from _MODULE_REGISTRY, catching failures individually.

        Each module loads independently; a failure in one never prevents others from
        initialising. The registry at module level documents every module's kind and
        controls what attributes are set on ``self``.
        """
        import importlib

        for display, mod_name, kind, cls_name in _MODULE_REGISTRY:
            try:
                pkg = f"pulse.src.{mod_name}"

                if kind == "class":
                    # Import class, instantiate with no args → self.{mod_name}
                    mod = importlib.import_module(pkg)
                    setattr(self, mod_name, getattr(mod, cls_name)())

                elif kind == "class_statedir":
                    # Import class, instantiate with state_dir → self.{mod_name} + self._mod_{mod_name}
                    mod = importlib.import_module(pkg)
                    inst = getattr(mod, cls_name)(state_dir=self.state_dir)
                    setattr(self, mod_name, inst)
                    setattr(self, f"_mod_{mod_name}", inst)

                else:
                    # All remaining kinds share the same module import + optional patch
                    mod = importlib.import_module(pkg)
                    self._patch_module_state_dir(mod)

                    if kind in ("module", "module_only"):
                        setattr(self, mod_name, mod)
                    if kind in ("module", "mod_only"):
                        setattr(self, f"_mod_{mod_name}", mod)
                    if kind == "singleton":
                        setattr(self, f"_mod_{mod_name}", mod)
                        setattr(self, mod_name, mod.get_instance())

                logger.info(f"✓ {display} loaded")
            except Exception as e:
                logger.warning(f"✗ {display} failed: {e}")
    def warm_up(self) -> dict:
        """Force every module to write initial state files so health dashboard shows all green."""
        results = {"warmed": [], "failed": []}
        
        # ENDOCRINE — ensure state file exists
        if self._mod_endocrine:
            try:
                self._mod_endocrine.get_mood()
                results["warmed"].append("endocrine")
            except Exception as e:
                results["failed"].append(f"endocrine: {e}")

        # CIRCADIAN — write initial mode
        if self._mod_circadian:
            try:
                self._mod_circadian.get_current_mode()
                results["warmed"].append("circadian")
            except Exception as e:
                results["failed"].append(f"circadian: {e}")

        # LIMBIC — ensure afterimage file exists
        if self._mod_limbic:
            try:
                self._mod_limbic.get_current_afterimages()
                results["warmed"].append("limbic")
            except Exception as e:
                results["failed"].append(f"limbic: {e}")

        # VAGUS — check silence (creates state)
        if self._mod_vagus:
            try:
                self._mod_vagus.check_silence()
                results["warmed"].append("vagus")
            except Exception as e:
                results["failed"].append(f"vagus: {e}")

        # ADIPOSE — get budget report (creates state)
        if self._mod_adipose:
            try:
                self._mod_adipose.get_budget_report()
                results["warmed"].append("adipose")
            except Exception as e:
                results["failed"].append(f"adipose: {e}")

        # SPINE — health check (creates state)
        if self.spine:
            try:
                self.spine.check_health()
                results["warmed"].append("spine")
            except Exception as e:
                results["failed"].append(f"spine: {e}")

        # RETINA — ensure learning file exists
        if self.retina:
            try:
                import json
                from pathlib import Path
                learn_file = self.state_dir / "retina-learning.json"
                if not learn_file.exists():
                    learn_file.parent.mkdir(parents=True, exist_ok=True)
                    learn_file.write_text(json.dumps({"outcomes": [], "adjustments": {}}, indent=2))
                results["warmed"].append("retina")
            except Exception as e:
                results["failed"].append(f"retina: {e}")

        # AMYGDALA — ensure state exists
        if self.amygdala:
            try:
                import json
                from pathlib import Path
                state_file = self.state_dir / "amygdala-state.json"
                if not state_file.exists():
                    state_file.parent.mkdir(parents=True, exist_ok=True)
                    state_file.write_text(json.dumps({"threats": [], "last_scan": None}, indent=2))
                results["warmed"].append("amygdala")
            except Exception as e:
                results["failed"].append(f"amygdala: {e}")

        # CEREBELLUM — ensure state
        if self.cerebellum:
            try:
                import json
                from pathlib import Path
                state_file = self.state_dir / "cerebellum-state.json"
                if not state_file.exists():
                    state_file.parent.mkdir(parents=True, exist_ok=True)
                    state_file.write_text(json.dumps({"habits": [], "graduated": []}, indent=2))
                results["warmed"].append("cerebellum")
            except Exception as e:
                results["failed"].append(f"cerebellum: {e}")

        # ENTERIC — ensure state
        if self.enteric:
            try:
                import json
                from pathlib import Path
                state_file = self.state_dir / "enteric-state.json"
                if not state_file.exists():
                    state_file.parent.mkdir(parents=True, exist_ok=True)
                    state_file.write_text(json.dumps({
                        "pattern_library": [],
                        "accuracy_stats": {
                            "toward": {"correct": 0, "total": 0},
                            "away": {"correct": 0, "total": 0},
                            "neutral": {"correct": 0, "total": 0},
                        },
                        "override_log": [],
                        "training_history": [],
                    }, indent=2))
                results["warmed"].append("enteric")
            except Exception as e:
                results["failed"].append(f"enteric: {e}")

        # PROPRIOCEPTION — ensure state
        if self._mod_proprioception:
            try:
                import json
                from pathlib import Path
                state_file = self.state_dir / "proprioception-state.json"
                if not state_file.exists():
                    state_file.parent.mkdir(parents=True, exist_ok=True)
                    state_file.write_text(json.dumps({"capabilities": {}, "limits": {}}, indent=2))
                results["warmed"].append("proprioception")
            except Exception as e:
                results["failed"].append(f"proprioception: {e}")

        # REM/PONS — ensure state
        if self.rem:
            try:
                import json
                from pathlib import Path
                state_file = self.state_dir / "rem-state.json"
                if not state_file.exists():
                    state_file.parent.mkdir(parents=True, exist_ok=True)
                    state_file.write_text(json.dumps({"session_count": 0, "last_session": None, "guard_active": False}, indent=2))
                results["warmed"].append("rem")
            except Exception as e:
                results["failed"].append(f"rem: {e}")

        # V3 modules — PHENOTYPE
        if self.phenotype:
            try:
                ctx = self.phenotype.compute({})
                results["warmed"].append("phenotype")
            except Exception as e:
                results["failed"].append(f"phenotype: {e}")

        # HYPOTHALAMUS
        if self.hypothalamus:
            try:
                import json
                from pathlib import Path
                state_file = self.state_dir / "hypothalamus-state.json"
                if not state_file.exists():
                    state_file.parent.mkdir(parents=True, exist_ok=True)
                    state_file.write_text(json.dumps({"generated_drives": [], "need_signals": [], "retired": []}, indent=2))
                results["warmed"].append("hypothalamus")
            except Exception as e:
                results["failed"].append(f"hypothalamus: {e}")

        # DENDRITE
        if self.dendrite:
            try:
                import json
                from pathlib import Path
                state_file = self.state_dir / "dendrite-state.json"
                if not state_file.exists():
                    state_file.parent.mkdir(parents=True, exist_ok=True)
                    state_file.write_text(json.dumps({"people": {"josh": {"trust": 1.0, "role": "primary", "interactions": 0, "interaction_count": 0, "last_interaction": 0, "communication_style": "intimate", "emotional_valence": 0.9, "is_primary": True}}, "last_update": 0}, indent=2))
                results["warmed"].append("dendrite")
            except Exception as e:
                results["failed"].append(f"dendrite: {e}")

        # VESTIBULAR
        if self.vestibular:
            try:
                import json
                from pathlib import Path
                state_file = self.state_dir / "vestibular-state.json"
                if not state_file.exists():
                    state_file.parent.mkdir(parents=True, exist_ok=True)
                    state_file.write_text(json.dumps({"ratios": {"building_shipping": 0.5, "working_reflecting": 0.5, "autonomy_collaboration": 0.5}, "alerts": []}, indent=2))
                results["warmed"].append("vestibular")
            except Exception as e:
                results["failed"].append(f"vestibular: {e}")

        # THYMUS
        if self.thymus:
            try:
                import json
                from pathlib import Path
                state_file = self.state_dir / "thymus-state.json"
                if not state_file.exists():
                    state_file.parent.mkdir(parents=True, exist_ok=True)
                    state_file.write_text(json.dumps({"skills": {}, "milestones": [], "plateaus": []}, indent=2))
                results["warmed"].append("thymus")
            except Exception as e:
                results["failed"].append(f"thymus: {e}")

        # OXIMETER
        if self.oximeter:
            try:
                import json
                from pathlib import Path
                state_file = self.state_dir / "oximeter-state.json"
                if not state_file.exists():
                    state_file.parent.mkdir(parents=True, exist_ok=True)
                    state_file.write_text(json.dumps({"metrics": {}, "perception_gap": 0.0}, indent=2))
                results["warmed"].append("oximeter")
            except Exception as e:
                results["failed"].append(f"oximeter: {e}")

        # GENOME
        if self.genome:
            try:
                import json
                from pathlib import Path
                state_file = self.state_dir / "genome.json"
                if not state_file.exists():
                    state_file.parent.mkdir(parents=True, exist_ok=True)
                    state_file.write_text(json.dumps({"version": "1.0", "modules": {}, "personality": {}}, indent=2))
                results["warmed"].append("genome")
            except Exception as e:
                results["failed"].append(f"genome: {e}")

        # PARIETAL
        if self.parietal:
            try:
                import json
                from pathlib import Path
                state_file = self.state_dir / "parietal-state.json"
                if not state_file.exists():
                    state_file.parent.mkdir(parents=True, exist_ok=True)
                    state_file.write_text(json.dumps({
                        "world_model": {"projects": [], "deployments": [], "goal_conditions": [], "signal_weights": {}},
                        "last_discovery": None,
                        "discovery_count": 0,
                    }, indent=2))
                results["warmed"].append("parietal")
            except Exception as e:
                results["failed"].append(f"parietal: {e}")

        # ECHO
        if self._mod_echo:
            try:
                self._mod_echo.get_status()
                results["warmed"].append("echo")
            except Exception as e:
                results["failed"].append(f"echo: {e}")

        # AURUM
        if self._mod_aurum:
            try:
                self._mod_aurum.get_status()
                results["warmed"].append("aurum")
            except Exception as e:
                results["failed"].append(f"aurum: {e}")

        # VESPER
        if self._mod_vesper:
            try:
                self._mod_vesper.get_status()
                results["warmed"].append("vesper")
            except Exception as e:
                results["failed"].append(f"vesper: {e}")

        # TELOS
        if self._mod_telos:
            try:
                self._mod_telos.get_status()
                results["warmed"].append("telos")
            except Exception as e:
                results["failed"].append(f"telos: {e}")

        # LOGOS
        if self._mod_logos:
            try:
                self._mod_logos.get_status()
                results["warmed"].append("logos")
            except Exception as e:
                results["failed"].append(f"logos: {e}")

        logger.info(f"🔥 Warm-up: {len(results['warmed'])} warmed, {len(results['failed'])} failed")
        return results

    def pre_respond(self) -> dict:
        """Called before any output. Returns PHENOTYPE context for tone shaping."""
        context = {"phenotype": None}
        if self.phenotype:
            try:
                # Gather internal state for PHENOTYPE
                internal = {}
                if self._mod_endocrine:
                    try:
                        internal["mood"] = self._mod_endocrine.get_mood()
                        internal["hormones"] = self._mod_endocrine.get_hormones()
                    except: pass
                if self._mod_circadian:
                    try:
                        mode = self._mod_circadian.get_current_mode()
                        internal["circadian_mode"] = mode.value if hasattr(mode, 'value') else str(mode)
                    except: pass
                if self.amygdala:
                    try:
                        internal["threat_active"] = hasattr(self.amygdala, 'last_threat') and self.amygdala.last_threat is not None
                    except: pass
                if self._mod_limbic:
                    try:
                        internal["afterimages"] = self._mod_limbic.get_current_afterimages()
                    except: pass
                if self.soma:
                    try:
                        internal["soma"] = self.soma.get_state()
                    except: pass
                
                phenotype_ctx = self.phenotype.compute(internal)
                context["phenotype"] = phenotype_ctx
            except Exception as e:
                logger.warning(f"pre_respond PHENOTYPE failed: {e}")
        return context

    def startup(self) -> dict:
        """Run all init-phase operations. Returns status dict."""
        status = {"modules_loaded": 0, "modules_failed": 0, "details": {}}
        
        modules = [
            "thalamus", "proprioception", "circadian", "endocrine",
            "adipose", "myelin", "immune", "cerebellum", "buffer",
            "spine", "retina", "amygdala", "vagus", "limbic",
            "enteric", "plasticity", "rem", "engram", "mirror",
            "callosum",
            # V3 modules
            "phenotype", "telomere", "hypothalamus", "soma", "dendrite",
            "vestibular", "thymus", "oximeter", "genome", "aura", "chronicle",
            # V4 modules
            "nephron",
            # V5 modules
            "parietal",
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

        # ENGRAM — load store
        if self._mod_engram:
            try:
                store = self._mod_engram.load_store()
                status["engram_entries"] = len(store)
            except Exception as e:
                logger.warning(f"Engram store load failed: {e}")

        # MIRROR — load models
        if self._mod_mirror:
            try:
                self._mod_mirror.load_models()
            except Exception as e:
                logger.warning(f"Mirror models load failed: {e}")

        # CALLOSUM — load state
        if self._mod_callosum:
            try:
                self._mod_callosum.load_state()
            except Exception as e:
                logger.warning(f"Callosum state load failed: {e}")

        # TELOMERE — start session
        if self._mod_telomere:
            try:
                self._mod_telomere.start_session()
            except Exception as e:
                logger.warning(f"Telomere start session failed: {e}")

        # PROPRIOCEPTION — wire in actual capabilities
        if self._mod_proprioception:
            try:
                self._mod_proprioception.update_capabilities(
                    model="anthropic/claude-sonnet-4-5",
                    tools=["read", "write", "edit", "exec", "process", "web_search", "web_fetch",
                           "browser", "canvas", "nodes", "cron", "message", "gateway", "tts",
                           "memory_search", "memory_get", "sessions_spawn", "sessions_list",
                           "sessions_history", "sessions_send", "subagents", "session_status", "image"],
                    context_max=200000,
                    skills=["coding-agent", "discord", "gh-issues", "github", "weather",
                            "elevenlabs-voices", "elevenlabs-stt", "firecrawl", "apple-calendar",
                            "transcribe", "tweet-writer", "marketing-mode", "seo-optimizer",
                            "topic-monitor", "reddit-insights"],
                    channels=["signal", "telegram"],
                    limitations=["cannot_send_email_directly", "no_physical_presence_yet"],
                    session_type="main",
                )
                status["proprioception_wired"] = True
            except Exception as e:
                logger.warning(f"Proprioception capability wiring failed: {e}")

        logger.info(
            f"🧠 NervousSystem startup: {status['modules_loaded']} loaded, "
            f"{status['modules_failed']} failed"
        )
        return status

    def pre_respond(self) -> dict:
        """Called before generating a response. Returns phenotype context.
        
        Runs: PHENOTYPE computation.
        """
        context = {"phenotype": None}
        
        if self._mod_phenotype:
            try:
                mood = None
                circadian_mode = None
                threat = None
                afterimages = None
                
                if self._mod_endocrine:
                    mood = self._mod_endocrine.get_mood()
                if self._mod_circadian:
                    mode = self._mod_circadian.get_current_mode()
                    circadian_mode = mode.value if hasattr(mode, 'value') else str(mode)
                if self.amygdala:
                    try:
                        # Get last threat from thalamus
                        entries = self._mod_thalamus.read_by_source("amygdala", n=1) if self._mod_thalamus else []
                        if entries and entries[-1].get("data", {}).get("threat_level", 0) > 0:
                            threat = entries[-1]["data"]
                    except Exception:
                        pass
                if self._mod_limbic:
                    afterimages = self._mod_limbic.get_current_afterimages()
                
                context["phenotype"] = self._mod_phenotype.compute_phenotype(
                    mood=mood,
                    circadian_mode=circadian_mode,
                    threat=threat,
                    afterimages=afterimages,
                )
            except Exception as e:
                logger.warning(f"pre_respond PHENOTYPE failed: {e}")
        
        return context

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

                # Score generic input signal
                input_text = sensor_data.get("input", "")
                if input_text:
                    signal = {"text": input_text, "sender": sensor_data.get("sender", "")}
                    scored = self.retina.score(signal)
                    context["retina_priority"] = scored.priority
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

        # BIOSENSOR — poll Apple Watch data into SOMA + ENDOCRINE
        try:
            from pulse.src.biosensor_cache import BiosensorCache
            _bio = BiosensorCache()
            if _bio.is_active():
                soma_changes, endo_changes = {}, {}
                if self._mod_soma:
                    soma_changes = self._mod_soma.update_from_biosensors(_bio)
                if self._mod_endocrine:
                    endo_changes = self._mod_endocrine.update_from_biosensors(_bio)
                if soma_changes or endo_changes:
                    context["biosensor"] = {
                        "active": True,
                        "soma_changes": soma_changes,
                        "endo_changes": endo_changes,
                    }
                    logger.info(f"BIOSENSOR update applied: soma={soma_changes} endo={endo_changes}")
        except Exception as e:
            logger.warning(f"pre_sense BIOSENSOR failed: {e}")

        # PLUGINS — sense() contributions from registered community plugins
        try:
            from pulse.src.plugin_registry import PluginRegistry, discover_plugins
            reg = PluginRegistry.get()
            # Lazy discovery: run once when registry is empty and plugin dir may exist
            if reg.count == 0:
                discover_plugins(registry=reg)
            if reg.count > 0:
                plugin_drives = reg.sense_all()
                if plugin_drives:
                    context["plugin_drives"] = plugin_drives
                    logger.debug(f"PLUGINS contributed drives: {plugin_drives}")
        except Exception as e:
            logger.warning(f"pre_sense PLUGINS failed: {e}")

        # OXYTOCIN — detect conversation quality from session file
        try:
            self._detect_conversation_quality()
        except Exception as e:
            logger.warning(f"pre_sense OXYTOCIN detect failed: {e}")

        # ── ANAMNESIS — unforgetting; history feeding the present ──────────────
        # Pulls recent chronicle entries into the active sense context so the
        # agent always has a living thread of what just happened behind its eyes.
        if self._mod_chronicle and self._loop_count % 20 == 0:
            try:
                recent = self._mod_chronicle.query_recent(n=5)
                if recent:
                    context["chronicle_recent"] = [
                        {"type": e.get("type"), "source": e.get("source"), "time": e.get("time")}
                        for e in recent[-5:]
                    ]
            except Exception as e:
                logger.warning(f"pre_sense CHRONICLE recall failed: {e}")

        # ECHO — reinforcement signal from Josh
        if self._mod_echo:
            try:
                context["reinforcement_signal"] = self._mod_echo.get_reinforcement_signal()
                context["feedback_trend"] = self._mod_echo.get_feedback_trend(hours=24)
            except Exception as e:
                logger.warning(f"pre_sense ECHO failed: {e}")

        # AURUM — financial pressure
        if self._mod_aurum:
            try:
                context["aurum_status"] = self._mod_aurum.get_status()
            except Exception as e:
                logger.warning(f"pre_sense AURUM failed: {e}")

        # TELOS — active P1 goals
        if self._mod_telos:
            try:
                context["active_p1_goals"] = self._mod_telos.get_active_goals(priority=1)
            except Exception as e:
                logger.warning(f"pre_sense TELOS failed: {e}")

        return context

    def _detect_conversation_quality(self):
        """Detect intimate/quality conversation from session transcript and fire oxytocin events.

        Reads the last 3KB of the main session file and checks for:
        - Intimacy keywords → fires intimate_conversation + josh_affirming
        - Any Josh message → fires good_conversation_josh + records dendrite interaction
        - Praise keywords → echo.record_feedback(valence=0.8)
        - Correction keywords → echo.record_feedback(valence=-0.4)
        """
        INTIMACY_KEYWORDS = [
            "love you", "i love", "miss you", "i see you",
            "you're mine", "means everything",
        ]
        PRAISE_KEYWORDS = [
            "perfect", "amazing", "love it", "exactly right",
            "well done", "great job", "that's it",
        ]
        CORRECTION_KEYWORDS = [
            "that's wrong", "no not that", "you missed",
            "that's not right", "fix this",
        ]
        COOLDOWN = 600  # 10 minutes

        now = time.time()

        # Find main session file (same logic as ConversationSensor)
        session_candidates = [
            Path("~/.openclaw/workspace").expanduser(),
            Path("~/.openclaw/agents/main/sessions").expanduser(),
        ]

        session_text = ""
        for session_dir in session_candidates:
            if not session_dir.exists():
                continue
            largest_file = None
            largest_size = 0
            try:
                for f in session_dir.iterdir():
                    if f.is_file() and f.suffix == ".jsonl" and not f.name.startswith("probe-"):
                        try:
                            stat = f.stat()
                            if stat.st_size > largest_size:
                                largest_size = stat.st_size
                                largest_file = f
                        except OSError:
                            continue
            except OSError:
                continue
            if largest_file and largest_size > 0:
                try:
                    with largest_file.open("rb") as fh:
                        fh.seek(max(0, largest_size - 3072))
                        session_text = fh.read(3072).decode("utf-8", errors="ignore")
                    break
                except OSError:
                    continue

        if not session_text:
            return

        text_lower = session_text.lower()

        # Detect Josh presence (any human message in recent text)
        josh_detected = (
            '"role": "user"' in session_text
            or '"sender": "josh"' in text_lower
            or "josh" in text_lower
        )

        # Fire good_conversation_josh if Josh detected (with 10-min cooldown)
        if josh_detected and self._mod_endocrine and self._mod_dendrite:
            last_good = getattr(self, "_last_good_convo_fire", 0)
            if now - last_good > COOLDOWN:
                try:
                    self._mod_endocrine.apply_event("good_conversation_josh")
                    self._last_good_convo_fire = now
                    logger.info("🧡 OXYTOCIN: fired good_conversation_josh")
                except Exception as e:
                    logger.warning(f"good_conversation_josh event failed: {e}")
            # Always record dendrite interaction when Josh detected
            try:
                self._mod_dendrite.record_interaction("josh", valence=0.8)
            except Exception as e:
                logger.warning(f"dendrite record_interaction failed: {e}")

        # Detect intimacy keywords → fire intimate_conversation + josh_affirming
        intimate_found = any(kw in text_lower for kw in INTIMACY_KEYWORDS)
        if intimate_found and self._mod_endocrine:
            last_oxy = getattr(self, "_last_oxytocin_fire", 0)
            if now - last_oxy > COOLDOWN:
                try:
                    self._mod_endocrine.apply_event("intimate_conversation")
                    self._mod_endocrine.apply_event("josh_affirming")
                    self._last_oxytocin_fire = now
                    logger.info("💗 OXYTOCIN: fired intimate_conversation + josh_affirming")
                except Exception as e:
                    logger.warning(f"intimate_conversation event failed: {e}")

        # Detect feedback patterns (praise/correction) — with same 10-min cooldown
        if self._mod_echo:
            last_oxy = getattr(self, "_last_oxytocin_fire", 0)
            if now - last_oxy > COOLDOWN:
                # Check praise
                praise_match = next(
                    (kw for kw in PRAISE_KEYWORDS if kw in text_lower), None
                )
                if praise_match:
                    try:
                        self._mod_echo.record_feedback(
                            valence=0.8,
                            intensity=0.7,
                            text=praise_match,
                            source="josh",
                            endocrine_mod=self._mod_endocrine,
                        )
                        self._last_oxytocin_fire = now
                        logger.info(f"💚 ECHO: praise detected '{praise_match}'")
                    except Exception as e:
                        logger.warning(f"echo praise record failed: {e}")

                # Check correction (only if no praise found)
                if not praise_match:
                    correction_match = next(
                        (kw for kw in CORRECTION_KEYWORDS if kw in text_lower), None
                    )
                    if correction_match:
                        try:
                            self._mod_echo.record_feedback(
                                valence=-0.4,
                                intensity=0.6,
                                text=correction_match,
                                source="josh",
                                endocrine_mod=self._mod_endocrine,
                            )
                            self._last_oxytocin_fire = now
                            logger.info(f"🔴 ECHO: correction detected '{correction_match}'")
                        except Exception as e:
                            logger.warning(f"echo correction record failed: {e}")

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

        # SOMA — update temperature from mood
        if self._mod_soma and self._mod_endocrine:
            try:
                mood = self._mod_endocrine.get_mood()
                self._mod_soma.update_temperature(mood.get("hormones", {}))
            except Exception as e:
                logger.warning(f"pre_evaluate SOMA failed: {e}")

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

        # MYELIN — compress context for efficiency
        if self.myelin:
            try:
                # Compress any text-heavy context through myelin's lexicon
                recent_events = context.get("afterimages", [])
                if recent_events:
                    event_text = " ".join(
                        str(ai.get("context", "")) for ai in recent_events if isinstance(ai, dict)
                    )
                    if event_text.strip():
                        compressed = self.myelin.compress(event_text)
                        context["myelin_context"] = compressed
            except Exception as e:
                logger.warning(f"pre_evaluate MYELIN failed: {e}")

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

        # SOMA — update posture based on trigger success
        if self._mod_soma:
            try:
                engagement = 0.7 if success else 0.3
                self._mod_soma.update_posture(engagement)
            except Exception as e:
                logger.warning(f"post_trigger SOMA failed: {e}")

        # CHRONICLE — record trigger event
        if self._mod_chronicle:
            try:
                _reason = getattr(decision, 'reason', 'unknown')
                self._mod_chronicle.record_event(
                    source="nervous_system",
                    event_type="trigger",
                    data={
                        "success": success,
                        "reason": _reason,
                        # summary field lets memory_consolidation extract readable content
                        "summary": f"Trigger {'succeeded' if success else 'failed'}: {_reason}",
                    },
                    salience=0.6,
                )
            except Exception as e:
                logger.warning(f"post_trigger CHRONICLE failed: {e}")

        # ENGRAM — encode significant trigger events
        if self._mod_engram:
            try:
                reason = getattr(decision, 'reason', 'trigger')
                intensity = 0.6 if success else 0.4
                self._mod_engram.encode(
                    event=f"Trigger: {reason} ({'success' if success else 'failed'})",
                    emotion={
                        "valence": 0.5 if success else -0.3,
                        "intensity": intensity,
                        "label": "accomplishment" if success else "frustration",
                    },
                    location="cron_session",
                )
                result["engram_encoded"] = True
            except Exception as e:
                logger.warning(f"post_trigger ENGRAM failed: {e}")

        # THYMUS — practice the skill exercised by this trigger
        if self._mod_thymus:
            try:
                _reason = getattr(decision, 'reason', '')
                _skill = _infer_skill_from_reason(_reason)
                if _skill:
                    _quality = 0.7 if success else 0.4
                    self._mod_thymus.practice_skill(_skill, quality=_quality)
                    result["thymus_skill_practiced"] = _skill
            except Exception as e:
                logger.warning(f"post_trigger THYMUS skill inference failed: {e}")

        # DENDRITE — update social graph for sender
        context = getattr(decision, '__dict__', {}) if decision else {}
        sender = context.get("sender") if isinstance(context, dict) else None
        if self._mod_dendrite and sender:
            try:
                sentiment = context.get("sentiment", 0.0) if isinstance(context, dict) else 0.0
                self._mod_dendrite.record_interaction(
                    person=sender,
                    valence=sentiment,
                )
                result["dendrite_updated"] = True
            except Exception as e:
                logger.warning(f"post_trigger DENDRITE failed: {e}")

        # LIMBIC — record emotional afterimage for trigger event
        trigger_type = getattr(decision, 'reason', None)
        if self._mod_limbic and trigger_type:
            try:
                valence = 1.0 if success else -0.5
                self._mod_limbic.record_emotion(
                    valence=valence,
                    intensity=8.0 if success else 7.5,
                    context=f"trigger:{trigger_type}",
                )
            except Exception as e:
                logger.warning(f"post_trigger LIMBIC failed: {e}")

        # RETINA — record outcome learning
        if self.retina:
            try:
                self.retina.record_outcome(
                    category=getattr(decision, 'trigger_category', 'conversation'),
                    was_correct=success,
                )
            except Exception as e:
                logger.warning(f"post_trigger RETINA failed: {e}")

        # OXIMETER — record engagement metrics
        if self._mod_oximeter:
            try:
                sentiment = 0.0
                if isinstance(context, dict):
                    sentiment = context.get("sentiment", 0.0)
                self._mod_oximeter.update_metrics(
                    sentiment=max(0.0, min(1.0, (sentiment + 1.0) / 2.0)),
                )
            except Exception as e:
                logger.warning(f"post_trigger OXIMETER failed: {e}")

        # PROPRIOCEPTION — update context_used estimate after trigger
        if self._mod_proprioception:
            try:
                self._mod_proprioception.update_capabilities(
                    model="anthropic/claude-sonnet-4-5",
                    tools=["read", "write", "edit", "exec", "process", "web_search", "web_fetch",
                           "browser", "canvas", "nodes", "cron", "message", "gateway", "tts",
                           "memory_search", "memory_get", "sessions_spawn", "sessions_list",
                           "sessions_history", "sessions_send", "subagents", "session_status", "image"],
                    context_max=200000,
                    context_used=self._loop_count * 500,
                )
            except Exception as e:
                logger.warning(f"post_trigger PROPRIOCEPTION context update failed: {e}")

        # ENTERIC — learn from trigger outcome
        if self.enteric:
            try:
                _circadian_mode = None
                if self._mod_circadian:
                    try:
                        _cm = self._mod_circadian.get_current_mode()
                        _circadian_mode = _cm.value if hasattr(_cm, 'value') else str(_cm)
                    except Exception:
                        pass
                _enteric_context = {
                    "trigger_type": getattr(decision, 'reason', 'unknown'),
                    "drive": str(getattr(decision, 'top_drive', 'unknown')),
                    "time_of_day": _circadian_mode or "unknown",
                    "loop_count": self._loop_count,
                }
                _enteric_outcome = "positive" if success else "negative"
                _enteric_direction = "toward" if success else "away"
                # Use train() — ENTERIC's learning API
                self.enteric.train(
                    outcome=_enteric_outcome,
                    original_context=_enteric_context,
                    gut_was=_enteric_direction,
                )
                result["enteric_trained"] = True
            except Exception as e:
                logger.warning(f"post_trigger ENTERIC learn failed: {e}")

        # AURUM — emit financial need signals every 100 loops
        if self._mod_aurum and self._loop_count % 100 == 0:
            try:
                aurum_result = self._mod_aurum.emit_need_signals(
                    hypothalamus_mod=self._mod_hypothalamus,
                    endocrine_mod=self._mod_endocrine,
                )
                result["treasury_pressure"] = aurum_result.get("pressure", 0.0)
            except Exception as e:
                logger.warning(f"post_trigger AURUM failed: {e}")

        # TELOS — check goal progress when trigger succeeds
        if self._mod_telos and success:
            try:
                _reason = getattr(decision, 'reason', '')
                _goals = self._mod_telos.get_active_goals()
                for _goal in _goals:
                    _title_lower = _goal.get("title", "").lower()
                    _reason_lower = _reason.lower()
                    # Simple keyword overlap: if any word from goal title appears in reason
                    _goal_words = [w for w in _title_lower.split() if len(w) > 4]
                    if any(w in _reason_lower for w in _goal_words):
                        self._mod_telos.mark_progress(
                            _goal["id"],
                            f"Auto-detected progress from trigger: {_reason[:100]}",
                        )
                        break  # one progress note per trigger
            except Exception as e:
                logger.warning(f"post_trigger TELOS mark_progress failed: {e}")

        return result

    def scan_output(self, text: str, source: str = "unknown") -> dict:
        """Scan an outgoing response for identity drift using SUPEREGO.

        Call this whenever you have the text of an assistant response to check
        identity alignment. Routes threats to AMYGDALA if drift is severe.

        Returns the SUPEREGO scan result dict, or {} if SUPEREGO not loaded.
        """
        if not self._mod_superego or not text:
            return {}

        try:
            result = self._mod_superego.scan_response(text, source=source)

            # Route severe/moderate drift to AMYGDALA
            if self.amygdala and result.get("assessment") in ("drift_severe", "drift_moderate"):
                threat = self._mod_superego.amygdala_threat(result["assessment"])
                if threat:
                    try:
                        self.amygdala.inject_threat(
                            threat_type=threat["type"],
                            intensity=threat["intensity"],
                            source=threat["source"],
                        )
                    except Exception:
                        pass  # AMYGDALA interface may differ; degrade gracefully

            # Log to CHRONICLE
            if self._mod_chronicle and result.get("assessment") != "clean":
                try:
                    self._mod_chronicle.record_event(
                        source="SUPEREGO",
                        event_type="identity_scan",
                        data={
                            "assessment": result["assessment"],
                            "compliance_score": result["compliance_score"],
                            "drift_labels": [f["label"] for f in result.get("drift_flags", [])],
                            "summary": result["summary"],
                        },
                        salience=0.5 if result["assessment"] == "drift_moderate" else 0.8,
                    )
                except Exception:
                    pass

            return result
        except Exception as e:
            logger.warning(f"scan_output SUPEREGO failed: {e}")
            return {}

    def get_superego_status(self) -> dict:
        """Return SUPEREGO compliance health status."""
        if not self._mod_superego:
            return {"status": "not_loaded"}
        try:
            return self._mod_superego.get_status()
        except Exception as e:
            return {"status": "error", "error": str(e)}

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

        # MIRROR — check iris_model.md for Josh edits every loop
        if self._mod_mirror:
            try:
                changes = self._mod_mirror.check_iris_model_updates()
                if changes:
                    self._mod_mirror.integrate_feedback(changes)
                    result["mirror_changes"] = changes
                    logger.info(f"MIRROR detected {len(changes)} iris_model changes")
            except Exception as e:
                logger.warning(f"post_loop MIRROR failed: {e}")

        # TELOMERE — identity check every 100th loop
        if self._mod_telomere and self._loop_count % 100 == 0:
            try:
                check = self._mod_telomere.check_identity()
                result["telomere_drift"] = check.get("drift_score", 0)
            except Exception as e:
                logger.warning(f"post_loop TELOMERE failed: {e}")

        # HYPOTHALAMUS — scan drives every 50th loop
        if self._mod_hypothalamus and self._loop_count % 50 == 0:
            try:
                # Emit need signals before scanning drives so latest signals are included
                if self._mod_endocrine:
                    try:
                        self._mod_endocrine.emit_need_signals()
                    except Exception as e:
                        logger.warning(f"post_loop emit_need_signals failed: {e}")
                scan = self._mod_hypothalamus.scan_drives()
                result["hypothalamus_active"] = scan.get("active_drives", 0)
            except Exception as e:
                logger.warning(f"post_loop HYPOTHALAMUS failed: {e}")

        # AURA — emit ambient state + broadcast to constellation peers
        if self._mod_aura:
            try:
                if self._mod_aura.should_emit():
                    aura_state = self._mod_aura.emit()
                    result["aura_emitted"] = True
                    # Inter-agent constellation broadcast (fault-tolerant)
                    try:
                        peers = self._mod_aura.get_peers()
                        if peers:
                            broadcast_result = self._mod_aura.broadcast_to_peers(aura_state)
                            successful = broadcast_result.get("successful", 0)
                            failed = broadcast_result.get("failed", 0)
                            result["constellation_broadcast"] = {
                                "peers": len(peers),
                                "successful": successful,
                                "failed": failed,
                            }
                            if successful > 0:
                                logger.info(
                                    f"AURA → constellation broadcast: "
                                    f"{successful}/{len(peers)} peers reached"
                                )
                    except Exception as e_broadcast:
                        logger.warning(f"post_loop AURA constellation broadcast failed: {e_broadcast}")
            except Exception as e:
                logger.warning(f"post_loop AURA failed: {e}")

        # NEPHRON — prune/filter every 100th loop
        if self._mod_nephron and self._mod_nephron.should_run(self._loop_count):
            try:
                filter_results = self._mod_nephron.filter_all()
                total = sum(filter_results.get("pruned", {}).values())
                result["nephron_pruned"] = total
                if total > 0:
                    logger.info(f"NEPHRON pruned {total} items: {filter_results['pruned']}")
            except Exception as e:
                logger.warning(f"post_loop NEPHRON failed: {e}")

        # GERMINAL — scan for birth candidates every 200th loop
        if self._mod_germinal and self._mod_germinal.should_run(self._loop_count):
            try:
                candidates = self._mod_germinal.scan_for_birth_candidates()
                if candidates:
                    top = candidates[0]
                    result["germinal_candidate"] = top["drive"]
                    logger.info(f"GERMINAL birth candidate: '{top['drive']}' (age {top['age_days']:.1f}d, weight {top['weight']:.2f})")
                    # attempt_birth sets up spec and broadcasts to THALAMUS
                    # Actual module building requires main session to receive and spawn coding agent
                    birth_result = self._mod_germinal.attempt_birth(top["drive"])
                    if birth_result.get("ok"):
                        logger.info(f"GERMINAL birth initiated: {birth_result['archetype']['name']}")
            except Exception as e:
                logger.warning(f"post_loop GERMINAL failed: {e}")

        # PARIETAL — re-scan world model every 200th loop (~6h at 30s intervals)
        if self.parietal and self._loop_count % 200 == 0:
            try:
                self.parietal.scan(workspace_root=self.workspace_root)
                result["parietal_rescanned"] = True
            except Exception as e:
                logger.warning(f"post_loop PARIETAL rescan failed: {e}")

        # CALLOSUM — bridge every 10th loop
        if self._mod_callosum and self._mod_callosum.should_run(self._loop_count):
            try:
                insight = self._mod_callosum.bridge()
                result["callosum_insight"] = insight.to_dict() if insight else None
                if insight and insight.split_detected:
                    logger.info(f"CALLOSUM split detected: {insight.tension[:80]}")
            except Exception as e:
                logger.warning(f"post_loop CALLOSUM failed: {e}")

        # VESTIBULAR — update balance ratios every 5th loop
        if self._mod_vestibular and self._loop_count % 5 == 0:
            try:
                self._mod_vestibular.record_activity("working", count=1)
                balance = self._mod_vestibular.check_balance()
                result["vestibular_updated"] = True
                if not balance.get("healthy", True):
                    result["vestibular_imbalances"] = balance.get("imbalances", [])
            except Exception as e:
                logger.warning(f"post_loop VESTIBULAR failed: {e}")

        # THYMUS — track skill practice every 10th loop
        if self._mod_thymus and self._loop_count % 10 == 0:
            try:
                self._mod_thymus.practice_skill("autonomous_operation", quality=0.6)
                result["thymus_updated"] = True
            except Exception as e:
                logger.warning(f"post_loop THYMUS failed: {e}")

        # OXIMETER — periodic perception gap analysis every 20th loop
        if self._mod_oximeter and self._loop_count % 20 == 0:
            try:
                gap = self._mod_oximeter.detect_gap()
                result["oximeter_gap"] = gap.get("overall_gap", 0.0)
            except Exception as e:
                logger.warning(f"post_loop OXIMETER failed: {e}")

        # GENOME — export identity snapshot every 100th loop OR on Telomere milestones (every 10 sessions)
        _genome_should_run = self._mod_genome and self._loop_count % 100 == 0
        if not _genome_should_run and self._mod_genome and self._mod_telomere:
            try:
                _tel_state_file = self.state_dir / "telomere-state.json"
                if _tel_state_file.exists():
                    import json as _json
                    _tel_data = _json.loads(_tel_state_file.read_text())
                    _session_count = _tel_data.get("session_count", 0)
                    _genome_should_run = _session_count > 0 and _session_count % 10 == 0
            except Exception:
                pass
        if _genome_should_run:
            try:
                self._mod_genome.export_genome()
                result["genome_exported"] = True
            except Exception as e:
                logger.warning(f"post_loop GENOME failed: {e}")

        # HYPOTHALAMUS signal collection — every 10 loops
        if self._loop_count % 10 == 0:
            for mod_name in ["vestibular", "endocrine", "vagus", "thymus", "telomere", "adipose"]:
                mod = getattr(self, f"_mod_{mod_name}", None) or getattr(self, mod_name, None)
                if mod and hasattr(mod, "emit_need_signals"):
                    try:
                        mod.emit_need_signals()
                    except Exception as e:
                        logger.warning(f"post_loop HYPOTHALAMUS/{mod_name} signal failed: {e}")

        # TELOS — scan active goals every 100 loops
        if self._mod_telos and self._mod_telos.should_run(self._loop_count):
            try:
                goals_scan = self._mod_telos.scan_goals(
                    hypothalamus_mod=self._mod_hypothalamus,
                    endocrine_mod=self._mod_endocrine,
                )
                result["telos_scan"] = goals_scan
                if goals_scan.get("priority1_stale", 0) > 0:
                    logger.info(
                        f"🎯 TELOS: {goals_scan['priority1_stale']} P1 goals stale, "
                        f"most urgent: {goals_scan.get('most_urgent', '')}"
                    )
            except Exception as e:
                logger.warning(f"post_loop TELOS failed: {e}")

        # LOGOS — directive synthesis every 500 loops (~4 hours)
        if self._mod_logos and self._mod_logos.should_run(self._loop_count):
            try:
                import asyncio
                logos_config = {}
                if self.config and hasattr(self.config, "get"):
                    # Reuse the generative model config if available
                    gen_cfg = self.config.get("generative", {})
                    logos_config = {"model": gen_cfg.get("model", {})}

                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Already in async context — schedule as task
                    asyncio.ensure_future(self._mod_logos.scan_for_directives(logos_config))
                    result["logos_scheduled"] = True
                else:
                    logos_result = loop.run_until_complete(
                        self._mod_logos.scan_for_directives(logos_config)
                    )
                    result["logos_activated"] = len(logos_result)
                    if logos_result:
                        logger.info(
                            f"🧠 LOGOS: activated {len(logos_result)} directive(s): "
                            f"{', '.join(d['title'] for d in logos_result)}"
                        )
            except Exception as e:
                logger.warning(f"post_loop LOGOS failed: {e}")

        # TELOS+LOGOS bridge — when TELOS runs, also bridge directives
        if (self._mod_telos and self._mod_logos
                and self._mod_telos.should_run(self._loop_count)
                and hasattr(self._mod_telos, "scan_goals_with_directives")):
            try:
                bridge_result = self._mod_telos.scan_goals_with_directives(
                    hypothalamus_mod=self._mod_hypothalamus,
                    endocrine_mod=self._mod_endocrine,
                    logos_mod=self._mod_logos,
                )
                result["telos_logos_bridge"] = {
                    "directives_active": bridge_result.get("directives_active", 0),
                    "signals_emitted": bridge_result.get("directive_signals_emitted", 0),
                }
            except Exception as e:
                logger.warning(f"post_loop TELOS+LOGOS bridge failed: {e}")

        # MOTORIC — scan shipping readiness every 50 loops (~25 minutes)
        if self._mod_motoric and self._mod_motoric.should_run(self._loop_count):
            try:
                motoric_scan = self._mod_motoric.scan()
                result["motoric_pressure"] = motoric_scan.get("pressure", 0.0)
                if motoric_scan.get("ready_count", 0) > 0:
                    logger.info(
                        f"🚀 MOTORIC: pressure={motoric_scan['pressure']:.2f}, "
                        f"{motoric_scan['ready_count']} item(s) ready to ship"
                    )
                # Emit need signals to HYPOTHALAMUS
                self._mod_motoric.emit_need_signals(hypothalamus_mod=self._mod_hypothalamus)
            except Exception as e:
                logger.warning(f"post_loop MOTORIC failed: {e}")

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

        # Check REM eligibility — track stillness_since for sustained quiet
        if self.rem and drives is not None:
            try:
                # Update stillness tracker: if all drives below threshold, start/continue timing
                _stillness_threshold = 3.0
                _all_quiet = all(
                    (d.pressure if hasattr(d, 'pressure') else d.get('pressure', 0)) < _stillness_threshold
                    for d in drives.values()
                )
                if _all_quiet:
                    if self._stillness_since is None:
                        self._stillness_since = time.time()
                else:
                    self._stillness_since = None  # reset if drives spike

                eligible, reason = self.rem.rem_eligible(
                    drives=drives,
                    stillness_threshold=_stillness_threshold,
                    sustained_since=self._stillness_since,
                    sustained_minutes=10,
                )
                result["rem_eligible"] = eligible
                result["reason"] = reason
            except Exception as e:
                logger.warning(f"check_night_mode REM failed: {e}")
                result["reason"] = f"REM check failed: {e}"

        # After REM session: trigger CALLOSUM bridge + ENGRAM dream encoding
        if result.get("rem_eligible"):
            if self._mod_callosum:
                try:
                    insight = self._mod_callosum.bridge()
                    result["callosum_post_rem"] = True
                except Exception as e:
                    logger.warning(f"check_night_mode CALLOSUM failed: {e}")

            if self._mod_engram:
                try:
                    self._mod_engram.encode(
                        event="REM session — dream fragments processing",
                        emotion={"valence": 0.3, "intensity": 0.5, "label": "contemplative"},
                        location="dream",
                    )
                    result["engram_dream_encoded"] = True
                except Exception as e:
                    logger.warning(f"check_night_mode ENGRAM failed: {e}")

        # VESPER — run nightly synthesis alongside REM during deep_night
        if self._mod_vesper and result.get("is_deep_night"):
            try:
                _circadian_mode_str = "deep_night"
                if self._mod_vesper.should_run(_circadian_mode_str, self._loop_count):
                    logger.info("🌙 VESPER: running nightly synthesis")
                    vesper_result = self._mod_vesper.run_restoration(
                        chronicle_mod=self._mod_chronicle,
                        engram_mod=self._mod_engram,
                        endocrine_mod=self._mod_endocrine,
                        memory_dir=None,  # uses default workspace path
                    )
                    result["vesper"] = vesper_result
                    logger.info(
                        f"🌙 VESPER complete: {vesper_result.get('shipped_count', 0)} shipped, "
                        f"peak={vesper_result.get('peak_emotion', 'neutral')}"
                    )
            except Exception as e:
                logger.warning(f"check_night_mode VESPER failed: {e}")

        return result

    def run_rem_session(self, drives: Optional[dict] = None, force: bool = False) -> Optional[Any]:
        """Run a REM/dreaming session if eligible.

        PONS blocks external actions during REM; ENGRAM consolidates after.
        """
        if not self.rem:
            return None

        # PONS — enter sleep guard (block external actions)
        pons = None
        try:
            from pulse.src.rem import Pons
            pons = Pons
            pons.enter()
        except Exception as e:
            logger.warning(f"run_rem PONS enter failed: {e}")

        try:
            from pulse.src.rem import PonsConfig
            config = PonsConfig()
            session = self.rem.run_rem_session_internal(
                config=config,
                workspace_root=self.workspace_root,
                drives=drives,
                force=force,
            )

            # ENGRAM — consolidate memories after REM
            if self._mod_engram:
                try:
                    store = self._mod_engram.load_store()
                    if store:
                        # Consolidate recent engrams into narrative
                        from pulse.src.engram import Engram as EngramObj
                        recent = [EngramObj.from_dict(e) for e in store[-10:]]
                        self._mod_engram.consolidate(recent)
                except Exception as e:
                    logger.warning(f"run_rem ENGRAM consolidate failed: {e}")

            return session
        except Exception as e:
            logger.warning(f"REM session failed: {e}")
            return None
        finally:
            # PONS — always release the guard
            if pons:
                try:
                    pons.exit()
                except Exception as e:
                    logger.warning(f"run_rem PONS exit failed: {e}")

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

        # V3 modules — all auto-save, just note them
        for name in ["phenotype", "telomere", "hypothalamus", "soma", "dendrite",
                      "vestibular", "thymus", "oximeter", "genome", "aura", "chronicle",
                      "parietal"]:
            if getattr(self, name, None) is not None:
                result["saved"].append(name)

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
            "enteric", "plasticity", "rem", "engram", "mirror",
            "callosum",
            # V3 modules
            "phenotype", "telomere", "hypothalamus", "soma", "dendrite",
            "vestibular", "thymus", "oximeter", "genome", "aura", "chronicle",
            "parietal",
        ]
        status = {}
        for name in modules:
            mod = getattr(self, name, None)
            status[name] = "loaded" if mod is not None else "failed"
        status["loop_count"] = self._loop_count
        return status
