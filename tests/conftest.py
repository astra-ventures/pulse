"""Test configuration — set up import path for pulse package."""
import sys
from pathlib import Path

# The source uses `pulse.src.X` imports. Create a fake `pulse` package
# by adding the parent directory and symlinking.
repo_root = Path(__file__).parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

# Make `pulse.src` importable by treating repo root as a package
import types
if "pulse" not in sys.modules:
    pulse_pkg = types.ModuleType("pulse")
    pulse_pkg.__path__ = [str(repo_root)]
    sys.modules["pulse"] = pulse_pkg


# ── Optional dependency stubs ─────────────────────────────────────────────────
# `rich` is a runtime dependency but may not be installed in the test environment.
# Provide a minimal stub so tests that import cli.py (which uses rich) can run.

def _make_rich_stub():
    """Create minimal rich stub covering everything cli.py uses."""
    import io

    class _Console:
        def __init__(self, *a, **kw):
            self.no_color = False
            self._buf = io.StringIO()

        def print(self, *args, **kwargs):
            # Strip rich markup tags [bold], [green], etc. for clean output
            import re
            parts = []
            for a in args:
                parts.append(str(a))  # _Table.__str__() renders rows
            text = " ".join(parts)
            text = re.sub(r"\[/?[^\]]*\]", "", text)
            print(text)  # let pytest capsys capture it

        def rule(self, *a, **kw):
            pass

    class _Table:
        def __init__(self, *a, **kw):
            self._rows = []
        def add_column(self, *a, **kw):
            pass
        def add_row(self, *args, **kw):
            import re
            self._rows.append([re.sub(r"\[/?[^\]]*\]", "", str(c)) for c in args])
        def __str__(self):
            return "\n".join("  ".join(row) for row in self._rows)

    class _Panel:
        def __init__(self, *a, **kw):
            pass

    class _Text:
        def __init__(self, *a, **kw):
            pass

    rich = types.ModuleType("rich")
    rich.console = types.ModuleType("rich.console")
    rich.console.Console = _Console
    rich.table = types.ModuleType("rich.table")
    rich.table.Table = _Table
    rich.panel = types.ModuleType("rich.panel")
    rich.panel.Panel = _Panel
    rich.text = types.ModuleType("rich.text")
    rich.text.Text = _Text
    rich.markup = types.ModuleType("rich.markup")
    rich.markup.escape = lambda s: s

    class _Columns:
        def __init__(self, *a, **kw):
            pass

    class _BarColumn:
        def __init__(self, *a, **kw):
            pass

    class _Progress:
        def __init__(self, *a, **kw):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def add_task(self, *a, **kw):
            return 0
        def update(self, *a, **kw):
            pass

    rich.columns = types.ModuleType("rich.columns")
    rich.columns.Columns = _Columns
    rich.progress = types.ModuleType("rich.progress")
    rich.progress.Progress = _Progress
    rich.progress.BarColumn = _BarColumn
    rich.progress.TextColumn = _BarColumn
    rich.progress.TimeRemainingColumn = _BarColumn
    rich.progress.SpinnerColumn = _BarColumn

    class _box:
        SIMPLE = None
        ROUNDED = None
        MINIMAL = None
        HORIZONTALS = None
        SIMPLE_HEAVY = None
        SIMPLE_HEAD = None
        HEAVY = None
        HEAVY_EDGE = None
        HEAVY_HEAD = None
        DOUBLE = None
        DOUBLE_EDGE = None
        SQUARE = None
        MARKDOWN = None
        MINIMAL_HEAVY_HEAD = None
        MINIMAL_DOUBLE_HEAD = None
        ASCII = None
        ASCII2 = None
        ASCII_DOUBLE_HEAD = None

    rich_box = types.ModuleType("rich.box")
    rich_box.__dict__.update({k: None for k in dir(_box) if not k.startswith("_")})
    rich.box = rich_box

    # Register all submodules in sys.modules
    sys.modules["rich"] = rich
    sys.modules["rich.console"] = rich.console
    sys.modules["rich.table"] = rich.table
    sys.modules["rich.panel"] = rich.panel
    sys.modules["rich.text"] = rich.text
    sys.modules["rich.markup"] = rich.markup
    sys.modules["rich.columns"] = rich.columns
    sys.modules["rich.progress"] = rich.progress
    sys.modules["rich.box"] = rich.box

    return rich


try:
    import rich  # noqa: F401
except ImportError:
    _make_rich_stub()
