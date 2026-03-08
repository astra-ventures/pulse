"""Pulse module entrypoint.

Enables:
  python3 -m pulse

This runs the Pulse daemon (equivalent to `python3 -m pulse.src`).
The interactive CLI is exposed via the `pulse` console script.
"""

from src.__main__ import main


if __name__ == "__main__":
    main()
