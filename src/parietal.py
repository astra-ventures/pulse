"""PARIETAL — World Model Module for Pulse.

Discovers operational systems, infers health signals, builds dynamic sensors,
and registers them with SensorManager. Learns which signals matter via
PLASTICITY feedback.

The parietal lobe integrates multisensory signals to build a model of the
world and your place in it. PARIETAL never waits to be told what to watch —
it reads the environment, reasons about what matters, and builds its own
observability layer.
"""

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pulse.parietal")

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "parietal-state.json"

# Project-type detection keywords
_TRADING_KEYWORDS = {"trade", "kelly", "polymarket", "kalshi", "bet", "wager", "prediction"}

# Directories to always skip during scanning
_IGNORED_DIRS = {".git", "node_modules", "__pycache__", "venv", ".venv", "dist", "build"}


@dataclass
class HealthSignal:
    """A single health signal for a discovered system."""
    id: str
    type: str  # file_age, file_content, http_health, git_status
    target: str  # file path or URL
    healthy_if: str  # condition expression
    drive_impact: str = "system"  # goals, system, curiosity
    weight: float = 0.5

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "HealthSignal":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class GoalCondition:
    """A measurable goal extracted from project files."""
    description: str
    measurable: str
    status: str = "pending"  # pending, met, failed

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GoalCondition":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Project:
    """A discovered project in the workspace."""
    name: str
    path: str
    type: str
    description: str = ""
    health_signals: List[HealthSignal] = field(default_factory=list)
    goal_conditions: List[GoalCondition] = field(default_factory=list)
    discovered_at: float = 0.0
    last_checked: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["health_signals"] = [s.to_dict() for s in self.health_signals]
        d["goal_conditions"] = [g.to_dict() for g in self.goal_conditions]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        signals = [HealthSignal.from_dict(s) for s in d.get("health_signals", [])]
        goals = [GoalCondition.from_dict(g) for g in d.get("goal_conditions", [])]
        return cls(
            name=d["name"],
            path=d["path"],
            type=d.get("type", "unknown"),
            description=d.get("description", ""),
            health_signals=signals,
            goal_conditions=goals,
            discovered_at=d.get("discovered_at", 0.0),
            last_checked=d.get("last_checked", 0.0),
        )


@dataclass
class Deployment:
    """A discovered deployment/service."""
    name: str
    url: str
    expected_status: int = 200
    drive_impact: str = "system"
    weight: float = 1.0
    last_checked: Optional[float] = None
    last_status: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Deployment":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class WorldModel:
    """The complete world model maintained by PARIETAL."""
    projects: List[Project] = field(default_factory=list)
    deployments: List[Deployment] = field(default_factory=list)
    goal_conditions: List[GoalCondition] = field(default_factory=list)
    signal_weights: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "projects": [p.to_dict() for p in self.projects],
            "deployments": [d.to_dict() for d in self.deployments],
            "goal_conditions": [g.to_dict() for g in self.goal_conditions],
            "signal_weights": dict(self.signal_weights),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WorldModel":
        return cls(
            projects=[Project.from_dict(p) for p in d.get("projects", [])],
            deployments=[Deployment.from_dict(dp) for dp in d.get("deployments", [])],
            goal_conditions=[GoalCondition.from_dict(g) for g in d.get("goal_conditions", [])],
            signal_weights=d.get("signal_weights", {}),
        )


@dataclass
class SignalResult:
    """Result of checking a single health signal."""
    signal_id: str
    healthy: bool
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class Parietal:
    """World Model — environment discovery, signal inference, dynamic sensors."""

    def __init__(self, state_dir: Optional[Path] = None,
                 max_projects: int = 50,
                 max_sensors_per_project: int = 5,
                 scan_interval_hours: float = 6.0):
        self.state_dir = Path(state_dir) if state_dir else _DEFAULT_STATE_DIR
        self.state_file = self.state_dir / "parietal-state.json"
        self.max_projects = max_projects
        self.max_sensors_per_project = max_sensors_per_project
        self.scan_interval_hours = scan_interval_hours

        self.world_model = WorldModel()
        self.last_scan_time: float = 0.0
        self.discovery_count: int = 0
        self._registered_sensor_ids: set = set()

        self._load_state()

    # ─── State Persistence ────────────────────────────────────

    def _load_state(self):
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                wm = data.get("world_model", {})
                self.world_model = WorldModel.from_dict(wm)
                self.last_scan_time = data.get("last_discovery", 0.0) or 0.0
                self.discovery_count = data.get("discovery_count", 0)
                # Restore signal weights into model
                for sig_id, w in self.world_model.signal_weights.items():
                    for proj in self.world_model.projects:
                        for sig in proj.health_signals:
                            if sig.id == sig_id:
                                sig.weight = w
            except (json.JSONDecodeError, OSError, TypeError):
                pass

    def _save_state(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "world_model": self.world_model.to_dict(),
            "last_discovery": self.last_scan_time,
            "discovery_count": self.discovery_count,
        }
        self.state_file.write_text(json.dumps(data, indent=2))

    # ─── Discovery ────────────────────────────────────────────

    def scan(self, workspace_root: str, llm_endpoint: Optional[str] = None) -> WorldModel:
        """Main discovery method. Walk workspace, detect projects, infer signals."""
        root = Path(workspace_root).expanduser()
        if not root.exists():
            logger.warning(f"PARIETAL: workspace root does not exist: {root}")
            return self.world_model

        now = time.time()
        discovered_projects: List[Project] = []
        discovered_deployments: List[Deployment] = []
        discovered_goals: List[GoalCondition] = []

        # Walk up to 3 levels deep
        for dirpath in self._walk_dirs(root, max_depth=3):
            if len(discovered_projects) >= self.max_projects:
                break

            project_type = self._detect_project_type(dirpath)
            if project_type is None:
                continue

            name = dirpath.name
            description = self._read_description(dirpath)

            signals = self._infer_signals(dirpath, project_type, description, llm_endpoint)
            signals = signals[:self.max_sensors_per_project]

            goals = self._extract_goal_conditions(dirpath)

            # Extract deployments from config files
            deps = self._extract_deployments(dirpath, name)
            discovered_deployments.extend(deps)

            discovered_projects.append(Project(
                name=name,
                path=str(dirpath),
                type=project_type,
                description=description[:500],
                health_signals=signals,
                goal_conditions=goals,
                discovered_at=now,
                last_checked=now,
            ))

            discovered_goals.extend(goals)

        # Preserve existing signal weights
        old_weights = dict(self.world_model.signal_weights)

        self.world_model = WorldModel(
            projects=discovered_projects,
            deployments=discovered_deployments,
            goal_conditions=discovered_goals,
            signal_weights=old_weights,
        )

        # Apply persisted weights to new signals
        for proj in self.world_model.projects:
            for sig in proj.health_signals:
                if sig.id in old_weights:
                    sig.weight = old_weights[sig.id]

        self.last_scan_time = now
        self.discovery_count += 1
        self._save_state()

        logger.info(
            f"PARIETAL scan #{self.discovery_count}: "
            f"{len(discovered_projects)} projects, "
            f"{len(discovered_deployments)} deployments, "
            f"{sum(len(p.health_signals) for p in discovered_projects)} signals"
        )

        return self.world_model

    def _walk_dirs(self, root: Path, max_depth: int) -> List[Path]:
        """Walk directories up to max_depth levels."""
        dirs = []
        # Include root itself
        dirs.append(root)
        if max_depth <= 0:
            return dirs

        try:
            for entry in sorted(root.iterdir()):
                if entry.is_dir() and entry.name not in _IGNORED_DIRS and not entry.name.startswith("."):
                    dirs.append(entry)
                    if max_depth > 1:
                        try:
                            for sub in sorted(entry.iterdir()):
                                if sub.is_dir() and sub.name not in _IGNORED_DIRS and not sub.name.startswith("."):
                                    dirs.append(sub)
                                    if max_depth > 2:
                                        try:
                                            for subsub in sorted(sub.iterdir()):
                                                if subsub.is_dir() and subsub.name not in _IGNORED_DIRS and not subsub.name.startswith("."):
                                                    dirs.append(subsub)
                                        except PermissionError:
                                            pass
                        except PermissionError:
                            pass
        except PermissionError:
            pass

        return dirs

    def _detect_project_type(self, path: Path) -> Optional[str]:
        """Detect project type from marker files. Returns None if not a project."""
        markers = {}
        try:
            children = {c.name for c in path.iterdir() if not c.name.startswith(".")}
        except PermissionError:
            return None

        if "package.json" in children:
            markers["node"] = True
        if "pyproject.toml" in children or "setup.py" in children:
            markers["python"] = True
        if "requirements.txt" in children:
            markers["python"] = True
        if "go.mod" in children:
            markers["go"] = True
        if "Cargo.toml" in children:
            markers["rust"] = True
        if "Dockerfile" in children or "docker-compose.yml" in children:
            markers["docker"] = True
        if "wrangler.toml" in children:
            markers["cloudflare_worker"] = True
        if "fly.toml" in children:
            markers["fly_app"] = True
        if "logs" in children and (path / "logs").is_dir():
            markers["has_logs"] = True

        # Check for python files at root level
        py_files = [c for c in children if c.endswith(".py")]
        if py_files:
            markers["python"] = True

        if not markers:
            return None

        # Check for trading bot indicators
        if self._is_trading_project(path, children):
            return "trading_bot"

        if "cloudflare_worker" in markers:
            return "cloudflare_worker"
        if "fly_app" in markers:
            return "fly_app"
        if "go" in markers:
            return "go_service"
        if "rust" in markers:
            return "rust_service"
        if "node" in markers:
            return "node_project"
        if "python" in markers:
            return "python_project"
        if "docker" in markers:
            return "docker_service"

        return "generic"

    def _is_trading_project(self, path: Path, children: set) -> bool:
        """Check if a project looks like a trading bot."""
        # Check filenames and directory names for trading keywords
        lower_children = {c.lower() for c in children}
        if lower_children & _TRADING_KEYWORDS:
            return True

        # Check a few key files for trading keywords
        for fname in ["README.md", "pyproject.toml", "package.json"]:
            if fname in children:
                try:
                    content = (path / fname).read_text(errors="ignore")[:2000].lower()
                    if any(kw in content for kw in _TRADING_KEYWORDS):
                        return True
                except (OSError, PermissionError):
                    pass
        return False

    def _read_description(self, path: Path) -> str:
        """Read project description from README or similar files."""
        for fname in ["README.md", "PROJECTS.md", "DESCRIPTION.md", "package.json"]:
            fpath = path / fname
            if fpath.exists():
                try:
                    content = fpath.read_text(errors="ignore")[:1000]
                    if fname == "package.json":
                        try:
                            pkg = json.loads(fpath.read_text())
                            return pkg.get("description", "")[:500]
                        except (json.JSONDecodeError, OSError):
                            pass
                    return content[:500]
                except (OSError, PermissionError):
                    pass
        return ""

    # ─── Signal Inference ─────────────────────────────────────

    def _infer_signals(self, path: Path, project_type: str, description: str,
                       llm_endpoint: Optional[str] = None) -> List[HealthSignal]:
        """Infer health signals using heuristics first, LLM second."""
        signals: List[HealthSignal] = []
        name = path.name

        # Log files — watch for age and errors
        logs_dir = path / "logs"
        if logs_dir.exists() and logs_dir.is_dir():
            try:
                log_files = [f for f in logs_dir.iterdir()
                             if f.suffix in (".log", ".jsonl") and f.is_file()]
                for lf in log_files[:3]:
                    signals.append(HealthSignal(
                        id=f"{name}_log_{lf.stem}",
                        type="file_age",
                        target=str(lf),
                        healthy_if="age_hours < 48",
                        drive_impact="system",
                        weight=0.6,
                    ))
            except PermissionError:
                pass

        # Trading bot — watch for recent trades
        if project_type == "trading_bot":
            trade_logs = list(logs_dir.glob("*trade*")) if logs_dir.exists() else []
            for tl in trade_logs[:2]:
                signals.append(HealthSignal(
                    id=f"{name}_trades_{tl.stem}",
                    type="file_age",
                    target=str(tl),
                    healthy_if="age_hours < 24",
                    drive_impact="goals",
                    weight=0.8,
                ))

        # Cloudflare worker — infer health endpoint
        wrangler = path / "wrangler.toml"
        if wrangler.exists():
            url = self._extract_cf_health_url(wrangler)
            if url:
                signals.append(HealthSignal(
                    id=f"{name}_cf_health",
                    type="http_health",
                    target=url,
                    healthy_if="status == 200",
                    drive_impact="system",
                    weight=0.9,
                ))

        # Fly.io app — infer health endpoint
        fly_toml = path / "fly.toml"
        if fly_toml.exists():
            url = self._extract_fly_health_url(fly_toml)
            if url:
                signals.append(HealthSignal(
                    id=f"{name}_fly_health",
                    type="http_health",
                    target=url,
                    healthy_if="status == 200",
                    drive_impact="system",
                    weight=0.9,
                ))

        # Git status — uncommitted changes
        git_dir = path / ".git"
        if git_dir.exists():
            signals.append(HealthSignal(
                id=f"{name}_git_status",
                type="git_status",
                target=str(path),
                healthy_if="no_uncommitted",
                drive_impact="system",
                weight=0.3,
            ))

        # Tests directory — watch for output
        tests_dir = path / "tests"
        if tests_dir.exists() and tests_dir.is_dir():
            signals.append(HealthSignal(
                id=f"{name}_tests",
                type="file_age",
                target=str(tests_dir),
                healthy_if="age_hours < 168",
                drive_impact="curiosity",
                weight=0.3,
            ))

        return signals

    def _extract_cf_health_url(self, wrangler_path: Path) -> Optional[str]:
        """Extract health URL from wrangler.toml."""
        try:
            content = wrangler_path.read_text(errors="ignore")
            # Look for route patterns
            match = re.search(r'route\s*=\s*"([^"]+)"', content)
            if match:
                route = match.group(1).rstrip("/*")
                return f"https://{route}/health"
            # Look for name and construct workers.dev URL
            match = re.search(r'name\s*=\s*"([^"]+)"', content)
            if match:
                return f"https://{match.group(1)}.workers.dev/health"
        except (OSError, PermissionError):
            pass
        return None

    def _extract_fly_health_url(self, fly_path: Path) -> Optional[str]:
        """Extract health URL from fly.toml."""
        try:
            content = fly_path.read_text(errors="ignore")
            match = re.search(r'app\s*=\s*"([^"]+)"', content)
            if match:
                return f"https://{match.group(1)}.fly.dev/health"
        except (OSError, PermissionError):
            pass
        return None

    def _extract_deployments(self, path: Path, project_name: str) -> List[Deployment]:
        """Extract deployment URLs from config files."""
        deployments: List[Deployment] = []

        # Check .env for URLs
        env_file = path / ".env"
        if env_file.exists():
            try:
                content = env_file.read_text(errors="ignore")
                urls = re.findall(r'https?://[^\s"\']+/health', content)
                for url in urls[:3]:
                    deployments.append(Deployment(
                        name=f"{project_name}_env",
                        url=url,
                    ))
            except (OSError, PermissionError):
                pass

        return deployments

    def _extract_goal_conditions(self, path: Path) -> List[GoalCondition]:
        """Extract measurable goal conditions from project files."""
        goals: List[GoalCondition] = []

        for fname in ["PROJECTS.md", "TIERS.md", "goals.py", "GOALS.md"]:
            fpath = path / fname
            if not fpath.exists():
                continue
            try:
                content = fpath.read_text(errors="ignore")[:3000]
                # Extract checkbox items (common in project tracking files)
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith("- [ ]"):
                        desc = line[5:].strip()[:200]
                        if desc:
                            goals.append(GoalCondition(
                                description=desc,
                                measurable=f"Checkbox item in {fname}",
                                status="pending",
                            ))
                    elif line.startswith("- [x]") or line.startswith("- [X]"):
                        desc = line[5:].strip()[:200]
                        if desc:
                            goals.append(GoalCondition(
                                description=desc,
                                measurable=f"Checkbox item in {fname}",
                                status="met",
                            ))
            except (OSError, PermissionError):
                pass

        return goals[:20]

    # ─── Sensor Registration ──────────────────────────────────

    def register_sensors(self, sensor_manager) -> int:
        """Register dynamic sensors with SensorManager. Returns count."""
        from pulse.src.sensors.parietal_sensors import (
            ParietalFileSensor,
            ParietalFileContentSensor,
            ParietalHttpSensor,
            ParietalGitSensor,
        )

        count = 0
        for project in self.world_model.projects:
            for signal in project.health_signals:
                if signal.id in self._registered_sensor_ids:
                    continue

                sensor = None
                if signal.type == "file_age":
                    sensor = ParietalFileSensor(signal)
                elif signal.type == "file_content":
                    sensor = ParietalFileContentSensor(signal)
                elif signal.type == "http_health":
                    sensor = ParietalHttpSensor(signal)
                elif signal.type == "git_status":
                    sensor = ParietalGitSensor(signal)

                if sensor and hasattr(sensor_manager, 'add_sensor'):
                    sensor_manager.add_sensor(sensor)
                    self._registered_sensor_ids.add(signal.id)
                    count += 1

        return count

    # ─── Health Checks ────────────────────────────────────────

    def check_all(self) -> List[SignalResult]:
        """Run all health signals synchronously. Returns results."""
        results: List[SignalResult] = []

        for project in self.world_model.projects:
            for signal in project.health_signals:
                result = self._check_signal(signal)
                results.append(result)

        return results

    def _check_signal(self, signal: HealthSignal) -> SignalResult:
        """Check a single health signal."""
        try:
            if signal.type == "file_age":
                return self._check_file_age(signal)
            elif signal.type == "file_content":
                return self._check_file_content(signal)
            elif signal.type == "git_status":
                return self._check_git_status(signal)
            elif signal.type == "http_health":
                return SignalResult(
                    signal_id=signal.id,
                    healthy=True,
                    details={"note": "http checks require async — use sensor"},
                )
        except Exception as e:
            return SignalResult(
                signal_id=signal.id,
                healthy=False,
                details={"error": str(e)},
            )

        return SignalResult(signal_id=signal.id, healthy=True, details={})

    def _check_file_age(self, signal: HealthSignal) -> SignalResult:
        """Check file age signal."""
        path = Path(signal.target)
        if not path.exists():
            return SignalResult(
                signal_id=signal.id,
                healthy=False,
                details={"status": "missing"},
            )

        age_hours = (time.time() - path.stat().st_mtime) / 3600
        healthy = _eval_condition(signal.healthy_if, {"age_hours": age_hours})
        return SignalResult(
            signal_id=signal.id,
            healthy=healthy,
            details={"age_hours": round(age_hours, 2)},
        )

    def _check_file_content(self, signal: HealthSignal) -> SignalResult:
        """Check file content signal."""
        path = Path(signal.target)
        if not path.exists():
            return SignalResult(
                signal_id=signal.id,
                healthy=False,
                details={"status": "missing"},
            )

        try:
            content = path.read_text(errors="ignore")
            lines = content.strip().splitlines()
            last_line = lines[-1] if lines else ""
            return SignalResult(
                signal_id=signal.id,
                healthy=bool(last_line),
                details={"lines": len(lines), "last_line_preview": last_line[:100]},
            )
        except (OSError, PermissionError) as e:
            return SignalResult(
                signal_id=signal.id,
                healthy=False,
                details={"error": str(e)},
            )

    def _check_git_status(self, signal: HealthSignal) -> SignalResult:
        """Check git status for uncommitted changes."""
        import subprocess
        try:
            result = subprocess.run(
                ["git", "-C", signal.target, "status", "--porcelain"],
                capture_output=True, text=True, timeout=5,
            )
            has_changes = bool(result.stdout.strip())
            return SignalResult(
                signal_id=signal.id,
                healthy=not has_changes,
                details={"has_uncommitted": has_changes},
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            return SignalResult(
                signal_id=signal.id,
                healthy=True,
                details={"error": str(e)},
            )

    # ─── Weight Updates (PLASTICITY feedback) ─────────────────

    def update_signal_weight(self, signal_id: str, outcome: str):
        """Update signal weight based on PLASTICITY feedback.

        outcome: "actionable" → increase by 0.05 (max 1.0)
                 "noise" → decrease by 0.03 (min 0.1)
        """
        delta = 0.05 if outcome == "actionable" else -0.03

        for project in self.world_model.projects:
            for signal in project.health_signals:
                if signal.id == signal_id:
                    signal.weight = max(0.1, min(1.0, signal.weight + delta))
                    self.world_model.signal_weights[signal_id] = signal.weight
                    self._save_state()
                    return

    # ─── Context for CORTEX ───────────────────────────────────

    def get_context(self) -> dict:
        """Return compact summary for CORTEX context injection."""
        results = self.check_all()

        healthy = []
        unhealthy = []

        for r in results:
            if r.healthy:
                healthy.append(r.signal_id)
            else:
                detail = r.details.get("status", "")
                age = r.details.get("age_hours")
                if age is not None:
                    detail = f"age {age:.0f}h"
                unhealthy.append(f"{r.signal_id}: {detail}" if detail else r.signal_id)

        pending_goals = []
        for proj in self.world_model.projects:
            for g in proj.goal_conditions:
                if g.status == "pending":
                    pending_goals.append(g.description[:80])

        elapsed = time.time() - self.last_scan_time if self.last_scan_time else None
        last_scan_str = f"{elapsed / 3600:.1f}h ago" if elapsed is not None else "never"

        return {
            "systems_monitored": sum(len(p.health_signals) for p in self.world_model.projects),
            "unhealthy": unhealthy,
            "healthy": healthy,
            "goal_conditions_pending": pending_goals[:10],
            "last_scan": last_scan_str,
        }

    def get_status(self) -> dict:
        """Return parietal status summary."""
        return {
            "projects": len(self.world_model.projects),
            "deployments": len(self.world_model.deployments),
            "signals": sum(len(p.health_signals) for p in self.world_model.projects),
            "discovery_count": self.discovery_count,
            "last_scan": self.last_scan_time,
        }


def _eval_condition(condition: str, variables: dict) -> bool:
    """Safely evaluate a health condition expression.

    Supports simple comparisons: 'age_hours < 24', 'status == 200', etc.
    """
    # Parse simple conditions like "age_hours < 24", "status == 200"
    match = re.match(r'(\w+)\s*(<=?|>=?|==|!=)\s*(\d+\.?\d*)', condition)
    if match:
        var_name, op, val_str = match.groups()
        var_val = variables.get(var_name)
        if var_val is None:
            return False
        val = float(val_str)
        if op == "<":
            return var_val < val
        elif op == "<=":
            return var_val <= val
        elif op == ">":
            return var_val > val
        elif op == ">=":
            return var_val >= val
        elif op == "==":
            return var_val == val
        elif op == "!=":
            return var_val != val

    # Special conditions
    if condition == "no_uncommitted":
        return not variables.get("has_uncommitted", False)

    # Fallback: unknown condition = healthy
    return True
