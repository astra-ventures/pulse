"""
Pulse Plugin Architecture — Extensible module system for v0.3.0.

Allows community members to add custom modules to Pulse without forking
or modifying core source. Plugins are discovered at startup and called
each SENSE cycle.

Usage (plugin author):
    # Save as ~/.pulse/plugins/pulse_plugin_trading.py

    from pulse.src.plugin_registry import PulsePlugin

    class TradingModule(PulsePlugin):
        name = 'TRADING'
        version = '0.1.0'
        description = 'Monitors open positions and generates wealth drive pressure.'

        def sense(self) -> dict:
            return {'goals': 0.3}  # drive contributions this cycle

        def get_state(self) -> dict:
            return {'open_positions': 2, 'pnl_today': 48.50}

        def act(self, directive: str) -> bool:
            return False  # handled: True, not handled: False

Discovery:
    PluginRegistry auto-scans ~/.pulse/plugins/ for files matching
    pulse_plugin_*.py and imports any PulsePlugin subclass found.

    Standard entry points also supported (pulse.plugins group).

Integration:
    nervous_system.py calls registry.sense_all() in pre_sense(),
    registry.get_all_states() in state reporting, and
    registry.act_all(directive) for directive routing.
"""

import importlib.util
import inspect
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("pulse.plugin_registry")

_DEFAULT_PLUGIN_DIR = Path.home() / ".pulse" / "plugins"
_PLUGIN_FILE_PATTERN = "pulse_plugin_*.py"
_ENTRY_POINT_GROUP   = "pulse.plugins"


# ── Base class ────────────────────────────────────────────────────────────────

class PulsePlugin:
    """Base class for all Pulse plugins.

    Subclass this and implement the methods you need. All methods have
    safe defaults — you only need to override what your plugin uses.

    Minimal example:
        class MyModule(PulsePlugin):
            name = 'MY_MODULE'
            def sense(self) -> dict:
                return {'curiosity': 0.1}
    """

    # ── Class-level metadata (override in subclass) ────────────────────────
    name:        str = "UNNAMED_PLUGIN"
    version:     str = "0.1.0"
    description: str = ""
    author:      str = ""

    def __init__(self):
        self._enabled = True
        self._error_count = 0
        self._max_errors = 5  # disable after repeated failures

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_load(self) -> None:
        """Called once when plugin is first registered. Optional setup."""

    def on_unload(self) -> None:
        """Called when plugin is removed from registry. Optional cleanup."""

    # ── Core interface ────────────────────────────────────────────────────────

    def sense(self) -> dict:
        """Called each SENSE cycle. Return drive contribution dict.

        Keys should be drive names (curiosity, goals, connection, system, etc.)
        Values are floats — added to the base drive pressure for this cycle.

        Example:
            return {'goals': 0.2, 'curiosity': 0.1}
        """
        return {}

    def get_state(self) -> dict:
        """Return current plugin state for Observation API reporting.

        This dict appears under `plugins.{name}` in GET /state.
        """
        return {}

    def act(self, directive: str) -> bool:
        """Respond to a CORTEX directive string.

        Return True if the directive was handled by this plugin.
        Return False to let other plugins or the core system handle it.
        """
        return False

    # ── Health / introspection ────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled and self._error_count < self._max_errors

    def record_error(self, exc: Exception) -> None:
        """Called by registry when this plugin raises an exception."""
        self._error_count += 1
        if self._error_count >= self._max_errors:
            logger.warning(
                f"Plugin {self.name} disabled after {self._error_count} errors. "
                f"Last: {exc}"
            )
            self._enabled = False

    def reset_errors(self) -> None:
        """Re-enable after fixing errors."""
        self._error_count = 0
        self._enabled = True

    def health(self) -> dict:
        """Return health summary for this plugin."""
        return {
            "name": self.name,
            "version": self.version,
            "enabled": self.enabled,
            "error_count": self._error_count,
        }

    def __repr__(self) -> str:
        status = "enabled" if self.enabled else "disabled"
        return f"<PulsePlugin {self.name} v{self.version} [{status}]>"


# ── Registry ──────────────────────────────────────────────────────────────────

class PluginRegistry:
    """Central registry for all loaded Pulse plugins.

    Singleton: use PluginRegistry.get() or the module-level `registry`.
    """

    _instance: Optional["PluginRegistry"] = None

    @classmethod
    def get(cls) -> "PluginRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._plugins: Dict[str, PulsePlugin] = {}

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, plugin: PulsePlugin) -> bool:
        """Register a plugin instance. Returns True if newly registered."""
        if not isinstance(plugin, PulsePlugin):
            raise TypeError(f"Expected PulsePlugin instance, got {type(plugin)}")

        name = plugin.name
        if name in self._plugins:
            logger.debug(f"Plugin {name} already registered — skipping")
            return False

        try:
            plugin.on_load()
        except Exception as e:
            logger.warning(f"Plugin {name} on_load() failed: {e}")

        self._plugins[name] = plugin
        logger.info(f"Registered plugin: {plugin!r}")
        return True

    def unregister(self, name: str) -> bool:
        """Remove a plugin by name. Returns True if it was registered."""
        plugin = self._plugins.pop(name, None)
        if plugin is None:
            return False
        try:
            plugin.on_unload()
        except Exception as e:
            logger.warning(f"Plugin {name} on_unload() failed: {e}")
        logger.info(f"Unregistered plugin: {name}")
        return True

    def clear(self) -> None:
        """Remove all plugins (used in tests)."""
        for name in list(self._plugins):
            self.unregister(name)

    # ── SENSE cycle ───────────────────────────────────────────────────────────

    def sense_all(self) -> dict:
        """Call sense() on all enabled plugins. Merge drive contributions.

        Returns: merged dict of {drive_name: total_contribution}
        Failures are caught and recorded per-plugin.
        """
        merged: dict = {}
        for plugin in list(self._plugins.values()):
            if not plugin.enabled:
                continue
            try:
                contributions = plugin.sense()
                if contributions:
                    for drive, delta in contributions.items():
                        merged[drive] = merged.get(drive, 0.0) + float(delta)
            except Exception as e:
                plugin.record_error(e)
                logger.warning(f"Plugin {plugin.name} sense() failed: {e}")
        return merged

    # ── Observation API ───────────────────────────────────────────────────────

    def get_all_states(self) -> dict:
        """Return state from all enabled plugins. Dict keyed by plugin name."""
        states = {}
        for plugin in list(self._plugins.values()):
            if not plugin.enabled:
                continue
            try:
                states[plugin.name] = plugin.get_state()
            except Exception as e:
                plugin.record_error(e)
                logger.warning(f"Plugin {plugin.name} get_state() failed: {e}")
                states[plugin.name] = {"error": str(e)}
        return states

    # ── Directive routing ─────────────────────────────────────────────────────

    def act_all(self, directive: str) -> List[str]:
        """Route a directive to all plugins. Return list of names that handled it."""
        handled = []
        for plugin in list(self._plugins.values()):
            if not plugin.enabled:
                continue
            try:
                if plugin.act(directive):
                    handled.append(plugin.name)
            except Exception as e:
                plugin.record_error(e)
                logger.warning(f"Plugin {plugin.name} act() failed: {e}")
        return handled

    # ── Health ────────────────────────────────────────────────────────────────

    def health_all(self) -> List[dict]:
        """Return health dict for all registered plugins (including disabled)."""
        return [p.health() for p in self._plugins.values()]

    @property
    def count(self) -> int:
        return len(self._plugins)

    @property
    def enabled_count(self) -> int:
        return sum(1 for p in self._plugins.values() if p.enabled)

    def __contains__(self, name: str) -> bool:
        return name in self._plugins

    def __repr__(self) -> str:
        return f"<PluginRegistry {self.count} plugins ({self.enabled_count} enabled)>"


# ── Discovery ─────────────────────────────────────────────────────────────────

def _find_plugin_classes(module: Any) -> List[type]:
    """Find all PulsePlugin subclasses in a module (excluding the base class)."""
    classes = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if (
            issubclass(obj, PulsePlugin)
            and obj is not PulsePlugin
            and obj.__module__ == module.__name__
        ):
            classes.append(obj)
    return classes


def load_plugin_file(path: Path) -> Tuple[List[PulsePlugin], List[str]]:
    """Import a plugin file and instantiate any PulsePlugin subclasses.

    Returns (instances, errors).
    """
    instances = []
    errors = []

    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        errors.append(f"Could not create spec for {path}")
        return instances, errors

    module = importlib.util.module_from_spec(spec)
    # Use the stem as module name to make __module__ checks work
    module.__name__ = path.stem
    sys.modules[path.stem] = module

    try:
        spec.loader.exec_module(module)
    except Exception as e:
        errors.append(f"Error executing {path.name}: {e}")
        return instances, errors

    classes = _find_plugin_classes(module)
    if not classes:
        errors.append(f"No PulsePlugin subclasses found in {path.name}")
        return instances, errors

    for cls in classes:
        try:
            instance = cls()
            instances.append(instance)
        except Exception as e:
            errors.append(f"Error instantiating {cls.__name__}: {e}")

    return instances, errors


def discover_plugins(
    plugin_dir: Optional[Path] = None,
    registry: Optional[PluginRegistry] = None,
    pattern: str = _PLUGIN_FILE_PATTERN,
) -> Tuple[int, List[str]]:
    """Scan plugin_dir for pulse_plugin_*.py files and register them.

    Also scans entry points in the 'pulse.plugins' group if available.

    Returns (registered_count, error_list).
    """
    reg = registry or PluginRegistry.get()
    pdir = plugin_dir or _DEFAULT_PLUGIN_DIR

    registered = 0
    all_errors: List[str] = []

    # 1. File-based discovery
    if pdir.is_dir():
        plugin_files = sorted(pdir.glob(pattern))
        for fpath in plugin_files:
            instances, errors = load_plugin_file(fpath)
            all_errors.extend(errors)
            for inst in instances:
                if reg.register(inst):
                    registered += 1
    else:
        logger.debug(f"Plugin dir not found: {pdir} — skipping file discovery")

    # 2. Entry-point discovery (optional: requires importlib.metadata)
    try:
        from importlib.metadata import entry_points
        eps = entry_points(group=_ENTRY_POINT_GROUP)
        for ep in eps:
            try:
                cls = ep.load()
                if inspect.isclass(cls) and issubclass(cls, PulsePlugin) and cls is not PulsePlugin:
                    inst = cls()
                    if reg.register(inst):
                        registered += 1
            except Exception as e:
                all_errors.append(f"Entry point {ep.name}: {e}")
    except Exception:
        pass  # importlib.metadata not available or no entry points

    if registered > 0:
        logger.info(f"Discovered {registered} plugin(s) from {pdir}")
    if all_errors:
        for err in all_errors:
            logger.warning(f"Plugin discovery: {err}")

    return registered, all_errors


# ── Module-level singleton ────────────────────────────────────────────────────

#: Module-level registry singleton. Use this for production code.
registry = PluginRegistry.get()
