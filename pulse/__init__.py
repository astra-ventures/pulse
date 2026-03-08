"""Compatibility package for historical `pulse.src` imports.

This project keeps implementation modules under `src/`, while external APIs and
entry points use the `pulse.src` namespace. This shim makes that import path
work in installed environments without forcing a nested package rewrite.
"""

import importlib
import sys

_src_module = importlib.import_module("src")
sys.modules[__name__ + ".src"] = _src_module
setattr(sys.modules[__name__], "src", _src_module)

# Convenience: expose version on the `pulse` shim as well.
__version__ = getattr(_src_module, "__version__", "0.0.0")
