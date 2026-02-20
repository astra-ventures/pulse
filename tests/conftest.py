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
