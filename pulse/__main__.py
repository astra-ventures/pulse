"""Pulse module entrypoint.

Enables:
  python3 -m pulse

Behavior:
- With no args: start the Pulse daemon (same as `pulse-daemon`).
- With args: run the CLI (same as the `pulse` console script), e.g.
    python3 -m pulse doctor

This keeps `python -m pulse` as the simplest foreground daemon run, while also
supporting docs/examples that use `python -m pulse <command>` when the `pulse`
binary isn't on PATH.
"""

import sys


def main() -> None:
    # If args are provided, treat this as CLI invocation.
    if len(sys.argv) > 1:
        from pulse.src.cli import main as cli_main

        cli_main()
        return

    # No args → daemon.
    from src.__main__ import main as daemon_main

    daemon_main()


if __name__ == "__main__":
    main()
