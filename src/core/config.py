"""
Pulse Configuration — loads and validates pulse.yaml
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml


@dataclass
class OpenClawConfig:
    webhook_url: str = "http://127.0.0.1:18789/hooks/agent"
    webhook_token: str = ""
    message_prefix: str = "[PULSE]"
    max_turns_per_hour: int = 10
    min_trigger_interval: int = 300  # seconds
    # Session mode: "main" = inject into main session, "isolated" = spawn separate session
    session_mode: str = "isolated"
    # Delivery: announce results back to channel (only applies in isolated mode)
    deliver: bool = True
    # Model override for isolated sessions (None = use default)
    isolated_model: Optional[str] = None


@dataclass
class WorkspaceConfig:
    root: str = "~/.openclaw/workspace"
    goals: str = "scripts/goals.py"
    curiosity: str = "memory/self/curiosity.json"
    emotions: str = "memory/self/emotional-landscape.json"
    hypotheses: str = "memory/self/hypotheses.json"
    trust_scores: str = "memory/self/trust-scores.json"
    values: str = "memory/self/discovered-values.md"
    working_memory: str = "memory/self/working-memory.json"
    evolution: str = "memory/self/evolution.json"
    daily_notes: str = "memory/"

    def resolve_path(self, key: str) -> Path:
        """Resolve a workspace-relative path to absolute."""
        root = Path(self.root).expanduser()
        return root / getattr(self, key)


@dataclass 
class DriveCategory:
    weight: float = 1.0
    source: str = ""


@dataclass
class DrivesConfig:
    pressure_rate: float = 0.01
    trigger_threshold: float = 0.7
    max_pressure: float = 5.0
    success_decay: float = 0.5
    failure_boost: float = 0.2
    override_min_individual_pressure: float = 1.5  # min weighted_pressure for high-pressure override
    adaptive_decay: bool = True  # scale decay with total pressure
    categories: Dict[str, DriveCategory] = field(default_factory=dict)


@dataclass
class FilesystemSensorConfig:
    enabled: bool = True
    watch_paths: List[str] = field(default_factory=list)
    ignore_patterns: List[str] = field(default_factory=list)
    ignore_self_writes: bool = True


@dataclass
class DiscordSensorConfig:
    enabled: bool = False
    channels: List[str] = field(default_factory=list)
    silence_threshold_minutes: int = 180


@dataclass
class SystemSensorConfig:
    enabled: bool = True
    memory_threshold_percent: int = 85
    watch_processes: List[str] = field(default_factory=list)


@dataclass
class SensorsConfig:
    filesystem: FilesystemSensorConfig = field(default_factory=FilesystemSensorConfig)
    discord: DiscordSensorConfig = field(default_factory=DiscordSensorConfig)
    system: SystemSensorConfig = field(default_factory=SystemSensorConfig)


@dataclass
class RulesConfig:
    single_drive_threshold: float = 0.8
    combined_threshold: float = 0.7
    suppress_during_conversation: bool = True
    conversation_cooldown_minutes: int = 5


@dataclass
class ModelEvalConfig:
    base_url: str = "http://127.0.0.1:11434/v1"  # ollama default
    api_key: str = "ollama"
    model: str = "llama3.2:3b"
    max_tokens: int = 512
    temperature: float = 0.3
    timeout_seconds: int = 10
    max_suppress_minutes: int = 30  # cap on model-requested suppress_minutes


@dataclass
class EvaluatorConfig:
    mode: str = "rules"  # "rules" or "model"
    rules: RulesConfig = field(default_factory=RulesConfig)
    model: ModelEvalConfig = field(default_factory=ModelEvalConfig)


@dataclass
class StateConfig:
    dir: str = "~/.pulse/state"
    save_interval: int = 60
    history_retention_days: int = 30


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "~/.pulse/logs/pulse.log"
    sync_to_daily_notes: bool = True


@dataclass
class GenerativeConfig:
    enabled: bool = True
    roadmap_files: List[str] = field(default_factory=lambda: ["TIERS.md", "ROADMAP.md", "TODO.md"])
    max_tasks: int = 3
    auto_add_to_goals: bool = False
    min_idle_minutes: int = 15


@dataclass
class DaemonConfig:
    loop_interval_seconds: int = 30
    shutdown_timeout: int = 10
    pid_file: str = "~/.pulse/pulse.pid"
    health_port: int = 9720
    integration: str = "default"  # "default" or "iris" (or custom module path)


@dataclass
class ParietalConfig:
    enabled: bool = True
    scan_interval_hours: float = 6.0
    workspace_root: str = "~/.openclaw/workspace"
    use_llm_inference: bool = True
    max_projects: int = 50
    max_sensors_per_project: int = 5
    ignored_dirs: List[str] = field(default_factory=lambda: [
        ".git", "node_modules", "__pycache__", "venv", ".venv", "dist", "build",
    ])


@dataclass
class PulseConfig:
    openclaw: OpenClawConfig = field(default_factory=OpenClawConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    drives: DrivesConfig = field(default_factory=DrivesConfig)
    sensors: SensorsConfig = field(default_factory=SensorsConfig)
    evaluator: EvaluatorConfig = field(default_factory=EvaluatorConfig)
    state: StateConfig = field(default_factory=StateConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    daemon: DaemonConfig = field(default_factory=DaemonConfig)
    generative: GenerativeConfig = field(default_factory=GenerativeConfig)
    parietal: ParietalConfig = field(default_factory=ParietalConfig)

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "PulseConfig":
        """Load config from YAML file, falling back to defaults."""
        if config_path is None:
            # Search order: ./pulse.yaml, ~/.pulse/pulse.yaml, config/pulse.yaml
            candidates = [
                Path("pulse.yaml"),
                Path("~/.pulse/pulse.yaml").expanduser(),
                Path(__file__).parent.parent.parent / "config" / "pulse.yaml",
            ]
            for candidate in candidates:
                if candidate.exists():
                    config_path = str(candidate)
                    break

        if config_path and Path(config_path).exists():
            cls._check_config_permissions(config_path)
            with open(config_path) as f:
                raw = yaml.safe_load(f) or {}
            return cls._from_dict(raw)

        return cls()

    @classmethod
    def _from_dict(cls, data: dict) -> "PulseConfig":
        """Recursively build config from dict, applying env var substitution."""
        config = cls()

        if "openclaw" in data:
            oc = data["openclaw"]
            config.openclaw = OpenClawConfig(
                webhook_url=cls._resolve_env(oc.get("webhook_url", config.openclaw.webhook_url)),
                webhook_token=cls._resolve_env(oc.get("webhook_token", config.openclaw.webhook_token), required=True),
                message_prefix=oc.get("message_prefix", config.openclaw.message_prefix),
                max_turns_per_hour=oc.get("max_turns_per_hour", config.openclaw.max_turns_per_hour),
                min_trigger_interval=oc.get("min_trigger_interval", config.openclaw.min_trigger_interval),
                session_mode=oc.get("session_mode", config.openclaw.session_mode),
                deliver=oc.get("deliver", config.openclaw.deliver),
                isolated_model=oc.get("isolated_model", config.openclaw.isolated_model),
            )

        if "workspace" in data:
            ws = data["workspace"]
            config.workspace = WorkspaceConfig(**{
                k: ws.get(k, getattr(config.workspace, k))
                for k in WorkspaceConfig.__dataclass_fields__
            })

        if "drives" in data:
            d = data["drives"]
            categories = {}
            for name, cat_data in d.get("categories", {}).items():
                categories[name] = DriveCategory(
                    weight=cat_data.get("weight", 1.0),
                    source=cat_data.get("source", ""),
                )
            config.drives = DrivesConfig(
                pressure_rate=d.get("pressure_rate", config.drives.pressure_rate),
                trigger_threshold=d.get("trigger_threshold", config.drives.trigger_threshold),
                max_pressure=d.get("max_pressure", config.drives.max_pressure),
                success_decay=d.get("success_decay", config.drives.success_decay),
                failure_boost=d.get("failure_boost", config.drives.failure_boost),
                override_min_individual_pressure=d.get("override_min_individual_pressure", config.drives.override_min_individual_pressure),
                adaptive_decay=d.get("adaptive_decay", config.drives.adaptive_decay),
                categories=categories,
            )

        if "evaluator" in data:
            ev = data["evaluator"]
            rules_data = ev.get("rules", {})
            model_data = ev.get("model", {})
            config.evaluator = EvaluatorConfig(
                mode=ev.get("mode", config.evaluator.mode),
                rules=RulesConfig(
                    single_drive_threshold=rules_data.get("single_drive_threshold", config.evaluator.rules.single_drive_threshold),
                    combined_threshold=rules_data.get("combined_threshold", config.evaluator.rules.combined_threshold),
                    suppress_during_conversation=rules_data.get("suppress_during_conversation", config.evaluator.rules.suppress_during_conversation),
                    conversation_cooldown_minutes=rules_data.get("conversation_cooldown_minutes", config.evaluator.rules.conversation_cooldown_minutes),
                ),
                model=ModelEvalConfig(
                    base_url=cls._resolve_env(model_data.get("base_url", config.evaluator.model.base_url)),
                    api_key=cls._resolve_env(model_data.get("api_key", config.evaluator.model.api_key)),
                    model=model_data.get("model", config.evaluator.model.model),
                    max_tokens=model_data.get("max_tokens", config.evaluator.model.max_tokens),
                    temperature=model_data.get("temperature", config.evaluator.model.temperature),
                    timeout_seconds=model_data.get("timeout_seconds", config.evaluator.model.timeout_seconds),
                    max_suppress_minutes=model_data.get("max_suppress_minutes", config.evaluator.model.max_suppress_minutes),
                ),
            )

        if "sensors" in data:
            s = data["sensors"]
            fs = s.get("filesystem", {})
            sys_s = s.get("system", {})
            config.sensors = SensorsConfig(
                filesystem=FilesystemSensorConfig(
                    enabled=fs.get("enabled", config.sensors.filesystem.enabled),
                    watch_paths=fs.get("watch_paths", config.sensors.filesystem.watch_paths),
                    ignore_patterns=fs.get("ignore_patterns", config.sensors.filesystem.ignore_patterns),
                    ignore_self_writes=fs.get("ignore_self_writes", config.sensors.filesystem.ignore_self_writes),
                ),
                system=SystemSensorConfig(
                    enabled=sys_s.get("enabled", config.sensors.system.enabled),
                    memory_threshold_percent=sys_s.get("memory_threshold_percent", config.sensors.system.memory_threshold_percent),
                    watch_processes=sys_s.get("watch_processes", config.sensors.system.watch_processes),
                ),
            )

        if "logging" in data:
            lg = data["logging"]
            config.logging = LoggingConfig(
                level=lg.get("level", config.logging.level),
                file=lg.get("file", config.logging.file),
                sync_to_daily_notes=lg.get("sync_to_daily_notes", config.logging.sync_to_daily_notes),
            )

        if "daemon" in data:
            dm = data["daemon"]
            config.daemon = DaemonConfig(
                loop_interval_seconds=dm.get("loop_interval_seconds", config.daemon.loop_interval_seconds),
                shutdown_timeout=dm.get("shutdown_timeout", config.daemon.shutdown_timeout),
                pid_file=dm.get("pid_file", config.daemon.pid_file),
                health_port=dm.get("health_port", config.daemon.health_port),
                integration=dm.get("integration", config.daemon.integration),
            )

        if "state" in data:
            s = data["state"]
            config.state = StateConfig(
                dir=s.get("dir", config.state.dir),
                save_interval=s.get("save_interval", config.state.save_interval),
                history_retention_days=s.get("history_retention_days", config.state.history_retention_days),
            )

        if "generative" in data:
            g = data["generative"]
            config.generative = GenerativeConfig(
                enabled=g.get("enabled", config.generative.enabled),
                roadmap_files=g.get("roadmap_files", config.generative.roadmap_files),
                max_tasks=g.get("max_tasks", config.generative.max_tasks),
                auto_add_to_goals=g.get("auto_add_to_goals", config.generative.auto_add_to_goals),
                min_idle_minutes=g.get("min_idle_minutes", config.generative.min_idle_minutes),
            )

        if "parietal" in data:
            p = data["parietal"]
            config.parietal = ParietalConfig(
                enabled=p.get("enabled", config.parietal.enabled),
                scan_interval_hours=p.get("scan_interval_hours", config.parietal.scan_interval_hours),
                workspace_root=p.get("workspace_root", config.parietal.workspace_root),
                use_llm_inference=p.get("use_llm_inference", config.parietal.use_llm_inference),
                max_projects=p.get("max_projects", config.parietal.max_projects),
                max_sensors_per_project=p.get("max_sensors_per_project", config.parietal.max_sensors_per_project),
                ignored_dirs=p.get("ignored_dirs", config.parietal.ignored_dirs),
            )

        # Validate critical config
        config._validate()

        return config

    def _validate(self):
        """Validate config values."""
        import logging as _log
        _logger = _log.getLogger("pulse.config")
        errors = []
        
        if not self.openclaw.webhook_token:
            _logger.warning(
                "No webhook_token set — webhook calls will be unauthenticated. "
                "Set PULSE_HOOK_TOKEN or add webhook_token to pulse.yaml."
            )
        if self.drives.pressure_rate <= 0:
            errors.append("drives.pressure_rate must be positive")
        if self.drives.max_pressure <= 0:
            errors.append("drives.max_pressure must be positive")
        if self.drives.trigger_threshold <= 0:
            errors.append("drives.trigger_threshold must be positive")
        if self.drives.success_decay < 0:
            errors.append("drives.success_decay must be non-negative")
        if self.daemon.loop_interval_seconds < 1:
            errors.append("daemon.loop_interval_seconds must be >= 1")
        if not (1 <= self.daemon.health_port <= 65535):
            errors.append(f"daemon.health_port must be 1-65535, got {self.daemon.health_port}")
        if self.openclaw.max_turns_per_hour < 1:
            errors.append("openclaw.max_turns_per_hour must be >= 1")
        if self.openclaw.min_trigger_interval < 0:
            errors.append("openclaw.min_trigger_interval must be non-negative")
        if self.evaluator.mode not in ("rules", "model"):
            errors.append(f"evaluator.mode must be 'rules' or 'model', got '{self.evaluator.mode}'")
        if self.state.history_retention_days < 1:
            errors.append("state.history_retention_days must be >= 1")
        
        if errors:
            raise ValueError("Config validation errors:\n" + "\n".join(f"  - {e}" for e in errors))

    @classmethod
    def _resolve_env(cls, value: str, required: bool = False) -> str:
        """Replace ${ENV_VAR} patterns with environment variable values.
        
        Handles both full-string (${VAR}) and inline (prefix${VAR}suffix) patterns.
        Raises ValueError for required vars that are missing.
        """
        if not isinstance(value, str):
            return value

        import re
        def _replace(match):
            env_key = match.group(1)
            env_val = os.environ.get(env_key)
            if env_val is None:
                if required:
                    raise ValueError(
                        f"Required environment variable '{env_key}' is not set. "
                        f"Set it or update your pulse.yaml."
                    )
                return match.group(0)  # leave as-is
            return env_val

        return re.sub(r'\$\{([^}]+)\}', _replace, value)

    @classmethod
    def _check_config_permissions(cls, config_path: str):
        """Warn if config file is world-readable (may contain secrets)."""
        import stat
        try:
            mode = os.stat(config_path).st_mode
            if mode & stat.S_IROTH:
                import logging
                logging.getLogger("pulse.config").warning(
                    f"Config file {config_path} is world-readable (mode {oct(mode)}). "
                    f"Consider: chmod 600 {config_path}"
                )
        except OSError:
            pass
